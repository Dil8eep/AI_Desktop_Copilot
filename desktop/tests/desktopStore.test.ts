import { beforeEach, describe, expect, it } from "vitest";
import { useDesktopStore } from "../src/renderer/src/store/desktopStore";

describe("desktop store", () => {
  beforeEach(() => {
    useDesktopStore.setState({ backendStatus: "disconnected" });
  });

  it("keeps the backend state inside the renderer store", () => {
    useDesktopStore.getState().setBackendStatus("mock-ready");
    expect(useDesktopStore.getState().backendStatus).toBe("mock-ready");
  });
});
