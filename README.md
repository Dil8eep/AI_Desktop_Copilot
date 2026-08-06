# AI Desktop Copilot

AI Desktop Copilot is a Windows desktop application that combines a preparation
Dashboard with a visible, always-on-top assistant overlay. It can use a saved
resume profile, live meeting audio, and locally extracted screen text to provide
context-aware assistance.

The application is designed for consented meetings, mock-interview practice,
learning, accessibility, and personal productivity. It should not be used for
deception, covert monitoring, or violating assessment rules.

## What the application includes

- Electron Dashboard and transparent overlay for Windows.
- Account signup and login with renewable authenticated sessions.
- PDF resume upload, LiteParse/Tesseract extraction, and persistent parsed
  profiles.
- Job role, company, and experience-level session context.
- User-selected LLM providers: Groq, OpenRouter, Ollama Cloud, Gemini, or OpenAI.
- Meeting mode for normal assistance.
- Mock Interview mode with automatic, concise, first-person answers grounded in
  the uploaded resume.
- Local screen analysis for questions, multiple-choice questions, and coding
  problems.
- Local microphone and Windows system-audio capture.
- Groq speech-to-text configured centrally by an administrator.
- Admin portal for users, provider readiness, credential rotation, and audit
  information.
- FastAPI backend, PostgreSQL/Neon persistence, and Render deployment support.

## Current architecture

~~~text
Windows desktop
|-- Electron Dashboard
|-- Visible overlay
|-- Local LiteParse/Tesseract screen extraction
|-- Local microphone and WASAPI system-audio capture
|
|-- HTTPS and WSS
    |
    |-- FastAPI backend on Render
        |-- Authentication and token refresh
        |-- Resume-profile persistence
        |-- Per-user encrypted LLM credentials
        |-- Administrator-managed speech-to-text credential
        |-- PostgreSQL database on Neon or local Docker

Admin portal
|-- React and Vite
|-- Connects to the same FastAPI backend
~~~

Raw provider API keys are never returned by the backend. User LLM credentials
are encrypted before being stored. Temporary uploaded PDF files are deleted
after successful parsing; the parsed profile remains until the user replaces it
with a new resume.

## Repository structure

~~~text
admin-portal/   React/Vite administrator portal
backend/        FastAPI backend, database, providers, OCR and local helper
desktop/        Electron Dashboard, overlay and Windows installer configuration
scripts/        Repository automation
shared/         Shared protocol schemas
tests/          Cross-component tests
render.yaml     Render backend deployment blueprint
docker-compose.yml  Local PostgreSQL service
~~~

## Option 1: Install the Windows application

This is the easiest option for a normal user. The installer is currently
unsigned and is distributed as a local build artifact rather than a public
internet download.

### Requirements

- Windows 10 or Windows 11, 64-bit.
- Internet access to the deployed backend and selected AI provider.
- An API key for one supported LLM provider.
- A PDF resume for resume-grounded assistance.

### Installation

1. Obtain AI-Desktop-Copilot-Setup-0.1.2-x64.exe from the project owner.
2. Copy the actual EXE file to the target laptop using Google Drive, OneDrive,
   email, USB, or another file-sharing service. A local path from another
   computer is not a download URL.
3. Double-click the EXE file.
4. If Microsoft Defender SmartScreen displays Windows protected your PC,
   select More info and then Run anyway only when the file came from the
   trusted project owner.
5. Choose the installation directory and complete the installer.
6. Start AI Desktop Copilot from the desktop shortcut or Start menu.

The locally built installer is created at:

~~~text
desktopeleaseAI-Desktop-Copilot-Setup-0.1.2-x64.exe
~~~

## First-time application setup

1. Open AI Desktop Copilot.
2. Create an account with an email address and a password of at least eight
   characters, or sign in to an existing account.
3. In Connect a provider, select Groq, OpenRouter, Ollama Cloud, Gemini, or
   OpenAI.
4. Enter the exact model ID supported by that provider.
5. Enter the provider API key and select the validation/save action.
6. Upload a PDF resume.
7. Enter the target job role and company.
8. Select the appropriate experience level.
9. Select Start session. The backend uploads the PDF temporarily, extracts its
   contents, creates the parsed profile, and saves that profile to the account.
10. Select Start Overlay.

On later sign-ins, the saved parsed profile is restored automatically. A new PDF
is required only when the user wants to replace the existing resume profile.

## Using the overlay

### Meeting mode

Use Meeting mode for normal meeting assistance. Start the microphone or system
audio only with the participants' consent. The transcript and available screen
context are sent to the configured backend for response generation.

### Mock Interview mode

Use Mock Interview mode for explicit practice. Each newly finalized interviewer
question is answered automatically in a concise first-person voice. Personal
facts, qualifications, projects, skills, education, and experience are taken
only from the saved resume profile.

### Analyze Screen

Select Analyze Screen when a visible question needs assistance. Screen
extraction occurs locally through LiteParse/Tesseract. The extracted text is
then sent to the selected LLM, which can return:

- A direct answer and explanation for a normal question.
- The selected option and reasoning for a multiple-choice question.
- An approach, code, and explanation for a coding problem.

### Hiding and restoring the overlay

The overlay can be hidden from its controls. Use Show Overlay from the Dashboard
to make it visible again.

## Option 2: Run the project from source

Use these instructions for development on a Windows laptop.

### Prerequisites

- Git.
- Node.js 22 or newer.
- Python 3.12.
- Docker Desktop for local PostgreSQL.
- PowerShell.

### 1. Clone and install JavaScript dependencies

~~~powershell
git clone https://github.com/Dil8eep/AI_Desktop_Copilot.git
Set-Location AI_Desktop_Copilot
npm install
~~~

### 2. Create the Python environment

~~~powershell
Set-Location backend
python -m venv .venv
..venvScriptspython.exe -m pip install uv
..venvScriptspython.exe -m uv sync --dev
Copy-Item .env.example .env
~~~

Open backend.env and replace placeholder values. Never commit this file.

Generate a JWT secret:

~~~powershell
..venvScriptspython.exe -c 'import secrets; print(secrets.token_urlsafe(48))'
~~~

Generate the credential-encryption master key:

~~~powershell
..venvScriptspython.exe -c 'from app.infrastructure.credential_cipher import CredentialCipher; print(CredentialCipher.generate_master_key())'
~~~

Place the generated values in backend.env:

~~~dotenv
COPILOT_JWT_SECRET=replace-with-generated-jwt-secret
COPILOT_CREDENTIAL_MASTER_KEY=replace-with-generated-master-key
COPILOT_DATABASE_URL=postgresql+asyncpg://copilot_user:change-this-password@127.0.0.1:5434/ai_desktop_copilot
COPILOT_BACKEND_HOST=127.0.0.1
COPILOT_BACKEND_PORT=8765
COPILOT_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:5174,http://localhost:5174,null
COPILOT_ALLOWED_HOSTS=127.0.0.1,localhost,testserver
~~~

Provider API keys should be entered through the Dashboard or admin portal, not
placed in Git.

### 3. Start PostgreSQL

From the repository root:

~~~powershell
Set-Location ..
docker compose up -d
~~~

The local database listens only on 127.0.0.1:5434.

### 4. Migrate and start the backend

~~~powershell
Set-Location backend
..venvScriptspython.exe -m app.database_cli migrate
..venvScriptspython.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
~~~

Verify the backend in a browser:

~~~text
http://127.0.0.1:8765/health/ready
~~~

A healthy response contains a ready status.

### 5. Start the desktop application

Keep the backend terminal running. Open a second PowerShell terminal:

~~~powershell
Set-Location C:path	oAI_Desktop_Copilot
npm run dev:desktop
~~~

Development mode automatically uses:

~~~text
HTTP: http://127.0.0.1:8765
WebSocket: ws://127.0.0.1:8765/ws
~~~

HTTP and WebSocket endpoints must always point to the same backend because the
same JWT secret validates both connections.

### 6. Start the admin portal

Open a third PowerShell terminal:

~~~powershell
Set-Location C:path	oAI_Desktop_Copilot
npm run dev:admin
~~~

Open:

~~~text
http://127.0.0.1:5174
~~~

The Vite development server proxies API requests to
http://127.0.0.1:8765.

## Creating the first administrator

1. Create the intended administrator account through normal application signup.
2. Set COPILOT_BOOTSTRAP_ADMIN_EMAIL in backend.env to that exact email.
3. Run:

~~~powershell
Set-Location backend
..venvScriptspython.exe -m app.admin_cli promote-bootstrap-admin
~~~

The command prints bootstrap_admin_promoted when successful. The administrator
uses the same account email and password in the admin portal.

## Building a Windows installer

The build packages the Electron application and the local Python
capture/OCR helper:

~~~powershell
Set-Location desktop
npm run dist:win
node scriptserify-release.mjs --require-installer
~~~

The installer is generated in desktopelease. Generated release and build
artifacts are intentionally not committed to Git.

Because the installer is not code-signed, Windows SmartScreen may warn users.
Public distribution should add a trusted Windows code-signing certificate and a
hosted release/download process.

## Cloud deployment

The intended hosted split is:

- Backend: Render.
- PostgreSQL: Neon.
- Admin portal: Vercel.
- Dashboard and overlay: installed Electron application on each Windows laptop.
- OCR, microphone, and system-audio helper: local on each Windows laptop.

The Electron overlay cannot be replaced by a normal Vercel webpage because it
uses local Windows APIs for always-on-top overlay behavior, screen capture, and
WASAPI audio.

### Render backend

The root render.yaml configures the backend build, database migration, Uvicorn
startup, port binding, and health check. Configure these secrets in Render:

~~~text
COPILOT_DATABASE_URL
COPILOT_JWT_SECRET
COPILOT_CREDENTIAL_MASTER_KEY
COPILOT_BOOTSTRAP_ADMIN_EMAIL
COPILOT_CORS_ORIGINS
COPILOT_ALLOWED_HOSTS
~~~

Use the Neon async SQLAlchemy URL format:

~~~text
postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE?ssl=require
~~~

Do not place real database passwords, JWT secrets, encryption keys, OpenAI keys,
Groq keys, or other provider credentials in Git.

The current production health endpoint is:

~~~text
https://ai-desktop-copilot-api.onrender.com/health/ready
~~~

### Vercel admin portal

Create a Vercel project with admin-portal as the root directory and set:

~~~dotenv
VITE_API_BASE_URL=https://ai-desktop-copilot-api.onrender.com
~~~

Add the Vercel production domain to COPILOT_CORS_ORIGINS in Render, then redeploy
the backend.

## Common commands

From the repository root:

~~~powershell
npm run dev:desktop
npm run build:desktop
npm run lint:desktop
npm run test:desktop
npm run dev:admin
npm run build:admin
npm run typecheck:admin
~~~

Backend checks:

~~~powershell
Set-Location backend
..venvScriptspython.exe -m ruff check app
..venvScriptspython.exe -m mypy app
~~~

## Troubleshooting

### Render shows GET / as 404

This is expected because the backend does not provide a homepage. Use
/health/ready instead.

### Render shows port 10000

This is normal. Render supplies the PORT environment variable and Uvicorn binds
to that internal port.

### WebSocket 403 or expired token

Install the latest desktop version, completely close older Copilot/Electron
processes, reopen the application, and sign in again. Version 0.1.2 renews
access tokens automatically and stops retrying after an authentication
rejection.

### Resume parsing reports empty or invalid output

LiteParse first extracts text from the PDF. The selected LLM must then return a
JSON resume profile. The backend retries one empty or malformed response and
shows a clear error if the model still fails. Verify the provider/model or choose
a model that reliably follows structured JSON instructions.

### Admin portal cannot sign in

Confirm that the account exists, was promoted through app.admin_cli, and that
the portal points to the same backend where that user is stored.

### Blank installed application window

Install version 0.1.2 or newer. Packaged renderer assets use relative paths in
the corrected build.

## Security and privacy notes

- Never commit .env files or real credentials.
- Never expose provider API keys in frontend source code.
- Keep the overlay visible and under user control.
- Obtain consent before capturing or transcribing other participants.
- Use HTTPS and WSS in production.
- Rotate a secret immediately if it is accidentally exposed.
- The current installer is unsigned and intended for controlled testing.

## License and distribution

No public license is currently declared. Treat the repository and installer as
private project software unless the owner adds an explicit license.
