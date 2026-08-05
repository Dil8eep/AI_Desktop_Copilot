import { FormEvent, useCallback, useEffect, useState } from "react";

type View = "overview" | "users" | "providers" | "audit";
type Metrics = {
  total_users: number;
  new_users: number;
  recently_active: number;
  users_with_profiles: number;
};
type UserRecord = {
  id: string;
  email: string;
  role: string;
  created_at: string;
  last_login_at: string | null;
  profile_ready: boolean;
};
type Provider = {
  provider: string;
  purpose: string;
  model: string | null;
  status: "configured" | "missing" | "active" | "invalid";
  source: string;
  maskedHint: string | null;
  lastValidatedAt: string | null;
  lastErrorCode: string | null;
  canRollback: boolean;
  managementAvailable: boolean;
};
type AuditEvent = {
  id: string;
  actor_email: string | null;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  result: string;
  correlation_id: string | null;
  created_at: string;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const TOKEN_KEY = "copilot_admin_access_token";

const icons: Record<View, string> = {
  overview: "O",
  users: "U",
  providers: "P",
  audit: "A",
};

function formatDate(value: string | null): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function apiRequest<T>(
  path: string,
  token: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let code =
      response.status === 401
        ? "session_expired"
        : response.status === 403
          ? "admin_required"
          : "request_failed";
    try {
      const body = (await response.json()) as {
        detail?: string | { error?: string };
      };
      if (typeof body.detail === "string") code = body.detail;
      else if (body.detail?.error) code = body.detail.error;
    } catch {
      // Keep the normalized fallback; raw provider responses are never exposed.
    }
    throw new Error(code);
  }
  return (await response.json()) as T;
}

function Login({
  onAuthenticated,
}: {
  onAuthenticated: (token: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const login = await fetch(`${API_BASE}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!login.ok) throw new Error("invalid_credentials");
      const result = (await login.json()) as {
        accessToken: string;
        role: string;
      };
      if (result.role !== "admin") throw new Error("admin_required");
      await apiRequest("/api/admin/access", result.accessToken);
      sessionStorage.setItem(TOKEN_KEY, result.accessToken);
      onAuthenticated(result.accessToken);
    } catch (reason) {
      const message =
        reason instanceof Error ? reason.message : "request_failed";
      setError(
        message === "admin_required"
          ? "This account does not have administrator access."
          : "We could not sign you in. Check your email and password.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />
      <section className="login-card">
        <div className="brand-mark">C</div>
        <p className="eyebrow">AI DESKTOP COPILOT</p>
        <h1>Administration, with clarity.</h1>
        <p className="login-copy">
          A secure operational view of users, resume readiness, and speech
          transcription.
        </p>
        <form onSubmit={submit}>
          <label>
            Work email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="admin@company.com"
              autoComplete="username"
              required
            />
          </label>
          <label>
            Password
            <span className="password-field">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
                minLength={8}
                required
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? "Hide" : "Show"}
              </button>
            </span>
          </label>
          {error && <div className="error-banner">{error}</div>}
          <button className="primary-button" disabled={busy}>
            {busy ? "Verifying..." : "Sign in to Admin"}
          </button>
        </form>
        <p className="security-note">
          Protected by database-verified administrator access
        </p>
      </section>
    </main>
  );
}

function MetricCard({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: number;
  note: string;
  tone: string;
}) {
  return (
    <article className={`metric-card ${tone}`}>
      <div className="metric-top">
        <span>{label}</span>
        <i />
      </div>
      <strong>{value.toLocaleString()}</strong>
      <p>{note}</p>
    </article>
  );
}

export function AdminApp() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem(TOKEN_KEY) ?? "",
  );
  const [view, setView] = useState<View>("overview");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [period, setPeriod] = useState(7);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [successNotice, setSuccessNotice] = useState("");
  const [credentialDialog, setCredentialDialog] = useState<{
    provider: Provider;
    mode: "replace" | "rollback";
  } | null>(null);

  const signOut = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY);
    setToken("");
    setMetrics(null);
  }, []);

  const loadView = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setNotice("");
    try {
      if (view === "overview") {
        const [overview, providerData] = await Promise.all([
          apiRequest<{ metrics: Metrics }>(
            `/api/admin/overview?periodDays=${period}`,
            token,
          ),
          apiRequest<{ providers: Provider[] }>("/api/admin/providers", token),
        ]);
        setMetrics(overview.metrics);
        setProviders(providerData.providers);
      } else if (view === "users") {
        const data = await apiRequest<{ users: UserRecord[] }>(
          `/api/admin/users?query=${encodeURIComponent(search)}&pageSize=50`,
          token,
        );
        setUsers(data.users);
      } else if (view === "providers") {
        const data = await apiRequest<{ providers: Provider[] }>(
          "/api/admin/providers",
          token,
        );
        setProviders(data.providers);
      } else {
        const data = await apiRequest<{ events: AuditEvent[] }>(
          "/api/admin/audit-events?pageSize=50",
          token,
        );
        setEvents(data.events);
      }
    } catch (reason) {
      const message =
        reason instanceof Error ? reason.message : "request_failed";
      if (message === "session_expired" || message === "admin_required")
        signOut();
      else
        setNotice(
          "The admin service is unavailable. Check the backend connection and try again.",
        );
    } finally {
      setLoading(false);
    }
  }, [period, search, signOut, token, view]);

  useEffect(() => {
    void loadView();
  }, [loadView]);

  if (!token) return <Login onAuthenticated={setToken} />;

  const configuredProviders = providers.filter(
    (provider) =>
      provider.status === "configured" || provider.status === "active",
  ).length;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark small">C</div>
          <div>
            <strong>Copilot</strong>
            <span>ADMIN CONSOLE</span>
          </div>
        </div>
        <nav aria-label="Admin navigation">
          {(Object.keys(icons) as View[]).map((item) => (
            <button
              key={item}
              className={view === item ? "active" : ""}
              onClick={() => setView(item)}
            >
              <span>{icons[item]}</span>
              {item === "audit"
                ? "Audit trail"
                : item === "providers"
                  ? "Speech"
                  : item}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="secure-dot">
            <i />
            Backend verified
          </div>
          <button onClick={signOut}>Sign out</button>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">CONTROL CENTER</p>
            <h1>
              {view === "audit"
                ? "Audit trail"
                : view === "providers"
                  ? "Speech"
                  : view[0].toUpperCase() + view.slice(1)}
            </h1>
          </div>
          <div className="top-actions">
            <button
              className="icon-button"
              onClick={() => void loadView()}
              title="Refresh"
            >
              Refresh
            </button>
            <div className="avatar">AD</div>
          </div>
        </header>

        {notice && <div className="error-banner wide">{notice}</div>}
        {successNotice && <div className="success-banner">{successNotice}</div>}
        {loading && <div className="loading-line" />}

        {view === "overview" && (
          <section className="page-stack">
            <div className="section-heading">
              <div>
                <h2>System overview</h2>
                <p>A privacy-safe snapshot of your Copilot workspace.</p>
              </div>
              <select
                value={period}
                onChange={(e) => setPeriod(Number(e.target.value))}
              >
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={90}>Last 90 days</option>
              </select>
            </div>
            <div className="metrics-grid">
              <MetricCard
                label="Total users"
                value={metrics?.total_users ?? 0}
                note="All registered accounts"
                tone="violet"
              />
              <MetricCard
                label="New users"
                value={metrics?.new_users ?? 0}
                note={`Created in the last ${period} days`}
                tone="cyan"
              />
              <MetricCard
                label="Resume ready"
                value={metrics?.users_with_profiles ?? 0}
                note="Users with parsed profiles"
                tone="green"
              />
              <MetricCard
                label="Recently active"
                value={metrics?.recently_active ?? 0}
                note={`Signed in within ${period} days`}
                tone="amber"
              />
            </div>
            <div className="overview-grid">
              <article className="panel">
                <div className="panel-title">
                  <div>
                    <h3>Speech readiness</h3>
                    <p>Administrator-managed transcription service</p>
                  </div>
                  <span className="summary-pill">
                    {configuredProviders}/{providers.length} configured
                  </span>
                </div>
                <div className="provider-list">
                  {providers.map((provider) => (
                    <ProviderRow key={provider.provider} provider={provider} />
                  ))}
                </div>
              </article>
              <article className="panel definition-panel">
                <h3>How metrics are calculated</h3>
                <dl>
                  <div>
                    <dt>Total users</dt>
                    <dd>Every account stored in the users table.</dd>
                  </div>
                  <div>
                    <dt>Resume ready</dt>
                    <dd>Accounts with a parsed candidate profile.</dd>
                  </div>
                  <div>
                    <dt>Recently active</dt>
                    <dd>Accounts that signed in during the selected period.</dd>
                  </div>
                </dl>
              </article>
            </div>
          </section>
        )}

        {view === "users" && (
          <section className="page-stack">
            <div className="section-heading">
              <div>
                <h2>User directory</h2>
                <p>Account metadata only. Resume content is never shown.</p>
              </div>
              <form
                className="search"
                onSubmit={(e) => {
                  e.preventDefault();
                  setSearch(query);
                }}
              >
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by email"
                />
                <button>Search</button>
              </form>
            </div>
            <div className="table-panel">
              <table>
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th>Resume</th>
                    <th>Joined</th>
                    <th>Last login</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.email}</strong>
                        <span className="subtle-id">{user.id}</span>
                      </td>
                      <td>
                        <span className={`role ${user.role}`}>{user.role}</span>
                      </td>
                      <td>
                        <span
                          className={user.profile_ready ? "ready" : "not-ready"}
                        >
                          {user.profile_ready ? "Ready" : "Not uploaded"}
                        </span>
                      </td>
                      <td>{formatDate(user.created_at)}</td>
                      <td>{formatDate(user.last_login_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!loading && users.length === 0 && (
                <EmptyState
                  title="No users found"
                  text="Try a different email search."
                />
              )}
            </div>
          </section>
        )}

        {view === "providers" && (
          <section className="page-stack">
            <div className="section-heading">
              <div>
                <h2>Speech transcription</h2>
                <p>
                  Validate, rotate, and roll back the administrator-managed STT
                  credential.
                </p>
              </div>
            </div>
            <div className="provider-grid">
              {providers.map((provider) => (
                <article className="provider-card" key={provider.provider}>
                  <div className={`provider-logo ${provider.provider}`}>G</div>
                  <div className="provider-card-head">
                    <div>
                      <p>{provider.purpose.toUpperCase()}</p>
                      <h3>Groq</h3>
                    </div>
                    <span className={`status ${provider.status}`}>
                      {provider.status}
                    </span>
                  </div>
                  <div className="provider-details provider-details-wide">
                    <div>
                      <span>Credential source</span>
                      <strong>{provider.source}</strong>
                    </div>
                    <div>
                      <span>Model</span>
                      <strong>{provider.model ?? "Not selected"}</strong>
                    </div>
                    <div>
                      <span>Credential</span>
                      <strong>{provider.maskedHint ?? "Hidden"}</strong>
                    </div>
                    <div>
                      <span>Last validated</span>
                      <strong>
                        {provider.lastValidatedAt
                          ? formatDate(provider.lastValidatedAt)
                          : "Not validated"}
                      </strong>
                    </div>
                  </div>
                  {!provider.managementAvailable && (
                    <p className="configuration-warning">
                      Set COPILOT_CREDENTIAL_MASTER_KEY and restart the backend
                      to enable management.
                    </p>
                  )}
                  <div className="provider-actions">
                    <button
                      className="secondary-button"
                      disabled={!provider.managementAvailable}
                      onClick={() =>
                        setCredentialDialog({ provider, mode: "replace" })
                      }
                    >
                      Validate & replace
                    </button>
                    <button
                      className="ghost-button"
                      disabled={
                        !provider.managementAvailable || !provider.canRollback
                      }
                      onClick={() =>
                        setCredentialDialog({ provider, mode: "rollback" })
                      }
                    >
                      Roll back
                    </button>
                  </div>
                  <p className="provider-footnote">
                    Existing keys remain unreadable. New values are sent once
                    over the protected backend API.
                  </p>
                </article>
              ))}
            </div>
            <div className="info-banner">
              <span>i</span>
              <div>
                <strong>Runtime reload enabled</strong>
                <p>
                  A successful STT replacement is used by new transcription
                  operations immediately. In-progress audio finishes with its
                  existing client.
                </p>
              </div>
            </div>
          </section>
        )}
        {view === "audit" && (
          <section className="page-stack">
            <div className="section-heading">
              <div>
                <h2>Administrative audit trail</h2>
                <p>
                  Security-relevant actions without request bodies or secrets.
                </p>
              </div>
            </div>
            <div className="table-panel">
              <table>
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Administrator</th>
                    <th>Target</th>
                    <th>Result</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id}>
                      <td>
                        <strong>{event.action}</strong>
                        <span className="subtle-id">
                          {event.correlation_id ?? "No correlation ID"}
                        </span>
                      </td>
                      <td>
                        {event.actor_email ?? event.actor_user_id ?? "System"}
                      </td>
                      <td>
                        {event.target_type
                          ? `${event.target_type}: ${event.target_id ?? "--"}`
                          : "--"}
                      </td>
                      <td>
                        <span className={`status ${event.result}`}>
                          {event.result}
                        </span>
                      </td>
                      <td>{formatDate(event.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!loading && events.length === 0 && (
                <EmptyState
                  title="No audit events yet"
                  text="Future administrative changes will appear here."
                />
              )}
            </div>
          </section>
        )}
      </main>
      {credentialDialog && (
        <CredentialDialog
          provider={credentialDialog.provider}
          mode={credentialDialog.mode}
          token={token}
          onClose={() => setCredentialDialog(null)}
          onCompleted={async (message) => {
            setCredentialDialog(null);
            setSuccessNotice(message);
            await loadView();
          }}
        />
      )}
    </div>
  );
}

function credentialErrorMessage(code: string): string {
  const messages: Record<string, string> = {
    credential_master_key_not_configured:
      "Credential management is not configured on the backend.",
    credential_format_invalid: "The key format does not match this provider.",
    provider_authentication_failed: "The provider rejected this API key.",
    provider_model_not_available:
      "This key does not have access to the selected model.",
    provider_rate_limited:
      "The provider rate-limited validation. Try again shortly.",
    provider_timeout: "The provider did not respond in time.",
    provider_unavailable: "The provider is temporarily unavailable.",
    recent_authentication_failed:
      "Your administrator session is no longer authorized.",
    rollback_credential_not_found:
      "There is no previous managed key to restore.",
  };
  return messages[code] ?? "The operation could not be completed safely.";
}

function CredentialDialog({
  provider,
  mode,
  token,
  onClose,
  onCompleted,
}: {
  provider: Provider;
  mode: "replace" | "rollback";
  token: string;
  onClose: () => void;
  onCompleted: (message: string) => Promise<void>;
}) {
  const [credential, setCredential] = useState("");
  const [model, setModel] = useState(provider.model ?? "");
  const [showCredential, setShowCredential] = useState(false);
  const [validation, setValidation] = useState<"idle" | "valid" | "invalid">(
    "idle",
  );
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const providerName = "Groq";

  async function validateCredential() {
    setBusy(true);
    setMessage("");
    try {
      const result = await apiRequest<{
        valid: boolean;
        errorCode: string | null;
      }>(`/api/admin/providers/${provider.provider}/validate`, token, {
        method: "POST",
        body: JSON.stringify({ credential, model: model || null }),
      });
      if (result.valid) {
        setValidation("valid");
        setMessage("Credential and model access verified.");
      } else {
        setValidation("invalid");
        setMessage(
          credentialErrorMessage(result.errorCode ?? "request_failed"),
        );
      }
    } catch (reason) {
      setValidation("invalid");
      setMessage(
        credentialErrorMessage(
          reason instanceof Error ? reason.message : "request_failed",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function replaceCredential() {
    if (validation !== "valid") return;
    setBusy(true);
    setMessage("");
    try {
      await apiRequest(
        `/api/admin/providers/${provider.provider}/credential`,
        token,
        {
          method: "PUT",
          body: JSON.stringify({ credential, model: model || null }),
        },
      );
      setCredential("");
      await onCompleted(`${providerName} credential activated successfully.`);
    } catch (reason) {
      setMessage(
        credentialErrorMessage(
          reason instanceof Error ? reason.message : "request_failed",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function rollbackCredential() {
    setBusy(true);
    setMessage("");
    try {
      await apiRequest(
        `/api/admin/providers/${provider.provider}/rollback`,
        token,
        {
          method: "POST",
          body: JSON.stringify({}),
        },
      );
      await onCompleted(
        `${providerName} restored to the previous validated credential.`,
      );
    } catch (reason) {
      setMessage(
        credentialErrorMessage(
          reason instanceof Error ? reason.message : "request_failed",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="credential-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="credential-title"
      >
        <div className="modal-head">
          <div>
            <p className="eyebrow">
              {mode === "replace" ? "SECURE ROTATION" : "SAFE ROLLBACK"}
            </p>
            <h2 id="credential-title">
              {mode === "replace"
                ? `Manage ${providerName}`
                : `Roll back ${providerName}`}
            </h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            x
          </button>
        </div>
        {mode === "replace" ? (
          <div className="modal-form">
            <label>
              Model
              <input
                value={model}
                onChange={(event) => {
                  setModel(event.target.value);
                  setValidation("idle");
                }}
                placeholder="Enter transcription model ID"
                required
              />
            </label>
            <label>
              New API key
              <span className="password-field">
                <input
                  type={showCredential ? "text" : "password"}
                  value={credential}
                  onChange={(event) => {
                    setCredential(event.target.value);
                    setValidation("idle");
                  }}
                  placeholder="Paste the new provider key"
                  autoComplete="off"
                  required
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowCredential((visible) => !visible)}
                  aria-label={showCredential ? "Hide API key" : "Show API key"}
                >
                  {showCredential ? "Hide" : "Show"}
                </button>
              </span>
            </label>

            {message && (
              <div
                className={
                  validation === "valid"
                    ? "validation-message valid"
                    : "validation-message invalid"
                }
              >
                {message}
              </div>
            )}
            <div className="modal-actions">
              <button className="ghost-button" onClick={onClose}>
                Cancel
              </button>
              <button
                className="secondary-button"
                disabled={busy || !credential || !model}
                onClick={() => void validateCredential()}
              >
                {busy ? "Working..." : "Validate"}
              </button>
              <button
                className="primary-button compact"
                disabled={busy || validation !== "valid"}
                onClick={() => void replaceCredential()}
              >
                Activate key
              </button>
            </div>
          </div>
        ) : (
          <div className="modal-form">
            <div className="rollback-warning">
              <strong>Restore the previous credential?</strong>
              <p>
                The previous encrypted version will be validated before
                activation. The current key remains active if validation fails.
              </p>
            </div>

            {message && (
              <div className="validation-message invalid">{message}</div>
            )}
            <div className="modal-actions">
              <button className="ghost-button" onClick={onClose}>
                Cancel
              </button>
              <button
                className="primary-button compact"
                disabled={busy}
                onClick={() => void rollbackCredential()}
              >
                {busy ? "Validating..." : "Validate & roll back"}
              </button>
            </div>
          </div>
        )}
        <p className="modal-security">
          Keys are write-only, encrypted before storage, and cleared from this
          form after use.
        </p>
      </section>
    </div>
  );
}

function ProviderRow({ provider }: { provider: Provider }) {
  return (
    <div className="provider-row">
      <div className={`provider-logo ${provider.provider}`}>G</div>
      <div>
        <strong>Groq</strong>
        <span>Speech transcription</span>
      </div>
      <span className={`status ${provider.status}`}>{provider.status}</span>
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <div>*</div>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}
