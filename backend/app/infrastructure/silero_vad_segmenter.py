"""Local, lazy Silero VAD adapter for PCM16 microphone chunks."""

import asyncio
from collections import defaultdict
from uuid import UUID

import numpy as np

from app.domain.audio import VoiceSegment


class SileroVadSegmenter:
    """Create bounded utterances using a locally loaded Silero VAD model.

    The adapter accepts mono signed-16-bit PCM at 16 kHz. It keeps only the
    active utterance for each transient WebSocket session and never performs a
    network request while processing audio.
    """

    _SAMPLE_RATE_HZ = 16_000
    _FRAME_SAMPLES = 512
    _FRAME_BYTES = _FRAME_SAMPLES * 2
    _MAX_SEGMENT_BYTES = _SAMPLE_RATE_HZ * 2 * 25

    def __init__(self) -> None:
        self._detectors: dict[UUID, object] = {}
        self._buffers: dict[UUID, bytearray] = defaultdict(bytearray)
        self._remainders: dict[UUID, bytearray] = defaultdict(bytearray)
        self._active: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def push_pcm(
        self, session_id: UUID, sample_rate_hz: int, pcm_s16le: bytes
    ) -> tuple[VoiceSegment, ...]:
        """Return each utterance that ends in this chunk."""

        if sample_rate_hz != self._SAMPLE_RATE_HZ:
            raise ValueError("unsupported_audio_sample_rate")
        if not pcm_s16le or len(pcm_s16le) % 2:
            raise ValueError("invalid_pcm_s16le")
        async with self._lock:
            return await asyncio.to_thread(self._push_sync, session_id, pcm_s16le)

    def _push_sync(
        self, session_id: UUID, pcm_s16le: bytes
    ) -> tuple[VoiceSegment, ...]:
        import torch
        from silero_vad import (  # type: ignore[import-untyped]
            VADIterator,
            load_silero_vad,
        )

        detector = self._detectors.get(session_id)
        if detector is None:
            model = load_silero_vad(onnx=True)
            detector = VADIterator(model, sampling_rate=self._SAMPLE_RATE_HZ)
            self._detectors[session_id] = detector

        remainder = self._remainders[session_id]
        remainder.extend(pcm_s16le)
        completed: list[VoiceSegment] = []
        while len(remainder) >= self._FRAME_BYTES:
            frame = bytes(remainder[: self._FRAME_BYTES])
            del remainder[: self._FRAME_BYTES]
            samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
            audio = torch.from_numpy(samples / 32768.0)
            result = detector(audio, return_seconds=False)  # type: ignore[operator]
            is_mapping = isinstance(result, dict)
            if is_mapping and "start" in result:
                self._active.add(session_id)
                self._buffers[session_id].clear()
            if session_id in self._active:
                self._buffers[session_id].extend(frame)
            ended = is_mapping and "end" in result
            forced = len(self._buffers[session_id]) >= self._MAX_SEGMENT_BYTES
            if session_id in self._active and (ended or forced):
                completed.append(
                    VoiceSegment(
                        session_id=session_id,
                        sample_rate_hz=self._SAMPLE_RATE_HZ,
                        pcm_s16le=bytes(self._buffers[session_id]),
                    )
                )
                self._buffers[session_id].clear()
                self._active.discard(session_id)
        return tuple(completed)