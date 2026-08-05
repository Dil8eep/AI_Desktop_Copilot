"""Provider-neutral streaming LLM request and delta types."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class LlmRequest:
    """The small request contract required by every streaming LLM adapter."""

    session_id: UUID
    prompt: str
    user_id: str | None = None
    image_bytes: bytes | None = None
    image_mime_type: str | None = None


@dataclass(frozen=True)
class LlmDelta:
    """One append-only text delta from a model stream."""

    text: str


class LlmStreamError(Exception):
    """A sanitized stream failure safe to describe through the protocol."""
