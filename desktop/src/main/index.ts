import {
  app,
  BrowserWindow,
  desktopCapturer,
  globalShortcut,
  ipcMain,
  Menu,
  nativeImage,
  Tray,
} from "electron";
import path from "node:path";
import type {
  BackendConnectionStatus,
  BackendEvent,
  CandidateProfileContext,
  OverlayPreferences,
} from "../shared/desktopApi";
import { BackendSocketClient } from "./services/backendSocketClient";

const overlayDefaults: OverlayPreferences = { opacity: 0.92, fontSize: 16 };

type AppWindows = Readonly<{
  settings: BrowserWindow;
  overlay: BrowserWindow;
}>;

const getRendererUrl = (): string | undefined => process.env.COPILOT_RENDERER_URL;

const loadRendererPage = async (
  window: BrowserWindow,
  page: "index.html" | "overlay.html",
): Promise<void> => {
  const rendererUrl = getRendererUrl();
  if (rendererUrl) {
    await window.loadURL(new URL(page, rendererUrl).toString());
    return;
  }
  await window.loadFile(path.join(__dirname, "../../renderer", page));
};

const isTrustedRendererOrigin = (origin: string): boolean => {
  const rendererUrl = getRendererUrl();
  return (
    origin.startsWith("file://") ||
    Boolean(rendererUrl && origin.startsWith(rendererUrl))
  );
};

const configureDisplayMediaCapture = (window: BrowserWindow): void => {
  window.webContents.session.setDisplayMediaRequestHandler(
    async (request, callback) => {
      if (!isTrustedRendererOrigin(request.securityOrigin)) {
        callback({});
        return;
      }
      try {
        const sources = await desktopCapturer.getSources({
          types: ["screen"],
          thumbnailSize: { width: 320, height: 180 },
        });
        const source = sources[0];
        callback(source ? { video: source } : {});
      } catch {
        callback({});
      }
    },
  );
};
const configureCapturePermissions = (window: BrowserWindow): void => {
  const session = window.webContents.session;
  session.setPermissionCheckHandler((_contents, permission, requestingOrigin) => {
    const permissionName = permission as string;
    const isCapturePermission =
      permissionName === "media" || permissionName === "display-capture";
    return isCapturePermission && isTrustedRendererOrigin(requestingOrigin);
  });
  session.setPermissionRequestHandler((contents, permission, callback, details) => {
    const isCapturePermission =
      permission === "media" || permission === "display-capture";
    const origin = details.requestingUrl || contents.getURL();
    callback(isCapturePermission && isTrustedRendererOrigin(origin));
  });
};

const createWindows = (): AppWindows => {
  const preload = path.join(__dirname, "../preload/index.js");
  const settings = new BrowserWindow({
    width: 1040,
    height: 760,
    minWidth: 840,
    minHeight: 560,
    show: false,
    title: "AI Desktop Copilot",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload,
    },
  });
  const overlay = new BrowserWindow({
    width: 560,
    height: 300,
    minWidth: 360,
    minHeight: 180,
    show: false,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: true,
    movable: true,
    skipTaskbar: true,
    backgroundColor: "#00000000",
    title: "AI Desktop Copilot Overlay",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload,
    },
  });
  overlay.setAlwaysOnTop(true, "screen-saver");
  // Windows 10 version 2004+ capture APIs omit this privacy-sensitive window.
  overlay.setContentProtection(true);
  overlay.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  settings.once("ready-to-show", () => settings.show());
  return { settings, overlay };
};

const loadWindows = async (windows: AppWindows): Promise<void> => {
  configureCapturePermissions(windows.settings);
  configureCapturePermissions(windows.overlay);
  configureDisplayMediaCapture(windows.overlay);
  await Promise.all([
    loadRendererPage(windows.settings, "index.html"),
    loadRendererPage(windows.overlay, "overlay.html"),
  ]);
};

class DesktopRuntime {
  private overlayPreferences: OverlayPreferences = overlayDefaults;
  private sessionPrepared = false;

  public constructor(
    private readonly backend: BackendSocketClient,
    private readonly windows: AppWindows,
  ) {}

  public start(): void {
    this.backend.onStatus((status) => this.publish("backend:status", status));
    this.backend.onEvent((event) => {
      if (event.event === "llm.token") {
        this.showOverlay();
      }
      this.publish("backend:event", event);
    });
    this.applyOverlayPreferences(this.overlayPreferences);
    this.backend.start();
  }

  public shutdown(): void {
    this.backend.shutdown();
  }

  public getBackendStatus(): BackendConnectionStatus {
    return this.backend.getStatus();
  }

  public getCandidateProfileReady(): boolean {
    return this.backend.hasCandidateProfile();
  }

  public startSession(prompt: string, includeCandidateProfile = false): string {
    this.showOverlay();
    return this.backend.startSession(prompt, includeCandidateProfile);
  }

  public setCandidateProfileContext(profile: CandidateProfileContext | null): void {
    this.backend.setCandidateProfile(profile);
    if (profile === null) {
      this.sessionPrepared = false;
      this.hideOverlay();
    }
    this.publish("profile:status", this.backend.hasCandidateProfile());
  }

  public startPreparedOverlaySession(): void {
    if (!this.backend.hasCandidateProfile()) {
      throw new Error("Prepare the candidate profile before starting a session.");
    }
    this.sessionPrepared = true;
    this.showOverlay();
  }

  public startSystemAudio(): string {
    this.showOverlay();
    return this.backend.startSystemAudio();
  }

  public stopSystemAudio(sessionId: string): void {
    this.backend.stopSystemAudio(sessionId);
  }
  public sendScreenCapture(image: Uint8Array, mimeType: string): string {
    this.showOverlay();
    return this.backend.sendScreenCapture(image, mimeType);
  }

  public sendAudioChunk(
    sessionId: string,
    audio: Uint8Array,
    sampleRateHz: number,
  ): boolean {
    return this.backend.sendAudioChunk(sessionId, audio, sampleRateHz);
  }
  public showSettings(): void {
    this.windows.settings.show();
    this.windows.settings.focus();
  }

  public showOverlay(): void {
    if (this.sessionPrepared) {
      this.windows.overlay.showInactive();
    }
  }

  public hideOverlay(): void {
    this.windows.overlay.hide();
  }

  public toggleOverlay(): void {
    if (this.windows.overlay.isVisible()) {
      this.hideOverlay();
      return;
    }
    this.showOverlay();
  }

  public setOverlayPreferences(preferences: OverlayPreferences): void {
    if (
      !Number.isFinite(preferences.opacity) ||
      !Number.isFinite(preferences.fontSize) ||
      preferences.opacity < 0.3 ||
      preferences.opacity > 1 ||
      preferences.fontSize < 12 ||
      preferences.fontSize > 24
    ) {
      throw new Error("Invalid overlay preferences.");
    }
    this.overlayPreferences = preferences;
    this.applyOverlayPreferences(preferences);
  }

  private applyOverlayPreferences(preferences: OverlayPreferences): void {
    this.windows.overlay.setOpacity(preferences.opacity);
    this.publish("overlay:preferences", preferences);
  }

  private publish(
    channel:
      "backend:status" | "backend:event" | "overlay:preferences" | "profile:status",
    value: BackendConnectionStatus | BackendEvent | OverlayPreferences | boolean,
  ): void {
    for (const window of [this.windows.settings, this.windows.overlay]) {
      if (!window.isDestroyed()) {
        window.webContents.send(channel, value);
      }
    }
  }
}

const registerIpc = (runtime: DesktopRuntime): void => {
  ipcMain.handle("app:quit", () => app.quit());
  ipcMain.handle("app:get-runtime-info", () => ({
    platform: process.platform,
    version: app.getVersion(),
  }));
  ipcMain.handle("backend:get-status", () => runtime.getBackendStatus());
  ipcMain.handle("profile:get-status", () => runtime.getCandidateProfileReady());
  ipcMain.handle(
    "backend:start-session",
    (_event, prompt: unknown, includeCandidateProfile: unknown) => {
      if (typeof prompt !== "string") {
        throw new Error("The session prompt must be text.");
      }
      if (
        includeCandidateProfile !== undefined &&
        typeof includeCandidateProfile !== "boolean"
      ) {
        throw new Error("The profile-context flag must be true or false.");
      }
      return runtime.startSession(prompt, includeCandidateProfile === true);
    },
  );
  ipcMain.handle("profile:set-context", (_event, profile: unknown) => {
    if (profile !== null && (typeof profile !== "object" || Array.isArray(profile))) {
      throw new Error("Candidate profile context must be an object or null.");
    }
    runtime.setCandidateProfileContext(profile as CandidateProfileContext | null);
  });
  ipcMain.handle("system-audio:start", () => runtime.startSystemAudio());
  ipcMain.handle("system-audio:stop", (_event, sessionId: unknown) => {
    if (typeof sessionId !== "string") {
      throw new Error("The system-audio session id must be text.");
    }
    runtime.stopSystemAudio(sessionId);
  });
  ipcMain.handle("screen:capture", (_event, image: Uint8Array, mimeType: unknown) => {
    if (!(image instanceof Uint8Array) || typeof mimeType !== "string") {
      throw new Error("Screen capture data is invalid.");
    }
    return runtime.sendScreenCapture(image, mimeType);
  });
  ipcMain.handle(
    "audio:chunk",
    (_event, sessionId: unknown, audio: Uint8Array, sampleRateHz: unknown) => {
      if (
        typeof sessionId !== "string" ||
        !(audio instanceof Uint8Array) ||
        typeof sampleRateHz !== "number"
      ) {
        throw new Error("Audio chunk data is invalid.");
      }
      return runtime.sendAudioChunk(sessionId, audio, sampleRateHz);
    },
  );
  ipcMain.handle("overlay:start-session", () => runtime.startPreparedOverlaySession());
  ipcMain.handle("overlay:show", () => runtime.showOverlay());
  ipcMain.handle("overlay:hide", () => runtime.hideOverlay());
  ipcMain.handle("overlay:set-preferences", (_event, preferences: unknown) => {
    if (
      typeof preferences !== "object" ||
      preferences === null ||
      typeof (preferences as OverlayPreferences).opacity !== "number" ||
      typeof (preferences as OverlayPreferences).fontSize !== "number"
    ) {
      throw new Error("Overlay preferences must contain numeric values.");
    }
    runtime.setOverlayPreferences(preferences as OverlayPreferences);
  });
};

const createTray = (runtime: DesktopRuntime): Tray => {
  const iconSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16"><rect width="16" height="16" rx="4" fill="#22d3ee"/><path d="M4 4h8v2H4zm0 3h6v2H4zm0 3h8v2H4z" fill="#082f49"/></svg>`;
  const icon = nativeImage.createFromDataURL(
    `data:image/svg+xml;base64,${Buffer.from(iconSvg).toString("base64")}`,
  );
  const tray = new Tray(icon);
  tray.setToolTip("AI Desktop Copilot");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Show Control Center", click: () => runtime.showSettings() },
      { label: "Show Overlay", click: () => runtime.showOverlay() },
      { type: "separator" },
      { label: "Quit", click: () => app.quit() },
    ]),
  );
  tray.on("click", () => runtime.toggleOverlay());
  return tray;
};

const bootstrap = async (): Promise<void> => {
  const windows = createWindows();
  const backend = new BackendSocketClient({
    url: process.env.COPILOT_BACKEND_URL ?? "ws://127.0.0.1:8765/ws",
    localToken: process.env.COPILOT_LOCAL_AUTH_TOKEN ?? "development-only-token",
    reconnectDelayMs: 1_500,
  });
  const runtime = new DesktopRuntime(backend, windows);
  registerIpc(runtime);
  await loadWindows(windows);
  const tray = createTray(runtime);
  runtime.start();

  let isQuitting = false;
  windows.settings.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      windows.settings.hide();
    }
  });
  app.on("before-quit", () => {
    isQuitting = true;
    tray.destroy();
    runtime.shutdown();
    globalShortcut.unregisterAll();
  });
  globalShortcut.register("CommandOrControl+Shift+Space", () =>
    runtime.toggleOverlay(),
  );
  app.on("activate", () => windows.settings.show());
};

app
  .whenReady()
  .then(bootstrap)
  .catch((error: unknown) => {
    console.error("Desktop startup failed", error);
    app.quit();
  });
