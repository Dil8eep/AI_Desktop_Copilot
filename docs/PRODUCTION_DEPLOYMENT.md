# Milestone 7: Production deployment and operations

## Deployment boundary

This repository is a hybrid desktop application, not a fully browser-hosted application.

- Render hosts the FastAPI REST and WebSocket backend.
- Neon hosts PostgreSQL users, resume profiles, credential versions, and audit events.
- Vercel hosts only `admin-portal`, the browser-based administrator UI.
- Electron, the floating overlay, local audio/WASAPI capture, and LiteParse OCR remain installed on each Windows laptop.
- Resume object storage (MinIO, Cloudflare R2, or S3) is not wired yet. The current upload service uses backend-local disk, which is ephemeral on Render and must not be treated as durable storage.

## 1. Provision Neon

Create a Neon PostgreSQL project and copy its pooled connection string. Use the asyncpg form in Render:

```text
postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE?ssl=require
```

Do not put it in Git or a Vercel variable. It belongs only in the Render backend environment.

## 2. Generate deployment secrets

Run these locally from `backend` and copy each output directly into Render. Generate separate values; never reuse one secret for another purpose.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Use the outputs for `COPILOT_JWT_SECRET`, `COPILOT_LOCAL_AUTH_TOKEN`, and `COPILOT_CREDENTIAL_MASTER_KEY` respectively. Keep an encrypted offline backup of the master key. Losing it makes stored OpenAI and Groq credentials undecryptable; changing it without re-encrypting existing records has the same effect.

## 3. Deploy the backend on Render

Connect this repository and apply the root `render.yaml` Blueprint. Set every `sync: false` value shown in `backend/deployment.env.example`.

Set:

- `COPILOT_ALLOWED_HOSTS` to only the Render service hostname, without `https://`.
- `COPILOT_CORS_ORIGINS` to the final Vercel admin origin. Add other trusted origins as a comma-separated list only when needed.
- `COPILOT_BOOTSTRAP_ADMIN_EMAIL` to the existing account that should become administrator.

The start command runs the idempotent schema migration before Uvicorn. The migration creates the tables and an append-only database trigger for admin audit events. The service will refuse to start in production with development secrets, wildcard CORS/hosts, HTTP-only mode, a local database URL, or no credential master key.

Health endpoints:

- `/health/live` confirms the API process is running.
- `/health/ready` confirms PostgreSQL is reachable and is the Render health check.

After the user account exists, run the bootstrap promotion using a one-off Render shell with the same environment:

```bash
.venv/bin/python -m app.admin_cli promote-bootstrap-admin
```

## 4. Deploy the admin portal on Vercel

Import the repository as a Vercel project and set its Root Directory to `admin-portal`. Add:

```text
VITE_API_BASE_URL=https://YOUR_RENDER_SERVICE.onrender.com
```

Deploy, then update `COPILOT_CORS_ORIGINS` on Render to the exact Vercel production URL and redeploy the backend. The committed Vercel policy adds browser security headers. API keys are submitted only to the backend and are never returned by backend read endpoints.

## 5. Configure Windows desktop clients

The desktop application must remain installed and running locally. Point its backend HTTP/WebSocket configuration at the Render URL while retaining the local capture helper and overlay. Do not deploy the Electron dashboard itself to Vercel: browser sandboxes cannot provide the existing transparent overlay and WASAPI behavior.

The backend `COPILOT_LOCAL_AUTH_TOKEN` and any corresponding desktop configuration must be distributed through a secure installation/configuration channel, not embedded in a public web bundle.

## Operational checks

After each release:

1. Confirm `/health/live` returns 200.
2. Confirm `/health/ready` returns 200 and `database: available`.
3. Sign in to the Vercel admin portal.
4. Validate a provider key, replace it, and confirm only masked metadata appears afterward.
5. Start a fresh desktop request and verify it uses the new provider version.
6. Check Render logs for request IDs and status codes. Request bodies, authorization headers, transcripts, and API keys must not appear.

Credential replacement publishes a PostgreSQL notification inside the same transaction. Every running backend worker listens for it and invalidates that provider's in-memory cache. Operations already in flight keep their original client; the next operation resolves the new active version.

## Backup and recovery

- Enable Neon point-in-time restore or scheduled backups available on the selected plan.
- Periodically test a restore into a separate Neon branch/database.
- Back up `COPILOT_CREDENTIAL_MASTER_KEY` separately in an encrypted password manager or secrets vault.
- Before restoring provider credential rows, ensure the matching master key is available.
- Roll back application code by redeploying the last known-good commit. Database migrations in this milestone are additive; do not delete tables during an application rollback.
- Provider-key rollback is available from the admin portal and revalidates the retired key before activation.

## Alerts and free-tier limits

At minimum, alert on repeated `/health/ready` failures, HTTP 5xx spikes, login 429 spikes, and provider validation failures. Free Render/Neon/Vercel tiers may sleep, throttle, change quotas, or omit production-grade backup/alerting guarantees. They are suitable for demos and low-traffic evaluation, not an uptime-sensitive multi-user service without reviewing the current provider limits.

## Remaining deployment work

Milestone 7 hardens and packages the hosted backend/admin path. A distributable multi-user product still needs durable resume object storage, authenticated per-installation desktop provisioning, an Electron installer/updater, and a secure release/signing process.
