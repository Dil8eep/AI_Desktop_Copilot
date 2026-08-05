import path from "node:path";
import { describe, expect, it } from "vitest";
import { resolveLocalHelperLaunch } from "../src/main/localHelperLaunch";

describe("resolveLocalHelperLaunch", () => {
  it("uses the source backend without forwarding provider credentials", () => {
    const launch = resolveLocalHelperLaunch(
      "C:\\workspace\\desktop",
      "C:\\resources",
      false,
      {
        SystemRoot: "C:\\Windows",
        PATH: "C:\\Windows\\System32",
        OPENAI_API_KEY: "must-not-leak",
        COPILOT_DATABASE_URL: "must-not-leak",
      },
    );
    expect(launch.command).toBe(
      path.join("C:\\workspace\\backend", ".venv", "Scripts", "python.exe"),
    );
    expect(launch.args).toEqual(["-m", "app.local_helper"]);
    expect(launch.cwd).toBe("C:\\workspace\\backend");
    expect(launch.environment?.OPENAI_API_KEY).toBeUndefined();
    expect(launch.environment?.COPILOT_DATABASE_URL).toBeUndefined();
    expect(launch.environment?.SystemRoot).toBe("C:\\Windows");
  });

  it("resolves the packaged helper from Electron resources", () => {
    const launch = resolveLocalHelperLaunch(
      "C:\\installed\\app.asar",
      "C:\\installed\\resources",
      true,
      {},
    );
    expect(launch.command).toBe(
      path.join("C:\\installed\\resources", "local-helper", "copilot-local-helper.exe"),
    );
    expect(launch.args).toEqual([]);
  });
});
