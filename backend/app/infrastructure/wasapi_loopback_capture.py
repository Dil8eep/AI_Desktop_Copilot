"""Windows WASAPI loopback capture for consented system-audio assistance."""

import asyncio
import platform
from importlib import import_module
from typing import Any

import numpy as np


class SystemAudioCaptureError(Exception):
    """Safe failure code for unavailable system-audio capture."""


class WasapiLoopbackCapture:
    """Capture the default Windows speaker output as 16 kHz mono PCM."""

    _TARGET_SAMPLE_RATE_HZ = 16_000
    _FRAMES_PER_BUFFER = 2_048

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[bytes] | None = None
        self._audio: Any | None = None
        self._stream: Any | None = None
        self._channels = 0
        self._sample_rate_hz = 0
        self._continue_flag = 0

    async def start(self) -> None:
        """Open the default WASAPI loopback endpoint without blocking asyncio."""

        if self._stream is not None:
            return
        if platform.system() != "Windows":
            raise SystemAudioCaptureError("system_audio_windows_only")
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=32)
        try:
            await asyncio.to_thread(self._open_stream)
        except Exception as error:
            await self.stop()
            raise SystemAudioCaptureError("system_audio_unavailable") from error

    async def read_pcm16le(self) -> bytes:
        """Return the next resampled PCM chunk from the selected speaker output."""

        queue = self._queue
        if queue is None:
            raise SystemAudioCaptureError("system_audio_not_started")
        raw = await queue.get()
        return await asyncio.to_thread(self._to_target_pcm, raw)

    async def stop(self) -> None:
        """Release the native stream and device without blocking the event loop."""

        stream = self._stream
        audio = self._audio
        self._stream = None
        self._audio = None
        self._queue = None
        self._loop = None
        if stream is None and audio is None:
            return
        await asyncio.to_thread(self._close_stream, stream, audio)

    def _open_stream(self) -> None:
        pyaudio: Any = import_module("pyaudiowpatch")

        audio = pyaudio.PyAudio()
        wasapi = audio.get_host_api_info_by_type(pyaudio.paWASAPI)
        speakers = audio.get_device_info_by_index(wasapi["defaultOutputDevice"])
        loopback = speakers if speakers["isLoopbackDevice"] else next(
            (
                device
                for device in audio.get_loopback_device_info_generator()
                if speakers["name"] in device["name"]
            ),
            None,
        )
        if loopback is None:
            audio.terminate()
            raise SystemAudioCaptureError("system_audio_loopback_not_found")
        self._channels = int(loopback["maxInputChannels"])
        self._sample_rate_hz = int(loopback["defaultSampleRate"])
        if self._channels < 1 or self._sample_rate_hz < 1:
            audio.terminate()
            raise SystemAudioCaptureError("system_audio_invalid_device_format")
        self._continue_flag = pyaudio.paContinue
        self._audio = audio
        self._stream = audio.open(
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._sample_rate_hz,
            frames_per_buffer=self._FRAMES_PER_BUFFER,
            input=True,
            input_device_index=loopback["index"],
            stream_callback=self._on_audio,
        )

    def _on_audio(
        self, in_data: bytes, frame_count: int, time_info: Any, status: int
    ) -> tuple[bytes, int]:
        del frame_count, time_info, status
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._enqueue, bytes(in_data))
        return in_data, self._continue_flag

    def _enqueue(self, data: bytes) -> None:
        queue = self._queue
        if queue is None:
            return
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(data)

    def _to_target_pcm(self, raw: bytes) -> bytes:
        samples = np.frombuffer(raw, dtype="<i2")
        complete_samples = len(samples) - (len(samples) % self._channels)
        if complete_samples == 0:
            return b""
        frames = samples[:complete_samples].reshape(-1, self._channels)
        mono = frames.astype(np.float32).mean(axis=1)
        if self._sample_rate_hz != self._TARGET_SAMPLE_RATE_HZ:
            target_length = max(
                1,
                round(len(mono) * self._TARGET_SAMPLE_RATE_HZ / self._sample_rate_hz),
            )
            source_positions = np.arange(len(mono), dtype=np.float32)
            target_positions = np.linspace(
                0, len(mono) - 1, target_length, dtype=np.float32
            )
            mono = np.interp(target_positions, source_positions, mono)
        return bytes(np.clip(mono, -32768, 32767).astype("<i2").tobytes())

    @staticmethod
    def _close_stream(stream: Any | None, audio: Any | None) -> None:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        if audio is not None:
            audio.terminate()