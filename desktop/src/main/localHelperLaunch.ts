import path from "node:path";
import type { LocalHelperLaunchOptions } from "./services/localCaptureHelperClient";

const keepEnvironment = (environment: NodeJS.ProcessEnv): NodeJS.ProcessEnv => {
  const allowed = [
    "SystemRoot",
    "WINDIR",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "APPDATA",
  ];
  return Object.fromEntries(
    allowed.flatMap((key) =>
      environment[key] === undefined ? [] : [[key, environment[key]]],
    ),
  );
};

/** Resolve a credential-free helper launch for source and packaged installations. */
export const resolveLocalHelperLaunch = (
  appPath: string,
  resourcesPath: string,
  isPackaged: boolean,
  environment: NodeJS.ProcessEnv,
): LocalHelperLaunchOptions => {
  const safeEnvironment = {
    ...keepEnvironment(environment),
    PYTHONIOENCODING: "utf-8",
    PYTHONUNBUFFERED: "1",
  };
  if (isPackaged) {
    return {
      command: path.join(resourcesPath, "local-helper", "copilot-local-helper.exe"),
      args: [],
      environment: safeEnvironment,
    };
  }
  const backendDirectory = path.resolve(appPath, "../backend");
  return {
    command:
      environment.COPILOT_LOCAL_HELPER_COMMAND ??
      path.join(backendDirectory, ".venv", "Scripts", "python.exe"),
    args: ["-m", "app.local_helper"],
    cwd: backendDirectory,
    environment: safeEnvironment,
  };
};
