# Per-user LLM provider architecture

## Decision

Move LLM provider ownership from the administrator portal to each authenticated
user's Candidate Dashboard. Keep speech-to-text ownership in the administrator
portal.

The supported LLM providers are:

- OpenAI
- Groq
- OpenRouter
- Gemini
- Ollama Cloud

These are bring-your-own-key integrations. The product must not promise that a
provider or model is permanently free; provider free tiers, quotas, and model
catalogs can change independently of this application.

## Product boundary

### Candidate Dashboard

The Dashboard owns one active LLM configuration per user:

- provider
- model name
- write-only API key
- validation status and masked key hint
- replace and remove actions

The key is required before resume parsing, mock-interview answers, meeting
assistance, or screen-question solving can use an LLM. Existing resume data
remains available when an LLM configuration is missing.

### Administrator portal

The administrator portal retains only the global Groq speech-to-text
configuration. Its provider-readiness metric becomes `0/1` or `1/1`, and the
OpenAI LLM card and LLM rotation workflow are removed.

Administrators do not see, recover, replace, or use a user's LLM API key.

## Security model

- LLM credentials are encrypted with the existing backend-only
  `COPILOT_CREDENTIAL_MASTER_KEY` using AES-256-GCM.
- Associated authenticated data includes user ID, provider, purpose, and
  credential ID, preventing ciphertext from being reassigned between users.
- Raw keys are accepted only by authenticated backend endpoints and are never
  returned by any API.
- Read endpoints return provider, model, status, masked hint, and validation
  timestamps only.
- Provider base URLs are a server-side allowlist. Users cannot submit arbitrary
  URLs, preventing server-side request forgery.
- Logs, audit events, WebSocket events, and error responses never contain raw
  credentials.
- Replacing a key follows pending -> validate -> active. An invalid replacement
  never removes the user's previous active configuration.
- User LLM changes are recorded in a user-scoped security audit without storing
  request bodies or secrets.

## Persistence

Add a dedicated `user_llm_credentials` table rather than widening the existing
global `provider_credentials` table.

Required fields:

| Field | Purpose |
| --- | --- |
| `id` | Credential version UUID |
| `user_id` | Owner, referencing `users(id)` |
| `provider` | Fixed provider identifier |
| `purpose` | Always `llm` |
| `model` | User-selected provider model ID |
| `ciphertext`, `nonce` | AES-GCM encrypted key material |
| `masked_hint`, `fingerprint` | Safe identity and duplicate detection |
| `status` | `pending`, `active`, `invalid`, or `retired` |
| validation timestamps/error code | Operational status without raw errors |
| creation/activation/retirement timestamps | Version history |

Database invariants:

- At most one active LLM credential per user.
- Activation and retirement occur in one transaction.
- Every query and mutation includes the authenticated `user_id`.
- Deleting the user cascades through their LLM credential versions.

The existing `provider_credentials` table remains global and is restricted to
administrator-managed STT credentials.

## Authenticated API contract

All user LLM routes require the normal user JWT:

```text
GET    /api/llm/config
POST   /api/llm/config/validate
PUT    /api/llm/config
DELETE /api/llm/config
```

Write request:

```json
{
  "provider": "openrouter",
  "model": "provider/model-id",
  "credential": "write-only-secret"
}
```

Safe read response:

```json
{
  "configured": true,
  "provider": "openrouter",
  "model": "provider/model-id",
  "status": "active",
  "maskedHint": "...abcd",
  "lastValidatedAt": "timestamp"
}
```

Provider IDs are exactly `openai`, `groq`, `openrouter`, `gemini`, and
`ollama_cloud`.

Validation uses a minimal call through the same inference path the application
will use. It must not rely only on listing models, because restricted provider
keys can allow inference while denying model-list endpoints. Validation may use
a very small amount of provider quota.

## Runtime request routing

The current WebSocket authenticates only an installation token and the current
LLM streamer is global. Both must change.

1. The renderer passes its user JWT to Electron main through a narrow IPC method.
2. Electron main retains the JWT in memory and reconnects the backend WebSocket
   with both the installation token and user JWT.
3. FastAPI validates both credentials before accepting the WebSocket.
4. The server binds the verified `user_id` to that connection. Client event
   payloads cannot override it.
5. Every `LlmRequest` carries the server-bound user ID.
6. A user-scoped resolver loads and decrypts that user's active LLM
   configuration at operation start.
7. A provider router creates the appropriate adapter and streams normalized
   `LlmDelta` events through the existing session protocol.

Groq STT resolution remains global and administrator-managed. A Groq LLM key
owned by a user and the Groq STT key owned by the administrator are distinct
credentials with distinct scopes.

## Provider adapter strategy

All adapters implement the existing provider-neutral streaming interface, but
wire protocols remain explicit:

| Provider | Adapter strategy |
| --- | --- |
| OpenAI | OpenAI Responses API |
| Groq LLM | Groq supported text/Responses interface |
| OpenRouter | Stable OpenAI-compatible chat-completions path; do not depend on its beta Responses API |
| Gemini | Google's documented OpenAI-compatible chat-completions endpoint |
| Ollama Cloud | Native `https://ollama.com/api` streaming client with bearer authentication |

`ollama_cloud` specifically means Ollama's hosted Cloud API at
`https://ollama.com`, not a locally installed Ollama server at
`http://localhost:11434`. The user creates an API key on `ollama.com`; the
backend constructs the official Ollama client with `host="https://ollama.com"`
and an `Authorization: Bearer <user-key>` header, then streams
`client.chat(model, messages, stream=True)`. The API key is resolved from that
user's encrypted LLM configuration and is never placed in a shared backend
environment variable.

Capabilities are checked per adapter. Text-only models can answer transcript and
resume prompts but cannot solve image-based screen questions. For image input,
the API returns a sanitized `provider_model_image_not_supported` error instead
of silently dropping the image.

## Resume parsing

Resume parsing becomes user-scoped and uses the user's active LLM provider. The
authenticated user ID already exists on the resume route, so the parser resolves
the user configuration before parsing. A missing configuration returns
`llm_configuration_required` and does not delete an existing parsed profile.

## Dashboard flow

The Dashboard remains the entry page. Add a compact `AI model` section before
the resume/session setup:

1. Select provider.
2. Enter model ID.
3. Enter API key.
4. Validate and save.
5. Show only provider, model, active status, and masked hint afterward.

Changing provider/model/key is explicit and does not automatically open the
overlay or navigate to the Resume page. Starting the overlay remains a separate
user action.

## Migration behavior

- Do not copy the existing global OpenAI key into user records.
- Existing user profiles and accounts remain unchanged.
- After deployment, users without an LLM configuration see a clear setup prompt.
- The old global OpenAI credential can be retired after the user-scoped runtime
  is verified.
- The global Groq STT credential remains active and continues to be managed from
  the administrator portal.

## Milestones and review gates

### Milestone A - Backend ownership and schema

- Add user LLM schema/repository/service/API.
- Add provider allowlist and safe validation results.
- Keep existing runtime behavior unchanged behind tests.

### Milestone B - User-aware runtime routing

- Authenticate WebSockets with installation token plus user JWT.
- Add user identity to LLM requests.
- Implement provider router and five adapters.
- Route resume parsing through the user provider.

### Milestone C - Candidate Dashboard

- Add the compact provider/model/key UI.
- Restore safe configuration metadata after login.
- Require valid LLM configuration for new LLM operations.

### Milestone D - Administrator portal reduction

- Remove LLM/OpenAI management.
- Keep only Groq STT management and adjust overview counts/copy.

### Milestone E - migration, deployment, and end-to-end verification

- Run additive Neon migration.
- Deploy Render and Vercel.
- Verify each provider independently, then verify resume parsing, overlay text,
  screen solving, and global Groq STT.

No implementation milestone starts until this architecture is approved.
