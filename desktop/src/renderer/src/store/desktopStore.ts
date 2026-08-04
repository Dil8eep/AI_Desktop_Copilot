import { create } from "zustand";

type DesktopState = {
  backendStatus: "disconnected" | "connecting" | "mock-ready";
  setBackendStatus: (status: DesktopState["backendStatus"]) => void;
};

export const useDesktopStore = create<DesktopState>((set) => ({
  backendStatus: "disconnected",
  setBackendStatus: (backendStatus) => set({ backendStatus }),
}));
