"""Contract tests for the private local capture helper."""

import asyncio
import base64
import io
import json
from collections.abc import Mapping
from typing import TypedDict

import pytest

from app.domain.vision import ScreenAnalysis, TextBlock
from app.infrastructure.local_capture_helper import (
    HelperRequest,
    LocalCaptureHelper,
    run_helper,
)
from app.infrastructure.wasapi_loopback_capture import SystemAudioCaptureError


class RecordedEvent(TypedDict):
    id: str | None
    event: str
    payload: dict[str, object]


class RecordingOutput:
    def __init__(self) -> None:
        self.events: list[RecordedEvent] = []

    async def emit(
        self, request_id: str | None, event: str, payload: Mapping[str, object]
    ) -> None:
        self.events.append({"id": request_id, "event": event, "payload": dict(payload)})


class FakeAnalyzer:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.images: list[bytes] = []

    async def analyze(self, image_bytes: bytes) -> ScreenAnalysis:
        self.images.append(image_bytes)
        if self.failure is not None:
            raise self.failure
        return ScreenAnalysis(
            width=1280,
            height=720,
            blocks=(TextBlock("What is Python?", 0.97, ()),),
        )


class FakeAudioCapture:
    def __init__(self, start_failure: Exception | None = None) -> None:
        self.start_failure = start_failure
        self.started = 0
        self.stopped = 0
        self.chunks: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self) -> None:
        if self.start_failure is not None:
            raise self.start_failure
        self.started += 1

    async def read_pcm16le(self) -> bytes:
        return await self.chunks.get()

    async def stop(self) -> None:
        self.stopped += 1


def make_helper(
    analyzer: FakeAnalyzer | None = None,
    audio: FakeAudioCapture | None = None,
) -> tuple[LocalCaptureHelper, RecordingOutput, FakeAnalyzer, FakeAudioCapture]:
    output = RecordingOutput()
    selected_analyzer = analyzer or FakeAnalyzer()
    selected_audio = audio or FakeAudioCapture()
    return (
        LocalCaptureHelper(selected_analyzer, selected_audio, output),
        output,
        selected_analyzer,
        selected_audio,
    )


@pytest.mark.asyncio
async def test_ping_advertises_local_capabilities() -> None:
    helper, output, _, _ = make_helper()

    assert await helper.handle(
        HelperRequest(version="1.0", id="ping-1", command="ping")
    )

    assert output.events == [
        {
            "id": "ping-1",
            "event": "helper.pong",
            "payload": {"capabilities": ["ocr", "system-audio"]},
        }
    ]


@pytest.mark.asyncio
async def test_ocr_returns_only_bounded_extracted_text() -> None:
    helper, output, analyzer, _ = make_helper()
    image = b"small-png-payload"

    await helper.handle(
        HelperRequest(
            version="1.0",
            id="ocr-1",
            command="ocr.analyze",
            payload={
                "mimeType": "image/png",
                "imageBase64": base64.b64encode(image).decode("ascii"),
            },
        )
    )

    assert analyzer.images == [image]
    assert output.events[0] == {
        "id": "ocr-1",
        "event": "ocr.result",
        "payload": {
            "text": "What is Python?",
            "width": 1280,
            "height": 720,
            "blockCount": 1,
            "truncated": False,
        },
    }
    assert "imageBase64" not in output.events[0]["payload"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mime_type", "encoded"),
    [("image/gif", "YWJj"), ("image/png", "not-base64")],
)
async def test_ocr_rejects_invalid_payloads(mime_type: str, encoded: str) -> None:
    helper, output, analyzer, _ = make_helper()

    await helper.handle(
        HelperRequest(
            version="1.0",
            id="ocr-bad",
            command="ocr.analyze",
            payload={"mimeType": mime_type, "imageBase64": encoded},
        )
    )

    assert analyzer.images == []
    assert output.events[-1]["payload"] == {"code": "invalid_ocr_request"}


@pytest.mark.asyncio
async def test_ocr_dependency_errors_are_not_disclosed() -> None:
    helper, output, _, _ = make_helper(FakeAnalyzer(RuntimeError("secret path")))

    await helper.handle(
        HelperRequest(
            version="1.0",
            id="ocr-error",
            command="ocr.analyze",
            payload={"mimeType": "image/png", "imageBase64": "YQ=="},
        )
    )

    assert output.events[-1]["payload"] == {"code": "ocr_unavailable"}


@pytest.mark.asyncio
async def test_audio_chunks_are_split_at_the_protocol_limit() -> None:
    helper, output, _, audio = make_helper()
    await helper.handle(
        HelperRequest(version="1.0", id="audio-1", command="audio.start")
    )
    source = b"a" * (64 * 1024 + 7)
    await audio.chunks.put(source)

    for _ in range(20):
        if sum(event["event"] == "audio.chunk" for event in output.events) == 2:
            break
        await asyncio.sleep(0)

    chunks = [event for event in output.events if event["event"] == "audio.chunk"]
    assert [event["payload"]["byteLength"] for event in chunks] == [64 * 1024, 7]
    restored = b"".join(
        base64.b64decode(str(event["payload"]["audioBase64"])) for event in chunks
    )
    assert restored == source

    await helper.handle(
        HelperRequest(version="1.0", id="audio-stop", command="audio.stop")
    )
    assert output.events[-1]["event"] == "audio.stopped"
    assert audio.stopped == 1


@pytest.mark.asyncio
async def test_audio_start_failure_uses_safe_error_code() -> None:
    audio = FakeAudioCapture(SystemAudioCaptureError("system_audio_windows_only"))
    helper, output, _, _ = make_helper(audio=audio)

    await helper.handle(
        HelperRequest(version="1.0", id="audio-error", command="audio.start")
    )

    assert output.events[-1]["payload"] == {"code": "system_audio_windows_only"}


@pytest.mark.asyncio
async def test_invalid_json_is_rejected_without_ending_helper() -> None:
    helper, output, _, _ = make_helper()

    assert await helper.handle_bytes(b"not-json")

    assert output.events[-1] == {
        "id": None,
        "event": "helper.error",
        "payload": {"code": "invalid_helper_request"},
    }


@pytest.mark.asyncio
async def test_runner_emits_ready_and_stops_on_explicit_shutdown() -> None:
    helper, output, _, audio = make_helper()
    commands = (
        b"\n".join(
            json.dumps(command).encode("utf-8")
            for command in (
                {"version": "1.0", "id": "ping", "command": "ping", "payload": {}},
                {"version": "1.0", "id": "bye", "command": "shutdown", "payload": {}},
            )
        )
        + b"\n"
    )

    await run_helper(io.BytesIO(commands), output, helper)

    assert [event["event"] for event in output.events] == [
        "helper.ready",
        "helper.pong",
        "helper.stopped",
    ]
    assert audio.stopped == 1


@pytest.mark.asyncio
async def test_runner_cleans_up_when_parent_closes_stdin() -> None:
    helper, output, _, audio = make_helper()

    await run_helper(io.BytesIO(b""), output, helper)

    assert [event["event"] for event in output.events] == [
        "helper.ready",
        "helper.stopped",
    ]
    assert audio.stopped == 1
