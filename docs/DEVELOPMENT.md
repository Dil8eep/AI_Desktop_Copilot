# Development Guide

## Verification commands

```powershell
npm run lint:desktop
npm run test:desktop
npm run build:desktop
cd backend
.venv\Scripts\python.exe -m ruff check app tests
.venv\Scripts\python.exe -m mypy app tests
.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

## Context pipeline

Electron obtains microphone and display permission only after the user presses
the corresponding Control Center button. The renderer sends 16 kHz mono PCM
and JPEG screen captures through secure IPC to the Electron main process, then
over the authenticated loopback WebSocket. It never holds provider credentials.

Silero VAD runs locally in the backend. It processes PCM in its required
512-sample frames and emits an `audio.segmented` event only when an utterance
ends (or reaches the 25-second safety limit). Groq Whisper transcription is a
Milestone 6 adapter; no audio is sent to Groq in Milestone 5.

## OCR model decision

PaddleOCR uses the PP-OCRv6 safetensors pair selected for this project:
`PP-OCRv6_medium_det` detects text regions and
`PP-OCRv6_medium_rec` recognizes their text. The pair requires PaddleOCR's
Transformers engine, `transformers`, `torch`, and `torchvision`.

On the first OCR request PaddleOCR downloads the public model artifacts to the
user-local PaddleX cache (normally `.paddlex\official_models`), not this Git
workspace. Inference executes with `asyncio.to_thread`, so FastAPI's event loop
continues accepting WebSocket frames. The screen analyzer returns text,
confidence, and polygons; screen text is capped to 12,000 characters before it
is emitted as `context.updated`.

## Safety boundaries

Do not expose Electron or Node APIs to the renderer. Do not put provider keys
in desktop code or source control. Keep provider adapters at the composition
root and inject their ports. Rotate any API key that was ever pasted into a
chat or terminal output.