"""Provider-neutral audio values used before transcription."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class VoiceSegment:
    """A completed utterance selected by local voice activity detection."""

    session_id: UUID
    sample_rate_hz: int
    pcm_s16le: bytes


@dataclass(frozen=True)
class Transcript:
    """One finalized speech-to-text result."""

    text: str


class SpeechTranscriptionError(Exception):
    """A sanitized transcription failure safe for the desktop protocol."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code