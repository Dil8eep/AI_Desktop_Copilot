import { readFile } from "node:fs/promises";
import path from "node:path";

const rendererDirectory = path.resolve(import.meta.dirname, "../dist/renderer");
for (const page of ["index.html", "overlay.html"]) {
  const html = await readFile(path.join(rendererDirectory, page), "utf8");
  if (/(?:src|href)="\/assets\//.test(html)) {
    throw new Error(`${page} contains drive-root asset URLs that fail under file://.`);
  }
  if (!html.includes("./assets/")) {
    throw new Error(`${page} does not contain relative packaged asset URLs.`);
  }
}
console.log("Packaged renderer asset paths are relative.");
