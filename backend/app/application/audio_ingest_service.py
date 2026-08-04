"""Application service for local voice segmentation and transcription."""

from app.domain.audio import SpeechTranscriptionError
from app.domain.ports import AudioSegmenter, SpeechTranscriber
from app.domain.protocol import EventEnvelope


class AudioIngestService:
    """Turn PCM chunks into local VAD segments and finalized transcripts."""

    def __init__(
        self, segmenter: AudioSegmenter, transcriber: SpeechTranscriber
    ) -> None:
        self._segmenter = segmenter
        self._transcriber = transcriber

    async def ingest(
        self, event: EventEnvelope, pcm_s16le: bytes, source: str = "microphone"
    ) -> tuple[EventEnvelope, ...]:
        """Process one validated PCM chunk without exposing provider details."""

        sample_rate_hz = event.payload.get("sampleRateHz")
        if not isinstance(sample_rate_hz, int):
            raise ValueError("audio_chunk_missing_sample_rate")
        segments = await self._segmenter.push_pcm(
            event.session_id, sample_rate_hz, pcm_s16le
        )
        responses: list[EventEnvelope] = []
        for segment in segments:
            try:
                transcript = await self._transcriber.transcribe(segment)
            except SpeechTranscriptionError as error:
                if error.code == "empty_transcript":
                    continue
                raise
            responses.append(
                EventEnvelope.create(
                    event="audio.segmented",
                    session_id=segment.session_id,
                    request_id=event.request_id,
                    payload={
                        "sampleRateHz": segment.sample_rate_hz,
                        "byteLength": len(segment.pcm_s16le),
                    },
                )
            )
            responses.append(
                EventEnvelope.create(
                    event="speech.final",
                    session_id=segment.session_id,
                    request_id=event.request_id,
                    payload={"text": transcript.text, "source": source},
                )
            )
        return tuple(responses)