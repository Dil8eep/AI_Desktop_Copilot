from uuid import UUID, uuid4

import pytest

from app.application.audio_ingest_service import AudioIngestService
from app.domain.audio import SpeechTranscriptionError, Transcript, VoiceSegment
from app.domain.protocol import EventEnvelope


class FakeAudioSegmenter:
    async def push_pcm(
        self, session_id: UUID, sample_rate_hz: int, pcm_s16le: bytes
    ) -> tuple[VoiceSegment, ...]:
        assert sample_rate_hz == 16_000
        assert pcm_s16le == b"pcm"
        return (
            VoiceSegment(
                session_id=session_id,
                sample_rate_hz=sample_rate_hz,
                pcm_s16le=pcm_s16le,
            ),
        )


class FakeSpeechTranscriber:
    async def transcribe(self, segment: VoiceSegment) -> Transcript:
        assert segment.pcm_s16le == b"pcm"
        return Transcript(text="Hello from Groq")


@pytest.mark.asyncio
async def test_audio_ingest_emits_local_metadata_then_final_transcript() -> None:
    service = AudioIngestService(FakeAudioSegmenter(), FakeSpeechTranscriber())
    request = EventEnvelope.create(
        event="audio.chunk",
        session_id=uuid4(),
        payload={"sampleRateHz": 16_000, "byteLength": 3},
    )

    events = await service.ingest(request, b"pcm")

    assert events[0].event == "audio.segmented"
    assert events[0].payload == {"sampleRateHz": 16_000, "byteLength": 3}
    assert events[1].event == "speech.final"
    assert events[1].payload == {"text": "Hello from Groq", "source": "microphone"}

class EmptySpeechTranscriber:
    async def transcribe(self, segment: VoiceSegment) -> Transcript:
        del segment
        raise SpeechTranscriptionError("empty_transcript")


@pytest.mark.asyncio
async def test_audio_ingest_ignores_empty_provider_transcripts() -> None:
    service = AudioIngestService(FakeAudioSegmenter(), EmptySpeechTranscriber())
    request = EventEnvelope.create(
        event="audio.chunk",
        session_id=uuid4(),
        payload={"sampleRateHz": 16_000, "byteLength": 3},
    )

    events = await service.ingest(request, b"pcm", source="system-audio")

    assert events == ()