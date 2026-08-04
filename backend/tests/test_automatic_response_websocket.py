from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import CaptureFixture

from app.api.websocket import create_websocket_endpoint
from app.application.context_service import ContextService
from app.application.session_service import SessionService
from app.domain.protocol import EventEnvelope
from app.infrastructure.in_memory_session_repository import InMemorySessionRepository
from app.infrastructure.mock_llm_streamer import MockLlmStreamer


class FakeAudioIngestService:
    async def ingest(
        self,
        event: EventEnvelope,
        pcm_s16le: bytes,
        source: str = "microphone",
    ) -> tuple[EventEnvelope, ...]:
        del source
        assert pcm_s16le == b"pcm"
        return (
            EventEnvelope.create(
                event="speech.final",
                session_id=event.session_id,
                request_id=event.request_id,
                payload={"text": "What is the deadline?", "source": "microphone"},
            ),
        )


class FakePerceptionService:
    async def analyze_screen(
        self, event: EventEnvelope, image_bytes: bytes
    ) -> tuple[EventEnvelope, ...]:
        del event, image_bytes
        return ()


class FakeSystemAudioCapture:
    async def start(self) -> None:
        return None

    async def read_pcm16le(self) -> bytes:
        return b""

    async def stop(self) -> None:
        return None


def _event(session_id: str) -> dict[str, object]:
    return {
        "version": "1.0",
        "event": "audio.chunk",
        "sessionId": session_id,
        "requestId": str(uuid4()),
        "timestamp": "2026-07-29T00:00:00Z",
        "payload": {
            "mimeType": "audio/pcm;codec=s16le",
            "sampleRateHz": 16_000,
            "byteLength": 3,
        },
    }


def test_final_transcript_starts_an_automatic_overlay_stream(
    capsys: CaptureFixture[str],
) -> None:
    application = FastAPI()
    sessions = SessionService(
        InMemorySessionRepository(), MockLlmStreamer(token_delay_seconds=0.001)
    )
    application.add_api_websocket_route(
        "/ws",
        create_websocket_endpoint(
            sessions,
            FakePerceptionService(),
            FakeAudioIngestService(),
            "test-token",
            lambda: ContextService(1_000, 1_000),
            True,
            True,
            FakeSystemAudioCapture,
        ),
    )

    with TestClient(application) as client:
        with client.websocket_connect(
            "/ws", headers={"x-copilot-token": "test-token"}
        ) as websocket:
            assert websocket.receive_json()["event"] == "system.ready"
            websocket.send_json(_event(str(uuid4())))
            websocket.send_bytes(b"pcm")
            events: list[dict[str, object]] = []
            while not events or events[-1]["event"] != "llm.completed":
                events.append(websocket.receive_json())

    assert events[0]["event"] == "speech.final"
    assert [event["event"] for event in events].count("llm.token") == 4
    assert events[-1]["payload"] == {"reason": "completed"}
    output = capsys.readouterr().out
    assert "Speaker: What is the deadline?" in output
    assert "AI: Mock streaming response." in output