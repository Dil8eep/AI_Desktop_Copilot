"""Session lifecycle and token streaming use cases."""

from collections.abc import AsyncIterator
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.llm import LlmRequest, LlmStreamError
from app.domain.ports import LlmStreamer, SessionRepository
from app.domain.protocol import EventEnvelope
from app.domain.sessions import SessionAlreadyActiveError


class StartSessionPayload(BaseModel):
    """Validated client payload for a new streaming request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str = Field(min_length=1, max_length=8_000)


class StopSessionPayload(BaseModel):
    """Validated client payload for a cancellation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SessionService:
    """Coordinates a session repository and a provider-neutral LLM stream."""

    def __init__(self, sessions: SessionRepository, llm_streamer: LlmStreamer) -> None:
        self._sessions = sessions
        self._llm_streamer = llm_streamer

    async def stream(
        self,
        event: EventEnvelope,
        screen_image: tuple[bytes, str] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        """Yield token events and one terminal event for a start command."""

        try:
            command = StartSessionPayload.model_validate(event.payload)
        except ValidationError:
            yield self._error(event, "invalid_session_start")
            return

        try:
            session = await self._sessions.create(event.session_id)
        except SessionAlreadyActiveError:
            yield self._error(event, "session_already_active")
            return

        reason = "completed"
        try:
            image_bytes, image_mime_type = screen_image or (None, None)
            request = LlmRequest(
                session_id=event.session_id,
                prompt=command.prompt,
                user_id=user_id,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
            )
            async for delta in self._llm_streamer.stream(
                request, session.cancellation_requested
            ):
                if session.cancellation_requested.is_set():
                    reason = "cancelled"
                    break
                yield EventEnvelope.create(
                    event="llm.token",
                    session_id=event.session_id,
                    request_id=event.request_id,
                    payload={"delta": delta.text},
                )
            if session.cancellation_requested.is_set():
                reason = "cancelled"
        except LlmStreamError as error:
            reason = "failed"
            code = str(error)
            safe_codes = {
                "llm_configuration_required",
                "provider_model_image_not_supported",
            }
            yield self._error(
                event, code if code in safe_codes else "llm_stream_failed"
            )
        finally:
            await self._sessions.remove(event.session_id)

        yield EventEnvelope.create(
            event="llm.completed",
            session_id=event.session_id,
            request_id=event.request_id,
            payload={"reason": reason},
        )

    async def cancel(self, event: EventEnvelope) -> EventEnvelope | None:
        """Request cancellation or return a typed error for an unknown session."""

        try:
            StopSessionPayload.model_validate(event.payload)
        except ValidationError:
            return self._error(event, "invalid_session_stop")

        cancelled = await self._sessions.request_cancellation(event.session_id)
        if not cancelled:
            return self._error(event, "session_not_found")
        return None

    async def cancel_session(self, session_id: UUID) -> None:
        """Cancel an active session during connection cleanup."""

        await self._sessions.request_cancellation(session_id)

    @staticmethod
    def _error(event: EventEnvelope, code: str) -> EventEnvelope:
        return EventEnvelope.create(
            event="protocol.error",
            session_id=event.session_id,
            request_id=event.request_id,
            payload={"code": code},
        )
