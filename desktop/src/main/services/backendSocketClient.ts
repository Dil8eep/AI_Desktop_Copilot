import { randomUUID } from "node:crypto";
import WebSocket, { type RawData } from "ws";
import type {
  BackendConnectionStatus,
  BackendEvent,
  CandidateProfileContext,
} from "../../shared/desktopApi";

type Listener<T> = (value: T) => void;

type BackendSocketOptions = Readonly<{
  url: string;
  localToken?: string;
  reconnectDelayMs: number;
}>;

const isBackendEvent = (value: unknown): value is BackendEvent => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const event = value as Record<string, unknown>;
  return (
    typeof event.event === "string" &&
    typeof event.sessionId === "string" &&
    typeof event.requestId === "string" &&
    typeof event.timestamp === "string" &&
    typeof event.payload === "object" &&
    event.payload !== null
  );
};

/** Owns the reconnecting local-backend connection in the Electron main process. */
export class BackendSocketClient {
  private socket: WebSocket | undefined;
  private reconnectTimer: NodeJS.Timeout | undefined;
  private reconnectEnabled = false;
  private accessToken: string | undefined;
  private authenticationRejected = false;
  private latestScreenText = "";
  private candidateProfile: CandidateProfileContext | undefined;
  private status: BackendConnectionStatus = "disconnected";
  private readonly statusListeners = new Set<Listener<BackendConnectionStatus>>();
  private readonly eventListeners = new Set<Listener<BackendEvent>>();

  public constructor(private readonly options: BackendSocketOptions) {}

  public start(): void {
    this.reconnectEnabled = true;
    this.connect();
  }

  public shutdown(): void {
    this.reconnectEnabled = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
    this.socket?.close();
    this.socket = undefined;
    this.publishStatus("disconnected");
  }

  public setAccessToken(accessToken: string | null): void {
    const normalized = accessToken?.trim() || undefined;
    if (this.accessToken === normalized) {
      return;
    }
    this.accessToken = normalized;
    this.authenticationRejected = false;
    if (this.socket) {
      this.socket.close();
      return;
    }
    if (this.reconnectEnabled) {
      this.connect();
    }
  }
  public getStatus(): BackendConnectionStatus {
    return this.status;
  }

  public onStatus(listener: Listener<BackendConnectionStatus>): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  public onEvent(listener: Listener<BackendEvent>): () => void {
    this.eventListeners.add(listener);
    return () => this.eventListeners.delete(listener);
  }

  public startSession(prompt: string, includeCandidateProfile = false): string {
    const normalizedPrompt = prompt.trim();
    if (!normalizedPrompt) {
      throw new Error("A prompt is required to start a session.");
    }
    if (this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error("The configured backend is not connected.");
    }

    const sessionId = randomUUID();
    this.socket.send(
      JSON.stringify({
        version: "1.0",
        event: "session.start",
        sessionId,
        requestId: randomUUID(),
        timestamp: new Date().toISOString(),
        payload: {
          prompt: normalizedPrompt,
          screenText: this.latestScreenText,
          includeCandidateProfile,
          ...(includeCandidateProfile && this.candidateProfile
            ? { candidateProfile: this.candidateProfile }
            : {}),
        },
      }),
    );
    return sessionId;
  }

  /** Keep the prepared profile in memory only for user-requested prompt context. */
  public setCandidateProfile(profile: CandidateProfileContext | null): void {
    this.candidateProfile = profile ?? undefined;
  }

  public hasCandidateProfile(): boolean {
    return this.candidateProfile !== undefined;
  }

  public sendScreenText(text: string): string {
    const normalized = text.trim();
    if (!normalized) {
      throw new Error("Screen text is required.");
    }
    if (normalized.length > 12_000) {
      throw new Error("Screen text exceeds the 12,000 character limit.");
    }
    const sessionId = randomUUID();
    this.sendJsonEvent("screen.text", sessionId, { text: normalized });
    return sessionId;
  }

  public sendAudioChunk(
    sessionId: string,
    audio: Uint8Array,
    sampleRateHz: number,
    source: "microphone" | "system-audio" = "microphone",
  ): boolean {
    if (!Number.isInteger(sampleRateHz) || sampleRateHz !== 16_000) {
      throw new Error("Audio must be 16 kHz PCM.");
    }
    if (this.socket?.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.sendBinaryEvent("audio.chunk", sessionId, audio, {
      mimeType: "audio/pcm;codec=s16le",
      sampleRateHz,
      source,
    });
    return true;
  }
  private sendJsonEvent(
    event: "screen.text",
    sessionId: string,
    payload: Record<string, unknown>,
  ): void {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error("The configured backend is not connected.");
    }
    this.socket.send(
      JSON.stringify({
        version: "1.0",
        event,
        sessionId,
        requestId: randomUUID(),
        timestamp: new Date().toISOString(),
        payload,
      }),
    );
  }

  private sendBinaryEvent(
    event: "audio.chunk",
    sessionId: string,
    data: Uint8Array,
    payload: Record<string, string | number>,
  ): void {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      throw new Error("The configured backend is not connected.");
    }
    this.socket.send(
      JSON.stringify({
        version: "1.0",
        event,
        sessionId,
        requestId: randomUUID(),
        timestamp: new Date().toISOString(),
        payload: { ...payload, byteLength: data.byteLength },
      }),
    );
    this.socket.send(data);
  }
  private connect(): void {
    if (
      !this.reconnectEnabled ||
      !this.accessToken ||
      this.authenticationRejected ||
      this.socket
    ) {
      return;
    }
    this.publishStatus("connecting");
    const socket = new WebSocket(this.options.url, {
      headers: {
        ...(this.options.localToken
          ? { "x-copilot-token": this.options.localToken }
          : {}),
        ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}),
      },
    });
    this.socket = socket;

    socket.on("unexpected-response", (_request, response) => {
      if (response.statusCode === 401 || response.statusCode === 403) {
        this.authenticationRejected = true;
      }
      response.resume();
    });

    socket.on("open", () => {
      if (this.socket === socket) {
        this.publishStatus("connected");
      }
    });
    socket.on("message", (data: RawData) => this.handleMessage(data));
    socket.on("error", (error) => {
      if (/Unexpected server response: (401|403)/.test(error.message)) {
        this.authenticationRejected = true;
      }
      this.publishStatus("disconnected");
    });
    socket.on("close", () => {
      if (this.socket !== socket) {
        return;
      }
      this.socket = undefined;
      this.publishStatus("disconnected");
      if (!this.authenticationRejected) {
        this.scheduleReconnect();
      }
    });
  }

  private handleMessage(data: RawData): void {
    try {
      const parsed: unknown = JSON.parse(data.toString());
      if (isBackendEvent(parsed)) {
        if (parsed.event === "context.updated") {
          const screenText = parsed.payload.screenText;
          if (typeof screenText === "string") {
            this.latestScreenText = screenText;
          }
        }
        for (const listener of this.eventListeners) {
          listener(parsed);
        }
      }
    } catch {
      // The backend owns protocol errors; malformed frames are ignored safely.
    }
  }

  private scheduleReconnect(): void {
    if (!this.reconnectEnabled || this.reconnectTimer) {
      return;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, this.options.reconnectDelayMs);
  }

  private publishStatus(status: BackendConnectionStatus): void {
    if (this.status === status) {
      return;
    }
    this.status = status;
    for (const listener of this.statusListeners) {
      listener(status);
    }
  }
}
