"""Groq Whisper adapter for finalized local PCM segments."""

import asyncio
import wave
from io import BytesIO

from groq import AsyncGroq

from app.domain.audio import SpeechTranscriptionError, Transcript, VoiceSegment
from app.infrastructure.provider_client_factory import ProviderClientFactory
from app.infrastructure.provider_credential_resolver import CredentialResolutionError


class GroqWhisperTranscriber:
    """Resolve one credential for each transcription operation."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float,
        max_attempts: int = 2,
        client_factory: ProviderClientFactory | None = None,
    ) -> None:
        self._client = AsyncGroq(api_key=api_key) if api_key is not None else None
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._client_factory = client_factory

    async def transcribe(self, segment: VoiceSegment) -> Transcript:
        """Return the final text from Groq without writing user audio to disk."""
        try:
            client, model = await self._client_for_transcription()
        except CredentialResolutionError as error:
            raise SpeechTranscriptionError("speech_provider_not_configured") from error
        audio_wav = await asyncio.to_thread(self._as_wav, segment)
        for attempt in range(self._max_attempts):
            try:
                response = await asyncio.wait_for(
                    client.audio.transcriptions.create(
                        file=("speech.wav", audio_wav),
                        model=model,
                        temperature=0,
                        response_format="verbose_json",
                    ),
                    timeout=self._timeout_seconds,
                )
                text = getattr(response, "text", "").strip()
                if text:
                    return Transcript(text=text)
                raise SpeechTranscriptionError("empty_transcript")
            except SpeechTranscriptionError:
                raise
            except Exception as error:
                if attempt + 1 == self._max_attempts:
                    raise SpeechTranscriptionError(
                        "speech_transcription_failed"
                    ) from error
                await asyncio.sleep(0.2 * (attempt + 1))
        raise SpeechTranscriptionError("speech_transcription_failed")

    async def _client_for_transcription(self) -> tuple[AsyncGroq, str]:
        if self._client_factory is not None:
            client, resolved = await self._client_factory.groq()
            return client, resolved.model or self._model
        if self._client is None:
            raise CredentialResolutionError("provider_not_configured")
        return self._client, self._model

    @staticmethod
    def _as_wav(segment: VoiceSegment) -> bytes:
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(segment.sample_rate_hz)
            wav.writeframes(segment.pcm_s16le)
        return output.getvalue()


class UnavailableSpeechTranscriber:
    """Explicitly reports missing local speech-provider configuration."""

    async def transcribe(self, segment: VoiceSegment) -> Transcript:
        del segment
        raise SpeechTranscriptionError("speech_provider_not_configured")
