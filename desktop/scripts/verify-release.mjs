import { access, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

const desktopDirectory = path.resolve(import.meta.dirname, "..");
const releaseDirectory = path.join(desktopDirectory, "release");
const unpackedDirectory = path.join(releaseDirectory, "win-unpacked");
const appExecutable = path.join(unpackedDirectory, "AI Desktop Copilot.exe");
const appArchive = path.join(unpackedDirectory, "resources", "app.asar");
const helperExecutable = path.join(
  unpackedDirectory,
  "resources",
  "local-helper",
  "copilot-local-helper.exe",
);
const installer = path.join(releaseDirectory, "AI-Desktop-Copilot-Setup-0.1.0-x64.exe");

const requireFile = async (filePath) => {
  await access(filePath);
  const details = await stat(filePath);
  if (!details.isFile() || details.size === 0) {
    throw new Error(`Release file is empty: ${filePath}`);
  }
  return details.size;
};

const verifyPackagedApplication = async () =>
  new Promise((resolve, reject) => {
    const child = spawn(appExecutable, ["--release-smoke-test"], {
      stdio: "ignore",
      windowsHide: true,
    });
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Packaged application smoke test timed out."));
    }, 30_000);
    child.on("error", () => {
      clearTimeout(timer);
      reject(new Error("Packaged application could not start."));
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error(`Packaged application exited with code ${code}.`));
    });
  });

const verifyHelperProtocol = async () =>
  new Promise((resolve, reject) => {
    const child = spawn(helperExecutable, [], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("Packaged helper protocol verification timed out."));
    }, 15_000);
    let output = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      output += chunk;
      const events = output
        .split("\n")
        .filter(Boolean)
        .map((line) => JSON.parse(line));
      if (events.some((event) => event.event === "helper.pong")) {
        child.stdin.write(
          `${JSON.stringify({
            version: "1.0",
            id: "release-shutdown",
            command: "shutdown",
            payload: {},
          })}\n`,
        );
      }
      if (events.some((event) => event.event === "helper.stopped")) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.on("error", () => {
      clearTimeout(timer);
      reject(new Error("Packaged helper could not start."));
    });
    child.stdin.write(
      `${JSON.stringify({
        version: "1.0",
        id: "release-ping",
        command: "ping",
        payload: {},
      })}\n`,
    );
  });

const appSize = await requireFile(appExecutable);
const archiveSize = await requireFile(appArchive);
const helperSize = await requireFile(helperExecutable);
const archive = await readFile(appArchive);
const archiveText = archive.toString("latin1");
if (!archiveText.includes("https://ai-desktop-copilot-api.onrender.com")) {
  throw new Error("Packaged application is missing the production API endpoint.");
}
for (const forbidden of [
  "postgresql://",
  "postgresql+asyncpg://",
  "COPILOT_JWT_SECRET=",
  "COPILOT_CREDENTIAL_MASTER_KEY=",
  "npg_",
]) {
  if (archiveText.includes(forbidden)) {
    throw new Error(
      `Packaged application contains forbidden secret material: ${forbidden}`,
    );
  }
}
await verifyHelperProtocol();
await verifyPackagedApplication();

let installerSize;
try {
  installerSize = await requireFile(installer);
} catch {
  if (process.argv.includes("--require-installer"))
    throw new Error("Installer is missing.");
}

console.log(
  JSON.stringify(
    {
      status: "ok",
      appExecutableBytes: appSize,
      appArchiveBytes: archiveSize,
      helperExecutableBytes: helperSize,
      installerBytes: installerSize ?? null,
    },
    null,
    2,
  ),
);
