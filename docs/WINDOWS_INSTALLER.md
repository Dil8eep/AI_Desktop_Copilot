# Windows Installer

## Status

Milestone F4 implemented for an unsigned private Windows x64 test release.

## Build prerequisites

The build laptop requires:

- Windows x64
- Node.js 22 or later with repository dependencies installed
- Python 3.12 and the synchronized `backend/.venv`
- Internet access the first time Electron Builder downloads Electron and NSIS tools

From `C:\Users\dileep\Desktop\ND\desktop`:

```powershell
npm run dist:win
node scripts\verify-release.mjs --require-installer
```


pm run dist:win` performs the PyInstaller helper build, desktop typecheck and production build, Electron packaging, and NSIS installer creation.

## Generated artifacts

Generated release files are intentionally ignored by Git:

```text
desktop/release/win-unpacked/
desktop/release/AI-Desktop-Copilot-Setup-0.1.1-x64.exe
desktop/release/AI-Desktop-Copilot-Setup-0.1.1-x64.exe.blockmap
```

The installer is approximately 118 MiB. The packaged helper is stored at `resources/local-helper/copilot-local-helper.exe`, outside `app.asar`, and includes Python 3.12, LiteParse, and PyAudioWPatch runtime components.

## Installation on another laptop

1. Copy `AI-Desktop-Copilot-Setup-0.1.1-x64.exe` to the Windows x64 laptop.
2. Run the installer and choose the per-user installation directory.
3. Because this private build is unsigned, Windows SmartScreen may display an unknown-publisher warning. Review the filename and source before choosing to continue.
4. Launch **AI Desktop Copilot** from the Start Menu or desktop shortcut.
5. Sign in with the existing account or create a new one.
6. Existing users recover their parsed resume profile from Neon. New users upload and parse a resume once.
7. Select and configure the preferred user LLM provider in the Dashboard.
8. Start the overlay explicitly, then test Analyze Screen and Start Listening.

The installed laptop does not need Python, Node.js, PostgreSQL, or repository source. It does require internet access to the Render backend and the configured LLM provider. Groq STT remains administrator-managed on the backend.

## Automated release verification

The release verifier checks:

- Main executable, `app.asar`, helper executable, and installer exist and are non-empty.
- The packaged Render HTTPS endpoint is present.
- Known database and JWT secret markers are absent from `app.asar`.
- The packaged helper completes `ready`, `pong`, and graceful shutdown.
- Bundled LiteParse extracts text from a generated non-private PNG test image.
- The actual packaged Electron executable starts in production mode, locates the helper, and exits successfully through `--release-smoke-test`.

A temporary silent installation test also completed with installer, installed-app smoke test, and uninstaller exit codes of zero, leaving no test installation directory.

## Manual acceptance still required

Before sharing the installer broadly, test on a separate clean Windows x64 laptop:

- Windows SmartScreen flow
- Sign-up and sign-in against Render
- Existing resume restoration from Neon
- Local LiteParse Analyze Screen on a real display
- WASAPI speaker-output capture and Groq transcription
- Mock Interview automatic first-person answer behavior
- Meeting mode non-automatic behavior
- Overlay show, hide, restore, and application shutdown
- Start Menu and desktop shortcuts
- Interactive uninstall

These hardware, account, and second-device checks cannot be proven by a build-only test on the development laptop.

## Current distribution boundary

This is an unsigned private test installer. Milestone F5 is required for code signing, release checksums, update hosting, and optional device registration/revocation.
## Blank window correction

Version `0.1.0` used drive-root `/assets/...` URLs that work in the Vite development server but fail from an installed `file://` page. Version `0.1.1` uses relative `./assets/...` URLs, removes the default Electron menu bar, and adds both a static asset-path gate and an installed Dashboard mount test.

Do not redistribute the `0.1.0` installer. Uninstall it and install `AI-Desktop-Copilot-Setup-0.1.1-x64.exe`.