import { contextBridge, ipcRenderer } from "electron";
import type { DesktopApi, OverlayPreferences } from "../shared/desktopApi";

const api: DesktopApi = {
  getRuntimeInfo: () => ipcRenderer.invoke("app:get-runtime-info"),
  quit: () => ipcRenderer.invoke("app:quit"),
  getBackendStatus: () => ipcRenderer.invoke("backend:get-status"),
  getCandidateProfileReady: () => ipcRenderer.invoke("profile:get-status"),
  startSession: (prompt, includeCandidateProfile) =>
    ipcRenderer.invoke("backend:start-session", prompt, includeCandidateProfile),
  setCandidateProfileContext: (profile) =>
    ipcRenderer.invoke("profile:set-context", profile),
  startSystemAudio: () => ipcRenderer.invoke("system-audio:start"),
  stopSystemAudio: (sessionId) => ipcRenderer.invoke("system-audio:stop", sessionId),
  sendScreenCapture: (image, mimeType) =>
    ipcRenderer.invoke("screen:capture", image, mimeType),
  sendAudioChunk: (sessionId, audio, sampleRateHz) =>
    ipcRenderer.invoke("audio:chunk", sessionId, audio, sampleRateHz),
  startOverlaySession: () => ipcRenderer.invoke("overlay:start-session"),
  showOverlay: () => ipcRenderer.invoke("overlay:show"),
  hideOverlay: () => ipcRenderer.invoke("overlay:hide"),
  setOverlayPreferences: (preferences: OverlayPreferences) =>
    ipcRenderer.invoke("overlay:set-preferences", preferences),
  onBackendStatus: (listener) => {
    const callback = (
      _event: Electron.IpcRendererEvent,
      status: Parameters<typeof listener>[0],
    ) => listener(status);
    ipcRenderer.on("backend:status", callback);
    return () => ipcRenderer.removeListener("backend:status", callback);
  },
  onBackendEvent: (listener) => {
    const callback = (
      _event: Electron.IpcRendererEvent,
      event: Parameters<typeof listener>[0],
    ) => listener(event);
    ipcRenderer.on("backend:event", callback);
    return () => ipcRenderer.removeListener("backend:event", callback);
  },
  onCandidateProfileStatus: (listener) => {
    const callback = (_event: Electron.IpcRendererEvent, ready: boolean) =>
      listener(ready);
    ipcRenderer.on("profile:status", callback);
    return () => ipcRenderer.removeListener("profile:status", callback);
  },
  onOverlayPreferences: (listener) => {
    const callback = (
      _event: Electron.IpcRendererEvent,
      preferences: Parameters<typeof listener>[0],
    ) => listener(preferences);
    ipcRenderer.on("overlay:preferences", callback);
    return () => ipcRenderer.removeListener("overlay:preferences", callback);
  },
};

contextBridge.exposeInMainWorld("desktopApi", api);
