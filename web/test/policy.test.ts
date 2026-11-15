import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) files.push(...walk(full));
    else if (full.endsWith(".ts")) files.push(full);
  }
  return files;
}

describe("extension boundaries", () => {
  it("ships storage and one host, with a fixture-only test manifest", () => {
    const production = JSON.parse(readFileSync(path.join(root, "manifest.json"), "utf8"));
    const fixture = JSON.parse(readFileSync(path.join(root, "manifest.test.json"), "utf8"));
    expect(production.permissions).toEqual(["storage", "nativeMessaging"]);
    expect(production.host_permissions).toEqual(["https://web.whatsapp.com/*"]);
    expect(production.content_scripts[0].matches).toEqual(["https://web.whatsapp.com/*"]);
    expect(JSON.stringify(production)).not.toContain("127.0.0.1");
    expect(fixture.permissions).toEqual(["storage", "nativeMessaging"]);
    expect(fixture.host_permissions).toEqual(["http://127.0.0.1:8766/*"]);
    expect(fixture.content_scripts[0].matches).toEqual(["http://127.0.0.1:8766/*"]);
    expect(JSON.stringify(fixture)).not.toContain("web.whatsapp.com");
    for (const manifest of [production, fixture]) {
      const text = JSON.stringify(manifest);
      expect(text).not.toContain("all_urls");
      expect(text).not.toContain("<all_urls>");
      expect(manifest.permissions).not.toContain("tabs");
      expect(manifest.permissions).not.toContain("history");
      expect(manifest.permissions).not.toContain("cookies");
      expect(manifest.permissions).not.toContain("debugger");
      expect(manifest.permissions).not.toContain("webRequest");
      expect(manifest.permissions).not.toContain("scripting");
      expect(manifest.permissions).not.toContain("notifications");
    }
  });

  it("does not read page storage, hook the composer, or reach for private page state", () => {
    const forbidden = [
      "window.Store",
      "eval(",
      "new Function",
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
      "keypress",
      "webpack"
    ];
    const files = walk(path.join(root, "src"));
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      const source = readFileSync(file, "utf8");
      for (const token of forbidden) {
        expect(source, `${path.relative(root, file)} contains ${token}`).not.toContain(token);
      }
    }
    const content = readFileSync(path.join(root, "src/extension/content.ts"), "utf8");
    expect(content).not.toContain("chrome.tabs");
  });
});
