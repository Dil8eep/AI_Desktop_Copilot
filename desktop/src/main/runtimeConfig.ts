/** Validated desktop endpoints shared by HTTP and WebSocket clients. */

export type DesktopEnvironment = "development" | "production";

export type DesktopRuntimeConfig = Readonly<{
  environment: DesktopEnvironment;
  apiBaseUrl: string;
  websocketUrl: string;
}>;

const LOCAL_API_URL = "http://127.0.0.1:8765";

const parseEnvironment = (
  value: string | undefined,
  packaged: boolean,
): DesktopEnvironment => {
  const normalized = value?.trim().toLowerCase();
  if (!normalized) return packaged ? "production" : "development";
  if (normalized === "development" || normalized === "production") {
    return normalized;
  }
  throw new Error("COPILOT_DESKTOP_ENVIRONMENT must be development or production.");
};

const parseEndpoint = (
  rawValue: string,
  allowedProtocols: ReadonlySet<string>,
  variableName: string,
): URL => {
  let endpoint: URL;
  try {
    endpoint = new URL(rawValue.trim());
  } catch {
    throw new Error(`${variableName} must be an absolute URL.`);
  }
  if (!allowedProtocols.has(endpoint.protocol)) {
    throw new Error(`${variableName} uses an unsupported protocol.`);
  }
  if (endpoint.username || endpoint.password) {
    throw new Error(`${variableName} must not contain embedded credentials.`);
  }
  if (endpoint.search || endpoint.hash) {
    throw new Error(`${variableName} must not contain a query string or fragment.`);
  }
  return endpoint;
};

const normalizeApiUrl = (rawValue: string): string => {
  const endpoint = parseEndpoint(
    rawValue,
    new Set(["http:", "https:"]),
    "COPILOT_API_BASE_URL",
  );
  if (endpoint.pathname !== "/" && endpoint.pathname !== "") {
    throw new Error("COPILOT_API_BASE_URL must not contain a path.");
  }
  return endpoint.origin;
};

const normalizeWebSocketUrl = (rawValue: string): string => {
  const endpoint = parseEndpoint(rawValue, new Set(["ws:", "wss:"]), "COPILOT_WS_URL");
  if (endpoint.pathname === "/") endpoint.pathname = "/ws";
  if (endpoint.pathname !== "/ws") {
    throw new Error("COPILOT_WS_URL must use the /ws path.");
  }
  return endpoint.toString().replace(/\/$/, "");
};

const deriveWebSocketUrl = (apiBaseUrl: string): string => {
  const endpoint = new URL(apiBaseUrl);
  endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
  endpoint.pathname = "/ws";
  return endpoint.toString().replace(/\/$/, "");
};

export const resolveDesktopRuntimeConfig = (
  environmentVariables: NodeJS.ProcessEnv,
  packaged: boolean,
): DesktopRuntimeConfig => {
  const environment = parseEnvironment(
    environmentVariables.COPILOT_DESKTOP_ENVIRONMENT,
    packaged,
  );
  const apiBaseUrl = normalizeApiUrl(
    environmentVariables.COPILOT_API_BASE_URL ?? LOCAL_API_URL,
  );
  const websocketUrl = normalizeWebSocketUrl(
    environmentVariables.COPILOT_WS_URL ?? deriveWebSocketUrl(apiBaseUrl),
  );

  if (environment === "production") {
    if (!apiBaseUrl.startsWith("https://")) {
      throw new Error("Production COPILOT_API_BASE_URL must use HTTPS.");
    }
    if (!websocketUrl.startsWith("wss://")) {
      throw new Error("Production COPILOT_WS_URL must use WSS.");
    }
  }
  return { environment, apiBaseUrl, websocketUrl };
};
