# Admin Portal Architecture Contract

Status: Proposed for review. No implementation is authorized by this document.

## 1. Objective

Create a centrally hosted, administrator-only portal that shows product usage and
allows authorized administrators to rotate the backend OpenAI and Groq credentials
without exposing any provider secret to ordinary users, Electron renderers, logs, or
API responses.

The portal must support:

- total registered users;
- recent and active-user metrics with explicit definitions;
- users with or without a parsed resume profile;
- provider configuration health for OpenAI LLM and Groq STT;
- safe provider-key replacement and validation;
- rotation history and security audit events.

## 2. Product boundary

The admin portal is a separate browser application, not part of the transparent
Electron overlay. It can be deployed independently (for example, as a Vercel static
frontend) and communicates only with protected FastAPI admin endpoints.

Discovering or loading the admin UI is never treated as authorization. Every admin
API request must independently enforce the administrator role in the backend.

Ordinary users must never receive:

- plaintext provider keys;
- encrypted key ciphertext;
- key prefixes long enough to reconstruct a key;
- provider account details, quotas, or raw provider errors;
- admin user lists or aggregate operational data.

## 3. Roles and authentication

Add a `role` column to `users` with allowed values `user` and `admin`. Public signup
always creates `user`. An administrator cannot be created by a public request.

The first administrator is provisioned by a controlled deployment command using a
backend-only bootstrap identity such as `COPILOT_BOOTSTRAP_ADMIN_EMAIL`. Subsequent
role changes require an existing administrator and create an audit event.

Admin endpoints require:

1. a valid access token;
2. a current database lookup proving `role = admin`;
3. optional recent re-authentication for provider-key rotation;
4. rate limiting and CSRF protection when cookie authentication is introduced.

A role claim may be included in a short-lived token for UI rendering, but the database
remains authoritative for destructive or secret-management operations.

## 4. User metrics

Definitions must be visible in the UI:

- **Total users**: count of rows in `users`.
- **New users**: accounts created in the last 7 or 30 days.
- **Users with profiles**: users with a row in `candidate_profiles_by_user`.
- **Recently active**: users whose `last_login_at` or `last_activity_at` falls within
  the selected period.
- **Live sessions**: connected authenticated WebSocket sessions, if connection
  tracking is enabled. This is not the same as recently active users.

Required schema additions:

- `users.role`;
- `users.last_login_at`;
- optional `users.last_activity_at`;
- optional `session_events` for durable session analytics.

The first release should avoid invasive analytics. Store timestamps and event types,
not transcript text, audio, screenshots, prompts, or model responses.

## 5. Provider credential model

Provider credentials are write-only secrets. API reads return metadata only.

Suggested `provider_credentials` fields:

- `id` UUID;
- `provider` (`openai` or `groq`);
- `purpose` (`llm` or `stt`);
- `ciphertext` and encryption metadata;
- `masked_hint` such as `...a1b2`;
- non-reversible fingerprint for duplicate detection;
- `status` (`pending`, `active`, `invalid`, `retired`);
- `last_validated_at`;
- normalized `last_error_code`;
- `created_by` administrator ID;
- `created_at`, `activated_at`, and `retired_at`.

Never store plaintext keys. Encrypt secrets using an application master key held in
the hosting platform's secret manager/environment, never in PostgreSQL. For stronger
production isolation, use a managed secret manager and keep only a secret reference
in PostgreSQL.

The master encryption key is not editable through the admin portal.

## 6. Rotation workflow

Provider-key replacement is an atomic workflow:

1. Administrator selects OpenAI or Groq.
2. Portal asks for recent password verification.
3. Administrator enters the new key in a password-style input.
4. Browser sends it once over HTTPS directly to FastAPI.
5. FastAPI validates its format and performs a minimal provider authentication test.
6. FastAPI encrypts it and creates a `pending` version.
7. If validation succeeds, one database transaction activates the new version and
   retires the old version.
8. Runtime provider-client caches are invalidated.
9. A small server-side smoke request confirms the active credential.
10. The API returns only status, masked hint, timestamps, and a normalized result.
11. The browser clears the input immediately.

If validation fails, the old credential remains active. A failed replacement must
never interrupt working user sessions.

Keys do not necessarily have a formal expiry time. Operational status should distinguish:

- invalid or revoked credential;
- quota or billing exhaustion;
- rate limiting;
- provider outage or timeout;
- unknown validation failure.

The portal must not label every provider error as `expired`.

## 7. Runtime credential reload

The current backend constructs OpenAI and Groq adapters at application startup from
`Settings`. This must change before portal-based rotation can work.

Introduce backend-only abstractions:

- `ProviderCredentialStore` to load/decrypt the active version;
- `ProviderCredentialResolver` with a short bounded cache;
- `ProviderClientFactory` to construct or refresh provider clients;
- cache invalidation after successful rotation;
- health state that never includes plaintext credentials.

Existing sessions may finish with the credential they started with. New sessions use
the newly active version immediately. Rotation must not require a backend restart.

Environment variables remain an emergency/bootstrap fallback. The portal clearly
shows whether a provider is using a managed database/secret-manager credential or an
environment fallback, without displaying either secret.

## 8. Admin API contract

Proposed endpoints:

- `GET /api/admin/overview`
- `GET /api/admin/users?query=&page=&pageSize=`
- `GET /api/admin/providers`
- `POST /api/admin/providers/{provider}/validate`
- `PUT /api/admin/providers/{provider}/credential`
- `POST /api/admin/providers/{provider}/rollback`
- `GET /api/admin/audit-events?page=&pageSize=`

`GET /api/admin/providers` example:

```json
{
  "providers": [
    {
      "provider": "openai",
      "purpose": "llm",
      "status": "healthy",
      "maskedHint": "...a1b2",
      "source": "managed",
      "lastValidatedAt": "2026-08-03T10:00:00Z",
      "lastErrorCode": null
    }
  ]
}
```

No response schema contains a `key`, `secret`, `ciphertext`, or reversible credential.
Use `Cache-Control: no-store` on all admin responses.

## 9. Portal pages

### Overview

- total users;
- users with parsed profiles;
- new users in the chosen period;
- recently active users;
- provider health summary;
- recent administrative events.

### Users

- searchable, paginated email and account ID;
- role, created time, last login, profile readiness;
- no password hashes, resume content, transcripts, or provider secrets.

### Provider keys

- one card each for OpenAI LLM and Groq STT;
- healthy/degraded/invalid/unknown status;
- masked hint and last validation time;
- Replace key action;
- Validate current key action;
- tightly controlled rollback to the immediately previous encrypted version;
- confirmation plus recent re-authentication for rotation/rollback.

### Audit

- actor administrator;
- action type;
- provider or target user ID;
- timestamp, result, request correlation ID, and source IP policy;
- never request bodies, keys, ciphertext, or raw authorization headers.

## 10. Security controls

- Admin authorization enforced only in FastAPI, never only in React routing.
- HTTPS required; public HTTP is redirected or rejected.
- Strict Content Security Policy for the admin origin.
- Separate admin CORS allowlist.
- Rate limits for login, validation, rotation, and rollback.
- Recent re-authentication and optional TOTP/WebAuthn MFA for secret changes.
- Secrets redacted from structured logs and exception tracking.
- Database backups protect ciphertext, while the encryption key is backed up separately.
- Key rotation audit events are append-only.
- No provider key is sent to Electron, the user Dashboard, WebSocket events, or telemetry.

## 11. Failure behavior

- Provider validation failure keeps the old active key.
- Database failure prevents rotation rather than using an unrecorded key.
- Cache invalidation failure returns an incomplete-rotation error and triggers an alert.
- If no valid provider key exists, affected user operations return a normalized
  `provider_not_configured` or `provider_authentication_failed` error.
- The portal can display a warning, but it never reveals the provider response body.

## 12. Milestones and review gates

1. **Architecture review**: approve this contract and choose secret storage
   (encrypted PostgreSQL or managed secret manager).
2. **Authorization foundation**: migrations, admin bootstrap, role dependency, and
   security tests.
3. **Read-only portal**: overview, users, provider metadata, and audit list.
4. **Credential service**: encryption, masked metadata, validation, and repository.
5. **Runtime reload**: resolver/factory integration for OpenAI and Groq.
6. **Rotation UI**: replace, validate, re-authenticate, rollback, and audit behavior.
7. **Deployment hardening**: HTTPS, CSP, CORS, rate limiting, backups, alerts, and
   clean production verification.

No milestone advances past its review gate without approval.

## 13. Acceptance criteria

- Ordinary users receive `403` from every admin endpoint.
- Public signup cannot create an administrator.
- No API or log reveals plaintext keys or ciphertext.
- User counts match database fixtures and pagination is stable.
- A rejected new key leaves the old key active.
- A valid rotation affects new LLM/STT sessions without backend restart.
- OpenAI and Groq failures are classified without calling all failures `expired`.
- Every rotation, rollback, role change, and failed admin authorization is audited.
- Electron and the normal user Dashboard never receive provider credentials.
