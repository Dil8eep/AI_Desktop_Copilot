# Milestone F3: Electron Local Capture Integration

## Status

Implemented and verified locally. Installer packaging remains Milestone F4.

## Implemented path

### Analyze Screen

1. The renderer captures a user-selected display after the explicit Analyze Screen action.
2. Electron main sends the JPEG or PNG bytes through private standard-input IPC to the F2 helper.
3. LiteParse extracts text locally.
4. Electron validates the helper response and sends only bounded `screen.text` to the authenticated backend WebSocket.
5. The backend uses the signed-in user's selected LLM and resume context to generate the streamed solution.

The production Electron path no longer exposes a backend `screen.capture` sender.

### System audio

1. The explicit listening control asks Electron main to start the F2 helper's WASAPI capture.
2. The helper returns mono 16 kHz PCM chunks of at most 64 KiB.
3. Electron validates each helper event and forwards the bytes as `audio.chunk` with source `system-audio`.
4. Render performs VAD and administrator-managed Groq transcription.
5. Meeting and Mock Interview behavior remains controlled by the existing backend conversation mode.

Electron no longer sends `system_audio.start` or `system_audio.stop` to the hosted backend.

## Lifecycle and security

- Electron lazily starts one helper and waits for `helper.ready`.
- Requests are correlated by random IDs and have bounded timeouts.
- Malformed, oversized, or unexpected helper output terminates the helper safely.
- Only a small Windows/process environment allowlist is inherited; provider keys, database URLs, JWT secrets, and user access tokens are excluded.
- Renderer code receives narrow promise-based preload methods, never child-process access.
- Electron waits for graceful helper shutdown during application quit and force-terminates it after a short timeout.
- Development resolves `backend/.venv/Scripts/python.exe -m app.local_helper`.
- Packaged installations resolve `resources/local-helper/copilot-local-helper.exe`; producing that executable is F4.

## Verification

- Local helper client contract tests cover OCR, PCM forwarding, payload rejection, and shutdown.
- Launch configuration tests cover source/package paths and credential stripping.
- The compiled Electron client successfully starts and shuts down the real Python helper.
- Desktop typecheck, ESLint, Prettier, Vitest, and production build gates pass.

Real speaker capture is intentionally exercised only through the application's explicit user control; automated tests do not activate the user's audio device.