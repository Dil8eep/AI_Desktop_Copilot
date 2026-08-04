"""In-memory V1 session repository with no durable history."""

import asyncio
from uuid import UUID

from app.domain.sessions import ActiveSession, SessionAlreadyActiveError, SessionStatus


class InMemorySessionRepository:
    """Stores only active sessions and removes them on stream completion."""

    def __init__(self) -> None:
        self._sessions: dict[UUID, ActiveSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, session_id: UUID) -> ActiveSession:
        """Create an active session or reject an already-active identifier."""

        async with self._lock:
            if session_id in self._sessions:
                raise SessionAlreadyActiveError(str(session_id))
            session = ActiveSession(session_id=session_id)
            self._sessions[session_id] = session
            return session

    async def request_cancellation(self, session_id: UUID) -> bool:
        """Signal cooperative cancellation and report whether a session existed."""

        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.status = SessionStatus.CANCELLING
            session.cancellation_requested.set()
            return True

    async def remove(self, session_id: UUID) -> None:
        """Remove completed transient state."""

        async with self._lock:
            self._sessions.pop(session_id, None)
