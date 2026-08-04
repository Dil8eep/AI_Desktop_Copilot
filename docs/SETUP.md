# Setup Guide

## Prerequisites

- Windows 11 (V1 target), Node.js 22 or later, npm, Python 3.12, and `uv`.
- No provider key is needed through Milestone 4: the backend LLM stream is
  deterministic and mocked.

## Install dependencies

From the repository root:

```powershell
npm install
uv sync --project backend --all-groups --python 3.12
```

## Run the backend

In the first terminal:

```powershell
cd C:\Users\dileep\Desktop\ND\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

The backend is loopback-only. The default development token is shared with the
desktop app; production startup will generate a different token per launch.
Visit `http://127.0.0.1:8765/docs` for the generated FastAPI reference and
`http://127.0.0.1:8765/health` for a health check.

## Run desktop and overlay

In a second terminal:

```powershell
cd C:\Users\dileep\Desktop\ND
npm run dev:desktop
```

Two windows appear: the **Control Center** and the transparent,
always-on-top **Overlay**. Enter a prompt in the Control Center and select
**Stream to overlay**. The deterministic backend response appears incrementally
in the overlay. Drag it by its title bar, resize it natively, adjust opacity and
font size in the Control Center, or toggle it with `Ctrl+Shift+Space`.

Use the tray menu to restore the Control Center or show the overlay. Stop the
development processes with `Ctrl+C` in their respective terminals.
## Screen sharing privacy

On supported Windows 10 version 2004+ capture APIs, the overlay requests content
protection and should be omitted from an entire-screen share while staying
visible locally. Restart the desktop app after updating. Verify this with a
second meeting participant before relying on it: application, browser, GPU, and
meeting-client capture paths can differ.