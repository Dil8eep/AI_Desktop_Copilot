import {
  useCallback,
  useEffect,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import type { RuntimeInfo } from "../../../shared/desktopApi";
import { useDesktopStore } from "../store/desktopStore";

type AuthMode = "login" | "signup";
type View = "dashboard" | "resume" | "sessions";
type ProfileRecord = Readonly<Record<string, unknown>>;
type LlmProvider = "groq" | "openrouter" | "ollama_cloud" | "gemini" | "openai";
type LlmConfiguration = Readonly<{
  configured: boolean;
  provider?: LlmProvider;
  model?: string;
  status?: string;
  maskedHint?: string;
}>;

const LLM_PROVIDERS: ReadonlyArray<Readonly<{ value: LlmProvider; label: string }>> = [
  { value: "groq", label: "Groq" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "ollama_cloud", label: "Ollama Cloud" },
  { value: "gemini", label: "Gemini" },
  { value: "openai", label: "OpenAI" },
];

type ProfileSectionProps = Readonly<{
  title: string;
  value: unknown;
}>;

const EXPERIENCE_LEVELS = [
  "Fresher",
  "Less than 1 year",
  "2 years",
  "3 years",
  "4 years",
  "5 years",
  "6 years",
  "7 years",
  "8 years",
  "9 years",
  "10 years",
  "More than 10 years",
] as const;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const humanize = (value: string): string =>
  value
    .replaceAll("_", " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const profileText = (value: unknown): string => {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(profileText).filter(Boolean).join(" | ");
  }
  if (isRecord(value)) {
    return Object.values(value).map(profileText).filter(Boolean).join(" | ");
  }
  return "";
};

const detailContent = (value: unknown): ReactNode => {
  if (Array.isArray(value)) {
    return (
      <ul className="profile-bullet-list">
        {value.map((item, index) => (
          <li key={`${profileText(item)}-${index}`}>{profileText(item)}</li>
        ))}
      </ul>
    );
  }
  return profileText(value);
};

const ProfileSection = ({ title, value }: ProfileSectionProps): ReactElement => {
  if (Array.isArray(value)) {
    return (
      <section className="profile-section">
        <h2>{humanize(title)}</h2>
        <div className="profile-entry-list">
          {value.map((entry, index) =>
            isRecord(entry) ? (
              <article className="profile-entry" key={`${title}-${index}`}>
                {Object.entries(entry).map(([key, item]) => (
                  <div className="profile-entry-field" key={key}>
                    <span>{humanize(key)}</span>
                    <div>{detailContent(item)}</div>
                  </div>
                ))}
              </article>
            ) : (
              <article className="profile-entry" key={`${title}-${index}`}>
                {profileText(entry)}
              </article>
            ),
          )}
        </div>
      </section>
    );
  }

  if (isRecord(value)) {
    return (
      <section className="profile-section">
        <h2>{humanize(title)}</h2>
        <div className="profile-group-list">
          {Object.entries(value).map(([key, item]) => (
            <article className="profile-group" key={key}>
              <h3>{humanize(key)}</h3>
              <p>{profileText(item)}</p>
            </article>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="profile-section">
      <h2>{humanize(title)}</h2>
      <p>{profileText(value)}</p>
    </section>
  );
};

const ProfileView = ({
  profile,
}: Readonly<{ profile: ProfileRecord }>): ReactElement => {
  const candidate = isRecord(profile.candidate) ? profile.candidate : {};
  const sections = isRecord(profile.sections) ? profile.sections : {};
  const additionalSections = isRecord(profile.additional_sections)
    ? profile.additional_sections
    : {};
  const summary = profileText(profile.summary);
  const name = profileText(candidate.name) || "Candidate profile";
  const contactFields = ["email", "phone", "location", "linkedin"]
    .map((key) => ({ key, value: profileText(candidate[key]) }))
    .filter((entry) => entry.value);

  return (
    <div className="profile-view">
      <section className="profile-overview">
        <div>
          <p className="kicker">PARSED RESUME</p>
          <h2>{name}</h2>
        </div>
        {contactFields.length > 0 && (
          <div className="profile-contact-list">
            {contactFields.map(({ key, value }) => (
              <span key={key}>{value}</span>
            ))}
          </div>
        )}
        {summary && <p className="profile-summary">{summary}</p>}
      </section>
      {Object.entries(sections).map(([title, value]) => (
        <ProfileSection key={title} title={title} value={value} />
      ))}
      {Object.entries(additionalSections).map(([title, value]) => (
        <ProfileSection key={title} title={title} value={value} />
      ))}
    </div>
  );
};

export const App = (): ReactElement => {
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [view, setView] = useState<View>("dashboard");
  const [accessToken, setAccessToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [llmProvider, setLlmProvider] = useState<LlmProvider>("groq");
  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [showLlmApiKey, setShowLlmApiKey] = useState(false);
  const [llmConfiguration, setLlmConfiguration] = useState<LlmConfiguration>({
    configured: false,
  });
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmMessage, setLlmMessage] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [candidateProfile, setCandidateProfile] = useState<ProfileRecord | null>(null);
  const [jobRole, setJobRole] = useState("");
  const [company, setCompany] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [profilePrepared, setProfilePrepared] = useState(false);
  const [sessionStarted, setSessionStarted] = useState(false);
  const { backendStatus } = useDesktopStore();
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfo | null>(null);
  const apiBaseUrl = runtimeInfo?.apiBaseUrl ?? "";

  useEffect(() => {
    void window.desktopApi
      .getRuntimeInfo()
      .then(setRuntimeInfo)
      .catch(() => setMessage("Desktop backend configuration is unavailable."));
  }, []);

  const restoreLlmConfiguration = useCallback(
    async (token: string, signal?: AbortSignal): Promise<LlmConfiguration> => {
      const response = await fetch(`${apiBaseUrl}/api/llm/config`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal,
      });
      if (!response.ok) {
        throw new Error("Unable to load your AI model configuration.");
      }
      const result = (await response.json()) as LlmConfiguration;
      setLlmConfiguration(result);
      if (result.configured && result.provider && result.model) {
        setLlmProvider(result.provider);
        setLlmModel(result.model);
      }
      return result;
    },
    [apiBaseUrl],
  );
  const restoreCandidateProfile = useCallback(
    async (token: string, signal?: AbortSignal): Promise<ProfileRecord | null> => {
      const response = await fetch(`${apiBaseUrl}/api/profile`, {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        signal,
      });
      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? "Your session expired. Please sign in again."
            : "Unable to load your saved resume profile.",
        );
      }
      const result = (await response.json()) as { profile?: unknown };
      if (!isRecord(result.profile)) {
        await window.desktopApi.setCandidateProfileContext(null);
        setCandidateProfile(null);
        setProfilePrepared(false);
        return null;
      }
      await window.desktopApi.setCandidateProfileContext(result.profile);
      setCandidateProfile(result.profile);
      setProfilePrepared(true);
      setSessionStarted(false);
      const preferences = isRecord(result.profile.session_preferences)
        ? result.profile.session_preferences
        : {};
      if (typeof preferences.job_role === "string") {
        setJobRole(preferences.job_role);
      }
      if (typeof preferences.company === "string") {
        setCompany(preferences.company);
      }
      if (typeof preferences.experience_level === "string") {
        setExperienceLevel(preferences.experience_level);
      }
      return result.profile;
    },
    [apiBaseUrl],
  );

  useEffect(() => {
    void window.desktopApi.setAccessToken(accessToken || null);
  }, [accessToken]);
  useEffect(() => {
    if (!refreshToken || !apiBaseUrl) return;
    const refreshAccessToken = async (): Promise<void> => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refreshToken }),
        });
        const result = (await response.json()) as {
          accessToken?: string;
          refreshToken?: string;
        };
        if (!response.ok || !result.accessToken || !result.refreshToken) {
          throw new Error("refresh_failed");
        }
        setAccessToken(result.accessToken);
        setRefreshToken(result.refreshToken);
      } catch {
        setAccessToken("");
        setRefreshToken("");
        setMessage("Your session expired. Please sign in again.");
      }
    };
    const timer = window.setInterval(() => void refreshAccessToken(), 10 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [refreshToken, apiBaseUrl]);
  useEffect(() => {
    if (!accessToken || !apiBaseUrl) return;
    const controller = new AbortController();
    setMessage("Signed in. Loading your saved workspace...");
    void Promise.all([
      restoreCandidateProfile(accessToken, controller.signal),
      restoreLlmConfiguration(accessToken, controller.signal),
    ])
      .then(([profile, llm]) => {
        if (controller.signal.aborted) return;
        if (!llm.configured) {
          setMessage("Signed in. Configure an AI model before using Copilot.");
          return;
        }
        setMessage(
          profile
            ? "Signed in. Your AI model and saved resume profile are ready."
            : "AI model ready. Upload and parse a resume to prepare your profile.",
        );
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setMessage(
          error instanceof Error
            ? error.message
            : "Unable to load your saved workspace.",
        );
      });
    return () => controller.abort();
  }, [accessToken, apiBaseUrl, restoreCandidateProfile, restoreLlmConfiguration]);
  const authenticate = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      if (!apiBaseUrl) {
        throw new Error("Desktop backend configuration is still loading.");
      }
      const endpoint = authMode === "login" ? "login" : "signup";
      const response = await fetch(`${apiBaseUrl}/api/auth/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const result = (await response.json()) as {
        accessToken?: string;
        refreshToken?: string;
        error?: string;
      };
      if (!response.ok || !result.accessToken || !result.refreshToken) {
        throw new Error(result.error ?? "Authentication failed.");
      }
      setAccessToken(result.accessToken);
      setRefreshToken(result.refreshToken);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setBusy(false);
    }
  };

  const saveLlmConfiguration = async (): Promise<void> => {
    if (!llmModel.trim() || !llmApiKey.trim()) {
      setLlmMessage("Enter the provider model name and API key.");
      return;
    }
    setLlmBusy(true);
    setLlmMessage("Validating the provider and model...");
    try {
      const response = await fetch(`${apiBaseUrl}/api/llm/config`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        cache: "no-store",
        body: JSON.stringify({
          provider: llmProvider,
          model: llmModel.trim(),
          credential: llmApiKey.trim(),
        }),
      });
      const result = (await response.json()) as LlmConfiguration & {
        detail?: string | { error?: string };
      };
      if (!response.ok || !result.configured) {
        const detail =
          typeof result.detail === "string" ? result.detail : result.detail?.error;
        throw new Error(detail ?? "The provider rejected this configuration.");
      }
      setLlmConfiguration(result);
      setLlmApiKey("");
      setShowLlmApiKey(false);
      setLlmMessage("AI model validated and saved securely.");
    } catch (error) {
      setLlmMessage(
        error instanceof Error ? error.message : "Unable to save the AI model.",
      );
    } finally {
      setLlmBusy(false);
    }
  };

  const removeLlmConfiguration = async (): Promise<void> => {
    setLlmBusy(true);
    setLlmMessage("Removing your AI model configuration...");
    try {
      const response = await fetch(`${apiBaseUrl}/api/llm/config`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Unable to remove the AI model.");
      setLlmConfiguration({ configured: false });
      setLlmApiKey("");
      setSessionStarted(false);
      setLlmMessage("AI model removed. Add another configuration to use Copilot.");
    } catch (error) {
      setLlmMessage(
        error instanceof Error ? error.message : "Unable to remove the AI model.",
      );
    } finally {
      setLlmBusy(false);
    }
  };
  const onResumeChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0] ?? null;
    if (file && file.type !== "application/pdf") {
      setResume(null);
      setMessage("Please select a PDF resume.");
      return;
    }
    setResume(file);
    setMessage("");
  };

  const startSession = async (): Promise<void> => {
    if (!llmConfiguration.configured) {
      setMessage("Configure and validate an AI model before parsing a resume.");
      return;
    }
    if (!resume || !jobRole.trim() || !company.trim() || !experienceLevel) {
      setMessage("Add a resume, job role, company, and experience before starting.");
      return;
    }
    setBusy(true);
    setMessage("Uploading and preparing your profile...");
    try {
      if (!apiBaseUrl) {
        throw new Error("Desktop backend configuration is unavailable.");
      }
      const headers = { Authorization: `Bearer ${accessToken}` };
      const upload = await fetch(`${apiBaseUrl}/api/resume/upload`, {
        method: "POST",
        headers: {
          ...headers,
          "Content-Type": "application/pdf",
          "X-Filename": resume.name,
        },
        body: await resume.arrayBuffer(),
      });
      if (!upload.ok) throw new Error("Resume upload failed.");
      const parse = await fetch(`${apiBaseUrl}/api/resume/parse`, {
        method: "POST",
        headers,
      });
      const parsed = (await parse.json()) as {
        error?: string;
        profile?: Record<string, unknown>;
      };
      if (!parse.ok || !parsed.profile) {
        if (parse.status === 401) {
          setAccessToken("");
          setRefreshToken("");
          throw new Error("Your session expired. Please sign in again.");
        }
        const parsingMessages: Record<string, string> = {
          resume_profile_empty_response:
            "The selected model returned an empty resume profile. Try again or choose another model.",
          resume_profile_invalid_json:
            "The selected model did not return a valid resume profile. Try again or choose another model.",
        };
        throw new Error(
          (parsed.error && parsingMessages[parsed.error]) ??
            parsed.error ??
            "Resume parsing failed.",
        );
      }
      const sessionProfile = {
        session_preferences: {
          experience_level: experienceLevel,
          job_role: jobRole.trim(),
          company: company.trim(),
        },
        ...parsed.profile,
      };
      await window.desktopApi.setCandidateProfileContext(sessionProfile);
      setCandidateProfile(sessionProfile);
      setProfilePrepared(true);
      setSessionStarted(false);
      setMessage("Profile prepared. Select Start Overlay when you are ready.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to start the session.",
      );
    } finally {
      setBusy(false);
    }
  };

  const openOverlay = async (): Promise<void> => {
    if (!llmConfiguration.configured) {
      setMessage("Configure and validate an AI model before starting the overlay.");
      return;
    }
    try {
      if (sessionStarted) {
        await window.desktopApi.showOverlay();
      } else {
        await window.desktopApi.startOverlaySession();
        setSessionStarted(true);
      }
      setMessage("");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to open the overlay.",
      );
    }
  };
  if (!accessToken) {
    return (
      <main className="auth-page">
        <section className="auth-panel">
          <div className="auth-brand">
            <span>CP</span>
            <div>
              <p>AI DESKTOP COPILOT</p>
              <h1>Prepare with clarity.</h1>
            </div>
          </div>
          <p className="auth-copy">
            A private workspace for consented meeting assistance, learning,
            accessibility, and coding practice.
          </p>
          <form onSubmit={(event) => void authenticate(event)}>
            <label>
              Email
              <input
                autoComplete="email"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                required
                type="email"
                value={email}
              />
            </label>
            <label>
              Password
              <span className="password-field">
                <input
                  autoComplete={
                    authMode === "login" ? "current-password" : "new-password"
                  }
                  minLength={8}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="At least 8 characters"
                  required
                  type={showPassword ? "text" : "password"}
                  value={password}
                />
                <button
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="password-toggle"
                  onClick={() => setShowPassword((current) => !current)}
                  type="button"
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24">
                    {showPassword ? (
                      <path d="m3 3 18 18m-5.3-5.3A4.5 4.5 0 0 1 9.3 9.3M5.3 5.3C3.3 6.9 2 9 2 12c2.2 4 5.5 6 10 6 1.3 0 2.5-.2 3.6-.6M9.9 4.1c.7-.1 1.4-.1 2.1-.1 4.5 0 7.8 2 10 6- .4.8-.9 1.5-1.5 2.2M14.1 14.1A3 3 0 0 1 9.9 9.9" />
                    ) : (
                      <path d="M2 12c2.2-4 5.5-6 10-6s7.8 2 10 6c-2.2 4-5.5 6-10 6S4.2 16 2 12Zm10 3.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" />
                    )}
                  </svg>
                </button>
              </span>
            </label>
            <button
              className="primary-action"
              disabled={busy || !runtimeInfo}
              type="submit"
            >
              {busy
                ? "Please wait..."
                : authMode === "login"
                  ? "Sign in"
                  : "Create account"}
            </button>
          </form>
          <button
            className="auth-switch"
            onClick={() => setAuthMode(authMode === "login" ? "signup" : "login")}
            type="button"
          >
            {authMode === "login"
              ? "New here? Create an account"
              : "Already have an account? Sign in"}
          </button>
          {message && <p className="auth-message">{message}</p>}
        </section>
      </main>
    );
  }

  return (
    <main className="workspace-page">
      <aside className="workspace-sidebar">
        <div className="workspace-logo">CP</div>
        <p className="workspace-name">COPILOT</p>
        {(["dashboard", "resume", "sessions"] as View[]).map((item) => (
          <button
            className={view === item ? "nav-item active" : "nav-item"}
            key={item}
            onClick={() => setView(item)}
            type="button"
          >
            {item}
          </button>
        ))}
        <button
          className="nav-item logout"
          onClick={() => {
            setAccessToken("");
            setRefreshToken("");
            setPassword("");
            setCandidateProfile(null);
            setProfilePrepared(false);
            setSessionStarted(false);
            setLlmConfiguration({ configured: false });
            setLlmApiKey("");
            setLlmMessage("");
            void window.desktopApi.setCandidateProfileContext(null);
          }}
          type="button"
        >
          Sign out
        </button>
      </aside>
      <section className="workspace-main">
        <header className="workspace-header">
          <div>
            <p className="kicker">{view.toUpperCase()}</p>
            <h1>
              {view === "dashboard"
                ? "Your session workspace"
                : view === "resume"
                  ? "Resume profile"
                  : "Session history"}
            </h1>
          </div>
          <span className="status-badge">
            <i /> {backendStatus} -{" "}
            {runtimeInfo
              ? runtimeInfo.environment === "production"
                ? "Cloud"
                : "Local"
              : "Configuring"}
          </span>
        </header>
        {view === "dashboard" && (
          <div className="workspace-grid">
            <section className="ai-model-card">
              <div className="ai-model-heading">
                <div>
                  <p className="kicker">YOUR AI MODEL</p>
                  <h2>Connect a provider</h2>
                  <p>
                    Your key is encrypted by the backend and is never displayed again.
                  </p>
                </div>
                <span
                  className={
                    llmConfiguration.configured ? "model-status active" : "model-status"
                  }
                >
                  {llmConfiguration.configured ? "Active" : "Setup required"}
                </span>
              </div>
              {llmConfiguration.configured && (
                <div className="active-model-summary">
                  <strong>
                    {LLM_PROVIDERS.find(
                      (provider) => provider.value === llmConfiguration.provider,
                    )?.label ?? llmConfiguration.provider}
                  </strong>
                  <span>{llmConfiguration.model}</span>
                  <small>Key {llmConfiguration.maskedHint}</small>
                </div>
              )}
              <div className="ai-model-fields">
                <label>
                  Provider
                  <select
                    className="dashboard-input"
                    disabled={llmBusy}
                    onChange={(event) =>
                      setLlmProvider(event.target.value as LlmProvider)
                    }
                    value={llmProvider}
                  >
                    {LLM_PROVIDERS.map((provider) => (
                      <option key={provider.value} value={provider.value}>
                        {provider.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Model name
                  <input
                    className="dashboard-input"
                    disabled={llmBusy}
                    onChange={(event) => setLlmModel(event.target.value)}
                    placeholder="Enter the provider model ID"
                    value={llmModel}
                  />
                </label>
                <label>
                  API key
                  <span className="password-field model-key-field">
                    <input
                      autoComplete="off"
                      className="dashboard-input"
                      disabled={llmBusy}
                      onChange={(event) => setLlmApiKey(event.target.value)}
                      placeholder={
                        llmConfiguration.configured
                          ? "Enter a new key to replace the current one"
                          : "Enter your provider API key"
                      }
                      type={showLlmApiKey ? "text" : "password"}
                      value={llmApiKey}
                    />
                    <button
                      aria-label={showLlmApiKey ? "Hide API key" : "Show API key"}
                      aria-pressed={showLlmApiKey}
                      className="password-toggle"
                      onClick={() => setShowLlmApiKey((current) => !current)}
                      type="button"
                    >
                      {showLlmApiKey ? "Hide" : "Show"}
                    </button>
                  </span>
                </label>
              </div>
              <div className="model-actions">
                <button
                  className="primary-action"
                  disabled={llmBusy || !llmModel.trim() || !llmApiKey.trim()}
                  onClick={() => void saveLlmConfiguration()}
                  type="button"
                >
                  {llmBusy ? "Validating..." : "Validate and save"}
                </button>
                {llmConfiguration.configured && (
                  <button
                    className="model-remove-action"
                    disabled={llmBusy}
                    onClick={() => void removeLlmConfiguration()}
                    type="button"
                  >
                    Remove
                  </button>
                )}
              </div>
              {llmMessage && <p className="model-message">{llmMessage}</p>}
            </section>{" "}
            <section className="hero-card">
              <p className="kicker">NEW SESSION</p>
              <h2>Ready when you are.</h2>
              <p>
                Bring your resume and role context together before starting the visible
                Copilot overlay.
              </p>
              <div className="feature-row">
                <span>Profile-aware</span>
                <span>Consent-first</span>
                <span>Streaming</span>
              </div>
            </section>
            <section className="setup-card">
              <h2>Set up a session</h2>
              <label className="field-label">
                Resume
                {candidateProfile ? (
                  <small>Optional replacement - PDF only</small>
                ) : (
                  <small>Required - PDF only</small>
                )}
              </label>
              <label className="resume-drop">
                <input accept="application/pdf" onChange={onResumeChange} type="file" />
                <strong>
                  {resume?.name ??
                    (candidateProfile
                      ? "Saved resume profile is ready"
                      : "Choose your resume")}
                </strong>
                <span>
                  {resume
                    ? `${Math.round(resume.size / 1024)} KB selected`
                    : candidateProfile
                      ? "Choose a new PDF only when you want to replace it"
                      : "Browse for a PDF file"}
                </span>
              </label>
              <label className="field-label">Job role</label>
              <input
                className="dashboard-input"
                onChange={(event) => setJobRole(event.target.value)}
                placeholder="AI Engineer"
                value={jobRole}
              />
              <label className="field-label">Company</label>
              <input
                className="dashboard-input"
                onChange={(event) => setCompany(event.target.value)}
                placeholder="Company name"
                value={company}
              />
              <label className="field-label">Experience</label>
              <select
                className="dashboard-input"
                onChange={(event) => setExperienceLevel(event.target.value)}
                value={experienceLevel}
              >
                <option value="">Select experience</option>
                {EXPERIENCE_LEVELS.map((level) => (
                  <option key={level} value={level}>
                    {level}
                  </option>
                ))}
              </select>
              <button
                className="primary-action"
                disabled={
                  busy ||
                  !llmConfiguration.configured ||
                  !resume ||
                  !jobRole.trim() ||
                  !company.trim() ||
                  !experienceLevel
                }
                onClick={() => void startSession()}
                type="button"
              >
                {busy
                  ? "Preparing..."
                  : candidateProfile
                    ? "Update profile"
                    : "Start session"}
              </button>
              <button
                className="secondary-action"
                disabled={!llmConfiguration.configured || !profilePrepared || busy}
                onClick={() => void openOverlay()}
                type="button"
              >
                {sessionStarted ? "Show Overlay" : "Start Overlay"}
              </button>
              {message && <p className="session-message">{message}</p>}
            </section>
            <section className="activity-card">
              <h2>Session checklist</h2>
              <ol>
                <li className={llmConfiguration.configured ? "complete" : ""}>
                  Configure and validate an AI model
                </li>
                <li className={resume || candidateProfile ? "complete" : ""}>
                  {candidateProfile && !resume
                    ? "Saved resume profile loaded"
                    : "Upload a resume"}
                </li>
                <li
                  className={
                    profilePrepared || (jobRole && company && experienceLevel)
                      ? "complete"
                      : ""
                  }
                >
                  {profilePrepared && !resume
                    ? "Saved profile details are ready"
                    : "Add role, company, and experience"}
                </li>
                <li className={sessionStarted ? "complete" : ""}>
                  Start the overlay when ready
                </li>
              </ol>
              <p>Your overlay appears only after the profile is prepared.</p>
            </section>
          </div>
        )}
        {view === "resume" &&
          (candidateProfile ? (
            <ProfileView profile={candidateProfile} />
          ) : (
            <section className="empty-card">
              <h2>No parsed resume yet</h2>
              <p>
                Upload your PDF and select Start session from Dashboard. The parsed
                profile will then appear here in its available sections.
              </p>
            </section>
          ))}
        {view === "sessions" && (
          <section className="empty-card">
            <h2>Session history</h2>
            <p>
              Completed consented sessions will appear here once persistent session
              storage is added.
            </p>
          </section>
        )}
      </section>
    </main>
  );
};
