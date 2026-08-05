"""Ports that keep application behavior independent from FastAPI and providers."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from app.domain.audio import Transcript, VoiceSegment
from app.domain.llm import LlmDelta, LlmRequest
from app.domain.protocol import EventEnvelope
from app.domain.sessions import ActiveSession
from app.domain.vision import ScreenAnalysis


class LlmStreamer(Protocol):
    """Streams provider-neutral text deltas for a single request."""

    def stream(
        self, request: LlmRequest, cancellation_requested: asyncio.Event
    ) -> AsyncIterator[LlmDelta]:
        """Yield deltas until completion, cancellation, or a typed failure."""


class SessionRepository(Protocol):
    """Manages only active, transient session state."""

    async def create(self, session_id: UUID) -> ActiveSession:
        """Create an active session."""

    async def request_cancellation(self, session_id: UUID) -> bool:
        """Signal an active session."""

    async def remove(self, session_id: UUID) -> None:
        """Discard an ended session."""


class ResumeProfileParser(Protocol):
    """Parses extracted resume text using an authenticated user's LLM."""

    async def parse(self, user_id: str, resume_text: str) -> dict[str, object]:
        """Return a flexible profile grounded only in the supplied resume."""


class ScreenAnalyzer(Protocol):
    """Extracts text blocks from a user-authorized screen capture."""

    async def analyze(self, image_bytes: bytes) -> ScreenAnalysis:
        """Return OCR text, confidence, and polygons for one capture."""


class AudioSegmenter(Protocol):
    """Separates PCM microphone chunks into local speech utterances."""

    async def push_pcm(
        self, session_id: UUID, sample_rate_hz: int, pcm_s16le: bytes
    ) -> tuple[VoiceSegment, ...]:
        """Return every utterance that ends in the given chunk."""


class SpeechTranscriber(Protocol):
    """Transcribes a completed speech segment with a backend provider."""

    async def transcribe(self, segment: VoiceSegment) -> Transcript:
        """Return the final transcript for one voiced utterance."""


class ConversationContext(Protocol):
    """Builds bounded, per-connection context for automatic responses."""

    def update_screen(self, screen_text: str) -> None:
        """Store the most recent user-authorized OCR text."""

    def update_screen_image(self, image_bytes: bytes, mime_type: str) -> None:
        """Store one bounded user-authorized screen image for vision analysis."""

    def get_screen_image(self) -> tuple[bytes, str] | None:
        """Return the latest authorized screen image, if available."""

    def record_transcript(self, text: str, source: str) -> None:
        """Store one finalized transcript with a source label."""

    def update_candidate_profile(self, profile: dict[str, object]) -> None:
        """Keep one user-authorized profile for explicit profile-aware requests."""

    def build_prompt(self) -> str:
        """Return a prompt focused on the latest finalized transcript."""

    def build_screen_prompt(self) -> str:
        """Return a prompt focused on the latest screen OCR context."""

    def build_user_prompt(
        self, instruction: str, include_candidate_profile: bool = False
    ) -> str:
        """Return a grounded prompt for an explicit user request."""


class ScreenPerception(Protocol):
    """Analyzes user-authorized screen bytes into protocol events."""

    async def analyze_screen(
        self, event: EventEnvelope, image_bytes: bytes
    ) -> tuple[EventEnvelope, ...]:
        """Return vision and bounded-context updates."""


class AudioIngestor(Protocol):
    """Turns validated audio bytes into transcript protocol events."""

    async def ingest(
        self,
        event: EventEnvelope,
        pcm_s16le: bytes,
        source: str = "microphone",
    ) -> tuple[EventEnvelope, ...]:
        """Return VAD and finalized-transcript updates."""


class SystemAudioCapture(Protocol):
    """Captures consented operating-system speaker output as PCM audio."""

    async def start(self) -> None:
        """Begin speaker-output capture."""

    async def read_pcm16le(self) -> bytes:
        """Return the next mono 16 kHz PCM chunk."""

    async def stop(self) -> None:
        """Release capture resources."""
