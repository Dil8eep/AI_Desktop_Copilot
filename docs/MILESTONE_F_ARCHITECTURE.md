# Milestone F Architecture: Windows Installer and Production Desktop

## Status

Architecture gate for review before runtime and packaging implementation.

## Goal

Produce an installable Windows desktop client that preserves the existing Dashboard and overlay while securely using the hosted Render backend and Neon database.

## Current gaps confirmed in the checkout

1. `electron-builder` is installed but there is no NSIS packaging configuration, application icon, release script, or packaged production endpoint.
2. The desktop currently asks the WebSocket backend to start WASAPI capture. This works with a Windows-local backend but cannot work on Render Linux.
3. Screen images are currently sent to the backend for LiteParse processing. This contradicts the desired local-OCR privacy boundary.
4. Production WebSockets require one shared `COPILOT_LOCAL_AUTH_TOKEN`. Embedding that secret in a distributed installer would expose it to every installation.
5. The production endpoint is supplied only through shell environment variables; a normal installed application needs a safe packaged default and a controlled override.
6. There is no code-signing, updater, first-run installation identity, or release artifact verification yet.

## Target architecture

```text
Windows installer
|-- Electron Dashboard and transparent overlay
|-- Local capture helper
|   |-- Windows WASAPI loopback capture
|   |-- LiteParse OCR
|   `-- Private local IPC controlled by Electron
`-- TLS connection to Render
    |-- REST authentication and resume profiles
    |-- JWT-authenticated WebSocket
    |-- Per-user encrypted LLM configuration
    |-- Groq STT using the administrator-managed key
    `-- Neon PostgreSQL persistence
```

## Security decisions

### Production WebSocket authentication

- Production desktop connections authenticate with the user's short-lived JWT over WSS.
- `X-Copilot-Token` remains a development/local-backend defense only.
- A shared production secret will not be embedded in the installer.
- Expired JWTs disconnect the socket and return the Dashboard to sign-in.
- Per-installation device registration can be added later if device revocation is required; it is not replaced with a recoverable shared secret.

### Local helper boundary

- Electron owns helper startup and shutdown.
- The helper accepts commands only from the parent Electron process through private local IPC.
- It does not listen on a public network interface.
- It never receives LLM, Groq, database, JWT-signing, or credential-encryption keys.
- It returns OCR text and PCM audio only after an explicit user action.
- Electron terminates the helper when the application exits.

### Provider credentials

- User LLM keys remain encrypted in the hosted database and are submitted only through authenticated REST calls.
- The administrator-managed Groq STT key remains backend-only.
- No provider key is stored in the installer, renderer bundle, or helper.

## Data flow

### Analyze Screen

1. User clicks **Analyze Screen**.
2. Electron captures the selected display locally.
3. The local helper runs LiteParse OCR.
4. Electron sends a bounded `screen.text` event to Render.
5. Render builds the screen-solving prompt using the authenticated user's resume and selected LLM.
6. Tokens stream back to the overlay.

No screenshot is uploaded in the production path.

### Meeting audio

1. User explicitly starts system-audio capture.
2. The local helper captures Windows WASAPI loopback PCM.
3. Electron sends bounded PCM chunks over the authenticated WebSocket with source `system-audio`.
4. Render performs VAD and Groq transcription.
5. Final interviewer text is added to conversation context.
6. Mock Interview mode generates one resume-grounded first-person response; Meeting mode does not automatically answer.

## Runtime configuration

Packaged defaults are public configuration, not secrets:

```text
COPILOT_DESKTOP_ENVIRONMENT=production
COPILOT_API_BASE_URL=https://ai-desktop-copilot-api.onrender.com
COPILOT_WS_URL=wss://ai-desktop-copilot-api.onrender.com/ws
```

- The API URL is compiled into the release configuration and may be overridden by an administrator-controlled configuration file for staging.
- Production rejects HTTP, WS, embedded URL credentials, query strings, and unexpected paths.
- `COPILOT_LOCAL_AUTH_TOKEN` is not required by a production package.

## Installer design

Use `electron-builder` with NSIS:

- Per-user installation by default; no administrator elevation required for the first release.
- Install Dashboard, overlay, Electron main/preload files, and the signed local helper executable.
- Create Start Menu and optional desktop shortcuts.
- Use `asar` for application JavaScript and place the helper in `extraResources`.
- Store mutable application state under Electron `userData`, never inside the installation directory.
- Uninstall removes program files but does not silently delete user-controlled diagnostic exports.

## Implementation gates

### F1 -- Production authentication and protocol (implemented)

- Make `X-Copilot-Token` development-only.
- Add explicit `screen.text` and sourced audio-chunk protocol handling.
- Add JWT expiry and production WebSocket tests.

### F2 -- Local helper (implemented)

- Build the Windows helper entrypoint for LiteParse and WASAPI.
- Add private IPC, lifecycle management, bounded payloads, and failure codes.
- Add helper unit/contract tests.

### F3 -- Electron integration

- Route Analyze Screen through local OCR text.
- Route system audio through local PCM chunks.
- Preserve explicit capture controls, overlay lifecycle, and Mock Interview/Meeting behavior.

### F4 -- Installer and release artifact

- Add NSIS/electron-builder configuration, icons, packaged endpoint defaults, and helper resources.
- Produce an unsigned test installer and unpacked artifact.
- Verify install, launch, sign-in, overlay, uninstall, and second-laptop setup.

### F5 -- Distribution hardening

- Code-sign Electron and the helper.
- Add release checksums and an update channel.
- Add optional per-device registration/revocation.

F5 requires a code-signing certificate and release-hosting decision and is not required for the first private test installer.

## Acceptance criteria for the private test installer

1. A clean Windows laptop can install and launch without Python, Node.js, or repository source.
2. The user signs in against Render and the WebSocket connects over WSS.
3. No shared backend or provider secret exists in installed files.
4. Resume data restores from Neon after login.
5. Analyze Screen performs local OCR and streams a response.
6. System audio is captured locally and transcribed through hosted Groq STT.
7. Overlay show/hide and explicit Start Overlay behavior remain correct.
8. Closing the application terminates capture and the local helper.
9. Build, helper, backend, protocol, and installer checks pass.

## Explicit non-goals for the first private installer

- Public Microsoft Store distribution.
- Silent enterprise deployment.
- Automatic database or PostgreSQL installation.
- Storing original resume files in S3/MinIO.
- Automatic updates before signing and release hosting are selected.