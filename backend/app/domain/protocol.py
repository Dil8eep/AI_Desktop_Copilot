"""Typed, provider-neutral WebSocket protocol primitives."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "1.0"

EventName = Literal[
    "system.ready",
    "session.start",
    "session.stop",
    "audio.chunk",
    "audio.segmented",
    "system_audio.start",
    "system_audio.stop",
    "system_audio.started",
    "system_audio.stopped",
    "screen.capture",
    "screen.text",
    "settings.update",
    "speech.partial",
    "speech.final",
    "vision.updated",
    "context.updated",
    "llm.token",
    "llm.completed",
    "overlay.update",
    "protocol.error",
]


class EventEnvelope(BaseModel):
    """A versioned message exchanged over the desktop-backend WebSocket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["1.0"] = "1.0"
    event: EventName
    session_id: UUID = Field(alias="sessionId")
    request_id: UUID = Field(alias="requestId")
    timestamp: datetime
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        event: EventName,
        session_id: UUID,
        payload: dict[str, Any],
        request_id: UUID | None = None,
    ) -> "EventEnvelope":
        """Build an outbound envelope with clock and request defaults."""

        return cls(
            event=event,
            sessionId=session_id,
            requestId=request_id or uuid4(),
            timestamp=datetime.now(UTC),
            payload=payload,
        )
