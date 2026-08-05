"""Explicit screen capture must immediately start a solve-first response."""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.websocket import create_websocket_endpoint
from app.application.context_service import ContextService
from app.application.session_service import SessionService
from app.domain.llm import LlmDelta, LlmRequest
from app.domain.protocol import EventEnvelope
from app.infrastructure.auth_service import JwtService
from app.infrastructure.in_memory_session_repository import InMemorySessionRepository


class RecordingLlmStreamer:
    def __init__(self) -> None:
        self.requests: list[LlmRequest] = []

    async def stream(
        self, request: LlmRequest, cancellation_requested: asyncio.Event
    ) -> AsyncIterator[LlmDelta]:
        del cancellation_requested
        self.requests.append(request)
        yield LlmDelta(text="B. Queue — FIFO processes the earliest item first.")


class QuestionPerception:
    async def analyze_screen(
        self, event: EventEnvelope, image_bytes: bytes
    ) -> tuple[EventEnvelope, ...]:
        assert image_bytes == b"img"
        return (
            EventEnvelope.create(
                event="context.updated",
                session_id=event.session_id,
                request_id=event.request_id,
                payload={
                    "screenText": (
                        "Which data structure uses FIFO? "
                        "A. Stack B. Queue C. Tree D. Heap"
                    ),
                    "truncated": False,
                },
            ),
        )


class UnusedAudioIngestor:
    async def ingest(
        self,
        event: EventEnvelope,
        pcm_s16le: bytes,
        source: str = "microphone",
    ) -> tuple[EventEnvelope, ...]:
        del event, pcm_s16le, source
        return ()


class UnusedSystemAudioCapture:
    async def start(self) -> None:
        return None

    async def read_pcm16le(self) -> bytes:
        return b""

    async def stop(self) -> None:
        return None


def test_screen_capture_solves_even_when_speech_auto_response_is_disabled() -> None:
    streamer = RecordingLlmStreamer()
    application = FastAPI()
    user_id = str(uuid4())
    jwt_service = JwtService("screen-test-secret-that-is-over-32-bytes", 15)
    application.add_api_websocket_route(
        "/ws",
        create_websocket_endpoint(
            SessionService(InMemorySessionRepository(), streamer),
            QuestionPerception(),
            UnusedAudioIngestor(),
            "test-token",
            lambda: ContextService(1_000, 2_000),
            False,
            False,
            UnusedSystemAudioCapture,
            jwt_service,
        ),
    )
    session_id = str(uuid4())
    request_id = str(uuid4())

    with TestClient(application) as client:
        with client.websocket_connect(
            "/ws",
            headers={
                "x-copilot-token": "test-token",
                "authorization": f"Bearer {jwt_service.issue_access_token(user_id)}",
            },
        ) as websocket:
            assert websocket.receive_json()["event"] == "system.ready"
            websocket.send_json(
                {
                    "version": "1.0",
                    "event": "screen.capture",
                    "sessionId": session_id,
                    "requestId": request_id,
                    "timestamp": "2026-08-04T00:00:00Z",
                    "payload": {"mimeType": "image/png", "byteLength": 3},
                }
            )
            websocket.send_bytes(b"img")
            events: list[dict[str, object]] = []
            while not events or events[-1]["event"] != "llm.completed":
                events.append(websocket.receive_json())

    assert [event["event"] for event in events] == [
        "context.updated",
        "llm.token",
        "llm.completed",
    ]
    assert len(streamer.requests) == 1
    request = streamer.requests[0]
    assert "Multiple choice" in request.prompt
    assert "without waiting for another user message" in request.prompt
    assert request.user_id == user_id
    assert request.image_bytes == b"img"
    assert request.image_mime_type == "image/png"
