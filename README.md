# AI Desktop Copilot

Windows-first desktop copilot for meeting assistance, coding, learning,
personal productivity, and accessibility. It combines live microphone
transcription with screen-derived context and streams assistance into a
transparent desktop overlay.

This project intentionally does not support deception or covert assessment
assistance. The overlay must remain a user-controlled, visible desktop tool.

## Status

**Milestone 4 — desktop overlay.** The application now has a secure Electron main-process WebSocket client, a settings/control window, and a separate transparent always-on-top overlay that renders streamed Markdown. Audio, screen capture, and external providers remain intentionally deferred to later milestones.

## Planned repository layout

```text
desktop/   Electron main, preload, renderer, overlay UI
backend/   FastAPI application and provider adapters
shared/    Versioned protocol schemas shared by desktop and backend
docs/      Architecture, contracts, setup, and development documentation
scripts/   Developer and packaging automation
tests/     Cross-component, WebSocket, and end-to-end tests
```

See [the architecture contract](docs/ARCHITECTURE.md) and
[the milestone plan](docs/MILESTONES.md).
