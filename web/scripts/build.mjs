import { build } from "esbuild";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const mode = process.argv[2] === "test" ? "test" : "production";
const root = path.resolve(import.meta.dirname, "..");
const out = path.join(root, mode === "test" ? "dist-test" : "dist");
const hosts = mode === "test" ? ["http://127.0.0.1:8766/*"] : ["https://web.whatsapp.com/*"];
const manifest = mode === "test" ? "manifest.test.json" : "manifest.json";

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const common = {
  bundle: true,
  format: "iife",
  target: "es2022",
  platform: "browser",
  logLevel: "info"
};

await build({
  ...common,
  entryPoints: [path.join(root, "src/extension/content.ts")],
  outfile: path.join(out, "content.js")
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/extension/background.ts")],
  outfile: path.join(out, "background.js"),
  define: { __BRIDGE_HOSTS__: JSON.stringify(hosts) }
});
await build({
  ...common,
  entryPoints: [path.join(root, "src/extension/popup.ts")],
  outfile: path.join(out, "popup.js")
});

cpSync(path.join(root, "src/extension/popup.html"), path.join(out, "popup.html"));
cpSync(path.join(root, "src/extension/popup.css"), path.join(out, "popup.css"));
cpSync(path.join(root, manifest), path.join(out, "manifest.json"));

const forbidden = [
  "window.Store",
  "eval(",
  "localStorage",
  "sessionStorage",
  "document.cookie",
  "indexedDB",
  "chrome.debugger",
  "chrome.scripting",
  "webRequest",
  "execCommand",
  "insertText",
  "XMLHttpRequest",
  "fetch(",
  "keydown",
  "keypress"
];
for (const file of ["content.js", "background.js", "popup.js"]) {
  const source = readFileSync(path.join(out, file), "utf8");
  for (const token of forbidden) {
    if (source.includes(token)) {
      throw new Error(`${mode} ${file} contains ${token}`);
    }
  }
}
const shipped = readFileSync(path.join(out, "manifest.json"), "utf8");
if (mode === "production" && shipped.includes("127.0.0.1")) throw new Error("production manifest mentions the fixture");
if (mode === "test" && shipped.includes("web.whatsapp.com")) throw new Error("test manifest mentions WhatsApp Web");
writeFileSync(path.join(out, "BUILD.txt"), `${mode}\n`);
