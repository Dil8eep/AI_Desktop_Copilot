export type BackendConnectionStatus = "connected" | "connecting" | "disconnected";

export type BackendEvent = Readonly<{
  event: string;
  sessionId: string;
  requestId: string;
  timestamp: string;
  payload: Record<string, unknown>;
}>;

export type OverlayPreferences = Readonly<{
  opacity: number;
  fontSize: number;
}>;

export type RuntimeInfo = Readonly<{
  platform: string;
  version: string;
  environment: "development" | "production";
  apiBaseUrl: string;
  websocketUrl: string;
}>;
export type CandidateProfileContext = Readonly<Record<string, unknown>>;

export type DesktopApi = Readonly<{
  getRuntimeInfo: () => Promise<RuntimeInfo>;
  quit: () => Promise<void>;
  getBackendStatus: () => Promise<BackendConnectionStatus>;
  getCandidateProfileReady: () => Promise<boolean>;
  setAccessToken: (accessToken: string | null) => Promise<void>;
  startSession: (prompt: string, includeCandidateProfile?: boolean) => Promise<string>;
  setCandidateProfileContext: (
    profile: CandidateProfileContext | null,
  ) => Promise<void>;
  startSystemAudio: () => Promise<string>;
  stopSystemAudio: (sessionId: string) => Promise<void>;
  sendScreenCapture: (image: Uint8Array, mimeType: string) => Promise<string>;
  sendAudioChunk: (
    sessionId: string,
    audio: Uint8Array,
    sampleRateHz: number,
  ) => Promise<boolean>;
  startOverlaySession: () => Promise<void>;
  showOverlay: () => Promise<void>;
  hideOverlay: () => Promise<void>;
  setOverlayPreferences: (preferences: OverlayPreferences) => Promise<void>;
  onBackendStatus: (listener: (status: BackendConnectionStatus) => void) => () => void;
  onBackendEvent: (listener: (event: BackendEvent) => void) => () => void;
  onCandidateProfileStatus: (listener: (ready: boolean) => void) => () => void;
  onOverlayPreferences: (
    listener: (preferences: OverlayPreferences) => void,
  ) => () => void;
}>;
