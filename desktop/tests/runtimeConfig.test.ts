import { describe, expect, it } from "vitest";
import { resolveDesktopRuntimeConfig } from "../src/main/runtimeConfig";

describe("desktop runtime configuration", () => {
  it("uses localhost development endpoints by default", () => {
    expect(resolveDesktopRuntimeConfig({}, false)).toEqual({
      environment: "development",
      apiBaseUrl: "http://127.0.0.1:8765",
      websocketUrl: "ws://127.0.0.1:8765/ws",
    });
  });

  it("uses the hosted Render endpoint in a package without environment variables", () => {
    expect(resolveDesktopRuntimeConfig({}, true)).toEqual({
      environment: "production",
      apiBaseUrl: "https://ai-desktop-copilot-api.onrender.com",
      websocketUrl: "wss://ai-desktop-copilot-api.onrender.com/ws",
    });
  });

  it("derives a secure Render WebSocket endpoint", () => {
    expect(
      resolveDesktopRuntimeConfig(
        {
          COPILOT_DESKTOP_ENVIRONMENT: "production",
          COPILOT_API_BASE_URL: "https://copilot-api.onrender.com/",
        },
        true,
      ),
    ).toEqual({
      environment: "production",
      apiBaseUrl: "https://copilot-api.onrender.com",
      websocketUrl: "wss://copilot-api.onrender.com/ws",
    });
  });

  it("rejects insecure production endpoints", () => {
    expect(() =>
      resolveDesktopRuntimeConfig(
        {
          COPILOT_DESKTOP_ENVIRONMENT: "production",
          COPILOT_API_BASE_URL: "http://copilot-api.example.com",
          COPILOT_WS_URL: "ws://copilot-api.example.com/ws",
        },
        true,
      ),
    ).toThrow("must use HTTPS");
  });

  it("rejects credentials and unexpected paths", () => {
    expect(() =>
      resolveDesktopRuntimeConfig(
        { COPILOT_API_BASE_URL: "https://user:secret@example.com" },
        false,
      ),
    ).toThrow("must not contain embedded credentials");
    expect(() =>
      resolveDesktopRuntimeConfig(
        { COPILOT_WS_URL: "wss://example.com/private/ws" },
        false,
      ),
    ).toThrow("must use the /ws path");
  });
});
