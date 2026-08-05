import { randomUUID } from "node:crypto";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_OUTPUT_LINE_BYTES = 128 * 1024;
const MAX_AUDIO_CHUNK_BYTES = 64 * 1024;
const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;
const OCR_REQUEST_TIMEOUT_MS = 60_000;

export type LocalHelperLaunchOptions = Readonly<{
  command: string;
  args: readonly string[];
  cwd?: string;
  environment?: NodeJS.ProcessEnv;
  startupTimeoutMs?: number;
}>;

export type LocalHelperMessage = Readonly<{
  version: "1.0";
  id: string | null;
  event: string;
  payload: Record<string, unknown>;
}>;

type PendingRequest = Readonly<{
  successEvent: string;
  resolve: (payload: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}>;

type AudioChunkListener = (
  sessionId: string,
  audio: Uint8Array,
  sampleRateHz: number,
) => void;

type HelperEventListener = (event: LocalHelperMessage) => void;

const isHelperMessage = (value: unknown): value is LocalHelperMessage => {
  if (typeof value !== "object" || value === null) return false;
  const message = value as Record<string, unknown>;
  return (
    message.version === "1.0" &&
    (typeof message.id === "string" || message.id === null) &&
    typeof message.event === "string" &&
    typeof message.payload === "object" &&
    message.payload !== null &&
    !Array.isArray(message.payload)
  );
};

/** Supervises the credential-free local OCR and WASAPI child process. */
export class LocalCaptureHelperClient {
  private child: ChildProcessWithoutNullStreams | undefined;
  private startPromise: Promise<void> | undefined;
  private readyResolve: (() => void) | undefined;
  private readyReject: ((error: Error) => void) | undefined;
  private readyTimer: NodeJS.Timeout | undefined;
  private outputBuffer = Buffer.alloc(0);
  private activeAudioSessionId: string | undefined;
  private shuttingDown = false;
  private readonly pending = new Map<string, PendingRequest>();

  public constructor(
    private readonly launch: LocalHelperLaunchOptions,
    private readonly onAudioChunk: AudioChunkListener,
    private readonly onHelperEvent: HelperEventListener = () => undefined,
  ) {}

  public start(): Promise<void> {
    if (this.startPromise) return this.startPromise;
    this.shuttingDown = false;
    this.startPromise = new Promise<void>((resolve, reject) => {
      this.readyResolve = resolve;
      this.readyReject = reject;
      this.readyTimer = setTimeout(
        () => this.fail(new Error("The local capture helper did not become ready.")),
        this.launch.startupTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS,
      );
      try {
        const child = spawn(this.launch.command, [...this.launch.args], {
          cwd: this.launch.cwd,
          env: this.launch.environment,
          stdio: ["pipe", "pipe", "pipe"],
          windowsHide: true,
        });
        this.child = child;
        child.stdout.on("data", (chunk: Buffer) => this.consumeOutput(chunk));
        child.stderr.on("data", () => undefined);
        child.on("error", () =>
          this.fail(new Error("The local capture helper could not be started.")),
        );
        child.on("exit", () => {
          if (!this.shuttingDown) {
            this.fail(new Error("The local capture helper stopped unexpectedly."));
          }
          this.resetProcess();
        });
      } catch {
        this.fail(new Error("The local capture helper could not be started."));
      }
    });
    return this.startPromise;
  }

  public async analyzeScreen(
    image: Uint8Array,
    mimeType: "image/jpeg" | "image/png",
  ): Promise<string> {
    if (image.byteLength === 0 || image.byteLength > MAX_IMAGE_BYTES) {
      throw new Error("Screen capture must be between 1 byte and 10 MiB.");
    }
    await this.start();
    const payload = await this.request(
      "ocr.analyze",
      { mimeType, imageBase64: Buffer.from(image).toString("base64") },
      "ocr.result",
      OCR_REQUEST_TIMEOUT_MS,
    );
    if (typeof payload.text !== "string" || !payload.text.trim()) {
      throw new Error("No readable text was detected on the selected screen.");
    }
    return payload.text;
  }

  public async startSystemAudio(): Promise<string> {
    if (this.activeAudioSessionId) {
      throw new Error("System audio capture is already active.");
    }
    await this.start();
    const sessionId = randomUUID();
    this.activeAudioSessionId = sessionId;
    try {
      await this.request(
        "audio.start",
        {},
        "audio.started",
        DEFAULT_REQUEST_TIMEOUT_MS,
        sessionId,
      );
      return sessionId;
    } catch (error) {
      this.activeAudioSessionId = undefined;
      throw error;
    }
  }

  public async stopSystemAudio(sessionId: string): Promise<void> {
    if (!this.activeAudioSessionId || this.activeAudioSessionId !== sessionId) {
      throw new Error("System audio capture is not active for this session.");
    }
    await this.request("audio.stop", {}, "audio.stopped");
    this.activeAudioSessionId = undefined;
  }

  public async shutdown(): Promise<void> {
    if (!this.child) return;
    this.shuttingDown = true;
    try {
      await this.request("shutdown", {}, "helper.stopped", 2_000);
    } catch {
      this.child?.kill();
    } finally {
      this.resetProcess();
    }
  }

  private request(
    command: string,
    payload: Record<string, unknown>,
    successEvent: string,
    timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
    requestId = randomUUID(),
  ): Promise<Record<string, unknown>> {
    const child = this.child;
    if (!child || child.stdin.destroyed) {
      return Promise.reject(new Error("The local capture helper is unavailable."));
    }
    return new Promise<Record<string, unknown>>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error("The local capture helper request timed out."));
      }, timeoutMs);
      this.pending.set(requestId, { successEvent, resolve, reject, timer });
      const line = `${JSON.stringify({
        version: "1.0",
        id: requestId,
        command,
        payload,
      })}\n`;
      child.stdin.write(line, "utf8", (error) => {
        if (!error) return;
        const pending = this.pending.get(requestId);
        if (!pending) return;
        clearTimeout(pending.timer);
        this.pending.delete(requestId);
        pending.reject(new Error("The local capture helper request failed."));
      });
    });
  }

  private consumeOutput(chunk: Buffer): void {
    this.outputBuffer = Buffer.concat([this.outputBuffer, chunk]);
    if (this.outputBuffer.byteLength > MAX_OUTPUT_LINE_BYTES * 2) {
      this.fail(new Error("The local capture helper returned an invalid response."));
      return;
    }
    let newline = this.outputBuffer.indexOf(0x0a);
    while (newline >= 0) {
      const line = this.outputBuffer.subarray(0, newline);
      this.outputBuffer = this.outputBuffer.subarray(newline + 1);
      if (line.byteLength > MAX_OUTPUT_LINE_BYTES) {
        this.fail(new Error("The local capture helper returned an invalid response."));
        return;
      }
      this.handleLine(line);
      newline = this.outputBuffer.indexOf(0x0a);
    }
  }

  private handleLine(line: Buffer): void {
    try {
      const parsed: unknown = JSON.parse(line.toString("utf8"));
      if (!isHelperMessage(parsed)) throw new Error("invalid helper message");
      this.handleMessage(parsed);
    } catch {
      this.fail(new Error("The local capture helper returned an invalid response."));
    }
  }

  private handleMessage(message: LocalHelperMessage): void {
    if (message.event === "helper.ready" && message.id === null) {
      if (this.readyTimer) clearTimeout(this.readyTimer);
      this.readyTimer = undefined;
      this.readyResolve?.();
      this.readyResolve = undefined;
      this.readyReject = undefined;
      this.onHelperEvent(message);
      return;
    }
    if (message.event === "audio.chunk") {
      this.handleAudioChunk(message);
      return;
    }
    if (message.event === "audio.stopped" && message.id === this.activeAudioSessionId) {
      this.activeAudioSessionId = undefined;
    }
    const pending = message.id ? this.pending.get(message.id) : undefined;
    if (pending) {
      if (message.event === "helper.error") {
        clearTimeout(pending.timer);
        this.pending.delete(message.id as string);
        pending.reject(this.safeHelperError(message.payload.code));
        return;
      }
      if (message.event === pending.successEvent) {
        clearTimeout(pending.timer);
        this.pending.delete(message.id as string);
        pending.resolve(message.payload);
        return;
      }
    }
    this.onHelperEvent(message);
  }

  private handleAudioChunk(message: LocalHelperMessage): void {
    if (message.id !== this.activeAudioSessionId) return;
    const encoded = message.payload.audioBase64;
    const byteLength = message.payload.byteLength;
    const sampleRateHz = message.payload.sampleRateHz;
    if (
      typeof encoded !== "string" ||
      typeof byteLength !== "number" ||
      byteLength < 1 ||
      byteLength > MAX_AUDIO_CHUNK_BYTES ||
      sampleRateHz !== 16_000
    ) {
      this.fail(new Error("The local capture helper returned invalid audio."));
      return;
    }
    const audio = Buffer.from(encoded, "base64");
    if (audio.byteLength !== byteLength) {
      this.fail(new Error("The local capture helper returned invalid audio."));
      return;
    }
    this.onAudioChunk(message.id, audio, sampleRateHz);
  }

  private safeHelperError(code: unknown): Error {
    const messages: Record<string, string> = {
      invalid_ocr_request: "The selected screen image is invalid.",
      ocr_unavailable: "Local screen text recognition is unavailable.",
      system_audio_already_active: "System audio capture is already active.",
      system_audio_not_active: "System audio capture is not active.",
      system_audio_loopback_not_found: "No Windows speaker-output device was found.",
      system_audio_invalid_device_format: "The speaker-output format is unsupported.",
      system_audio_windows_only: "System audio capture requires Windows.",
      system_audio_unavailable: "System audio capture is unavailable.",
    };
    return new Error(
      typeof code === "string" && messages[code]
        ? messages[code]
        : "The local capture helper rejected the request.",
    );
  }

  private fail(error: Error): void {
    if (this.readyTimer) clearTimeout(this.readyTimer);
    this.readyTimer = undefined;
    this.readyReject?.(error);
    this.readyResolve = undefined;
    this.readyReject = undefined;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
    this.child?.kill();
    this.resetProcess();
  }

  private resetProcess(): void {
    this.child = undefined;
    this.startPromise = undefined;
    this.outputBuffer = Buffer.alloc(0);
    this.activeAudioSessionId = undefined;
  }
}
