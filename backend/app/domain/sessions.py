"""Session models independent from transports and LLM providers."""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class SessionAlreadyActiveError(Exception):
    """Raised when a client tries to start the same active session twice."""


class SessionStatus(StrEnum):
    """The lifecycle states visible to the session application service."""

    STREAMING = "streaming"
    CANCELLING = "cancelling"
    COMPLETED = "completed"


@dataclass
class ActiveSession:
    """Transient session state with a cooperative cancellation signal."""

    session_id: UUID
    status: SessionStatus = SessionStatus.STREAMING
    cancellation_requested: asyncio.Event = field(default_factory=asyncio.Event)
