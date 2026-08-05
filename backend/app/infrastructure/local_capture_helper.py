"""Private JSON-lines IPC helper for local OCR and Windows audio capture."""

import asyncio
import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any, BinaryIO, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.ports import ScreenAnalyzer, SystemAudioCapture
from app.infrastructure.wasapi_loopback_capture import SystemAudioCaptureError

_HELPER_VERSION = "1.0"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_ENCODED_IMAGE_CHARACTERS = ((_MAX_IMAGE_BYTES + 2) // 3) * 4
_MAX_REQUEST_BYTES = _MAX_ENCODED_IMAGE_CHARACTERS + 16_384
_MAX_SCREEN_TEXT_CHARACTERS = 12_000
_MAX_AUDIO_CHUNK_BYTES = 64 * 1024
_IMAGE_MIME_TYPES = {"image/jpeg", "image/png"}

HelperCommand = Literal["ping", "ocr.analyze", "audio.start", "audio.stop", "shutdown"]


class HelperRequest(BaseModel):
    """One bounded command sent only by the parent Electron process."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"]
    id: str = Field(min_length=1, max_length=128)
    command: HelperCommand
    payload: dict[str, Any] = Field(default_factory=dict)


class HelperOutput(Protocol):
    """Serialize helper events to a parent-owned private channel."""

    async def emit(
        self, request_id: str | None, event: str, payload: Mapping[str, object]
    ) -> None: ...


class JsonLineOutput:
    """Concurrency-safe JSON-lines writer with no diagnostic side channel."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = asyncio.Lock()

    async def emit(
        self, request_id: str | None, event: str, payload: Mapping[str, object]
    ) -> None:
        message = {
            "version": _HELPER_VERSION,
            "id": request_id,
            "event": event,
            "payload": dict(payload),
        }
        encoded = (
            json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        async with self._lock:
            await asyncio.to_thread(self._write, encoded)

    def _write(self, encoded: bytes) -> None:
        self._stream.write(encoded)
        self._stream.flush()


class LocalCaptureHelper:
    """Own explicit local OCR and WASAPI operations for one Electron parent."""

    def __init__(
        self,
        analyzer: ScreenAnalyzer,
        audio_capture: SystemAudioCapture,
        output: HelperOutput,
    ) -> None:
        self._analyzer = analyzer
        self._audio_capture = audio_capture
        self._output = output
        self._audio_task: asyncio.Task[None] | None = None
        self._audio_capture_id: str | None = None

    async def handle(self, request: HelperRequest) -> bool:
        """Handle one validated command; return false only for shutdown."""

        if request.command == "ping":
            await self._output.emit(
                request.id,
                "helper.pong",
                {"capabilities": ["ocr", "system-audio"]},
            )
            return True
        if request.command == "ocr.analyze":
            await self._analyze(request)
            return True
        if request.command == "audio.start":
            await self._start_audio(request.id)
            return True
        if request.command == "audio.stop":
            await self._stop_audio(request.id)
            return True
        await self.shutdown(request.id)
        return False

    async def handle_bytes(self, raw_request: bytes) -> bool:
        """Validate one JSON line without exposing parser or dependency errors."""

        request_id: str | None = None
        try:
            if len(raw_request) > _MAX_REQUEST_BYTES:
                raise ValueError("helper_request_too_large")
            decoded = json.loads(raw_request)
            if isinstance(decoded, dict) and isinstance(decoded.get("id"), str):
                request_id = decoded["id"][:128]
            request = HelperRequest.model_validate(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
            await self._error(request_id, "invalid_helper_request")
            return True
        return await self.handle(request)

    async def shutdown(self, request_id: str | None = None) -> None:
        """Stop native capture before the parent process exits."""

        task = self._audio_task
        self._audio_task = None
        self._audio_capture_id = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._audio_capture.stop()
        await self._output.emit(request_id, "helper.stopped", {})

    async def _analyze(self, request: HelperRequest) -> None:
        mime_type = request.payload.get("mimeType")
        encoded_image = request.payload.get("imageBase64")
        if (
            mime_type not in _IMAGE_MIME_TYPES
            or not isinstance(encoded_image, str)
            or len(encoded_image) > _MAX_ENCODED_IMAGE_CHARACTERS
        ):
            await self._error(request.id, "invalid_ocr_request")
            return
        try:
            image_bytes = base64.b64decode(encoded_image, validate=True)
        except (binascii.Error, ValueError):
            await self._error(request.id, "invalid_ocr_request")
            return
        if not image_bytes or len(image_bytes) > _MAX_IMAGE_BYTES:
            await self._error(request.id, "invalid_ocr_request")
            return
        try:
            analysis = await self._analyzer.analyze(image_bytes)
        except Exception:
            await self._error(request.id, "ocr_unavailable")
            return
        full_text = "\n".join(
            block.text.strip() for block in analysis.blocks if block.text.strip()
        )
        screen_text = full_text[:_MAX_SCREEN_TEXT_CHARACTERS]
        await self._output.emit(
            request.id,
            "ocr.result",
            {
                "text": screen_text,
                "width": analysis.width,
                "height": analysis.height,
                "blockCount": len(analysis.blocks),
                "truncated": len(full_text) > len(screen_text),
            },
        )

    async def _start_audio(self, request_id: str) -> None:
        if self._audio_task is not None and not self._audio_task.done():
            await self._error(request_id, "system_audio_already_active")
            return
        try:
            await self._audio_capture.start()
        except SystemAudioCaptureError as error:
            await self._error(request_id, str(error))
            return
        except Exception:
            await self._error(request_id, "system_audio_unavailable")
            return
        self._audio_capture_id = request_id
        await self._output.emit(
            request_id,
            "audio.started",
            {"source": "system-audio", "sampleRateHz": 16_000},
        )
        self._audio_task = asyncio.create_task(
            self._stream_audio(request_id), name="local-helper-system-audio"
        )

    async def _stop_audio(self, request_id: str) -> None:
        task = self._audio_task
        if task is None or task.done():
            await self._error(request_id, "system_audio_not_active")
            return
        self._audio_task = None
        self._audio_capture_id = None
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await self._audio_capture.stop()
        await self._output.emit(request_id, "audio.stopped", {"source": "system-audio"})

    async def _stream_audio(self, capture_id: str) -> None:
        try:
            while True:
                pcm = await self._audio_capture.read_pcm16le()
                for offset in range(0, len(pcm), _MAX_AUDIO_CHUNK_BYTES):
                    chunk = pcm[offset : offset + _MAX_AUDIO_CHUNK_BYTES]
                    if not chunk:
                        continue
                    await self._output.emit(
                        capture_id,
                        "audio.chunk",
                        {
                            "source": "system-audio",
                            "sampleRateHz": 16_000,
                            "mimeType": "audio/pcm;codec=s16le",
                            "byteLength": len(chunk),
                            "audioBase64": base64.b64encode(chunk).decode("ascii"),
                        },
                    )
        except asyncio.CancelledError:
            raise
        except SystemAudioCaptureError as error:
            await self._error(capture_id, str(error))
        except Exception:
            await self._error(capture_id, "system_audio_unavailable")
        finally:
            if self._audio_capture_id == capture_id:
                self._audio_capture_id = None
                self._audio_task = None
                await self._audio_capture.stop()
                await self._output.emit(
                    capture_id, "audio.stopped", {"source": "system-audio"}
                )

    async def _error(self, request_id: str | None, code: str) -> None:
        await self._output.emit(request_id, "helper.error", {"code": code})


async def run_helper(
    input_stream: BinaryIO,
    output: HelperOutput,
    helper: LocalCaptureHelper,
) -> None:
    """Read bounded commands until parent EOF or explicit shutdown."""

    await output.emit(None, "helper.ready", {"protocolVersion": _HELPER_VERSION})
    stopped_explicitly = False
    try:
        while True:
            raw_request = await asyncio.to_thread(
                input_stream.readline, _MAX_REQUEST_BYTES + 1
            )
            if not raw_request:
                return
            if not await helper.handle_bytes(raw_request):
                stopped_explicitly = True
                return
    finally:
        if not stopped_explicitly:
            await helper.shutdown()
