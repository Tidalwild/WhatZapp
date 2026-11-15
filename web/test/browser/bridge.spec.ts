import { chromium, expect, test, type BrowserContext, type Page } from "@playwright/test";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer, type Server } from "node:http";
import { statSync } from "node:fs";
import { cp, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { homedir, tmpdir, userInfo } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const exec = promisify(execFile);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const repo = path.resolve(root, "..");
const extension = path.join(root, "dist-test");
const fixture = path.join(root, "fixture");
const MARKER = "secret-injected-preview";
const PREVIEW = "secret-fixture-preview";
const OTHER = "secret-sam-preview";

let pageServer: Server;
let hookServer: Server;
let hookPort = 0;
const hits: string[] = [];

test.beforeAll(async () => {
  pageServer = createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1:8766");
    const relative = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    const file = path.join(fixture, relative);
    if (!file.startsWith(fixture)) {
      response.writeHead(403);
      response.end();
      return;
    }
    try {
      const body = await readFile(file);
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(body);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  hookServer = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      hits.push(Buffer.concat(chunks).toString("utf8"));
      const body = '{"accepted":true,"unique":true,"duplicate":false}';
      response.writeHead(200, { "content-type": "application/json", "content-length": String(body.length) });
      response.end(body);
    });
  });
  await new Promise<void>((resolve) => pageServer.listen(8766, "127.0.0.1", () => resolve()));
  await new Promise<void>((resolve) => hookServer.listen(0, "127.0.0.1", () => resolve()));
  const address = hookServer.address();
  if (!address || typeof address === "string") throw new Error("hook port");
  hookPort = address.port;
});

test.afterAll(async () => {
  pageServer.closeAllConnections();
  hookServer.closeAllConnections();
  await new Promise<void>((resolve, reject) => pageServer.close((error) => (error ? reject(error) : resolve())));
  await new Promise<void>((resolve, reject) => hookServer.close((error) => (error ? reject(error) : resolve())));
});

test("fixture list unread reaches the local receiver once", async () => {
  // Chrome ignores a native host whose parent directory is world-writable, so this cannot live under /tmp.
  const home = await mkdtemp(path.join(privateRoot(), "bridge-home-"));
  const store = await mkdtemp(path.join(tmpdir(), "bridge-store-"));
  const trace = path.join(store, "trace.txt");
  await writeFile(trace, "");
  await exec("mkdir", ["-p", path.join(home, ".config/draft-bridge")]);
  await writeFile(
    path.join(home, ".config/draft-bridge/wake.env"),
    [
      "WHATSAPP_WAKE_ENABLED=1",
      `WHATSAPP_WAKE_URL=http://127.0.0.1:${hookPort}/`,
      "WHATSAPP_WAKE_AUTHORIZATION=local-test-only",
      "WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a",
      `WHATSAPP_WAKE_STORE=${store}`,
      `WHATSAPP_WAKE_BRIDGE_TRACE=${trace}`,
      ""
    ].join("\n")
  );
  await exec("python3", [
    "-c",
    "from pathlib import Path; from wake.read import bind_local; bind_local(Path('" + store + "'), 'contact-a', 'Me')"
  ], { cwd: repo });

  const launchOptions = {
    headless: false as const,
    env: {
      ...process.env,
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config"),
      WHATSAPP_WAKE_CONFIG: "",
      WHATSAPP_WAKE_URL: "",
      WHATSAPP_WAKE_AUTHORIZATION: "",
      WHATSAPP_WAKE_ENABLED: "0"
    },
    ignoreDefaultArgs: ["--disable-extensions"],
    args: [
      "--headless=new",
      "--disable-gpu",
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`
    ]
  };
  const extensionId = unpackedExtensionId(extension);
  await exec("sh", [
    path.join(repo, "scripts/install-wake-bridge.sh"),
    "--home",
    home,
    "--repo",
    repo,
    "--extension-id",
    extensionId
  ], {
    env: {
      PATH: process.env.PATH ?? "",
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config")
    }
  });
  // Playwright sets --user-data-dir, and this Chromium then looks for the host
  // manifest inside that directory rather than only under ~/.config.
  const profileHosts = path.join(home, "profile", "NativeMessagingHosts");
  await mkdir(profileHosts, { recursive: true });
  await cp(
    path.join(home, ".config", "google-chrome", "NativeMessagingHosts", "com.draft_bridge.wake.json"),
    path.join(profileHosts, "com.draft_bridge.wake.json")
  );
  const context = await chromium.launchPersistentContext(path.join(home, "profile"), launchOptions);
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:8766/list.html");
    await page.waitForSelector("html[data-bridge-probe='ready']");
    expect(await serviceWorkerId(context)).toBe(extensionId);
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.locator("#self-label").fill("Me");
    await popup.locator("#onboarding").check();
    await popup.locator("#peek").click();
    await expect(popup.locator("#header-line")).toContainText("contact-a");
    const blocked = await send(popup, {
      type: "snapshot",
      snapshot: { layout: "unrecognized", header: "", phase: "empty", slots: [] },
      listSignal: poisoned()
    });
    expect(blocked.bridgeForward).toBe("COLLECTION_OFF");
    expect(hits).toHaveLength(0);
    await popup.locator("#bind").click();
    await popup.locator("#collection-on").click();
    let last = "";
    await expect.poll(async () => {
      const code = await disposition(popup);
      const seen = await readFile(trace, "utf8").catch(() => "");
      const line = await popup.locator("#bridge-line").innerText().catch(() => "");
      const detail = await popup.evaluate(async () => {
        const reply = await chrome.runtime.sendMessage({ type: "get-view" });
        return String(reply?.bridge?.detail ?? "");
      });
      last = JSON.stringify({ code, detail, seen, line, hits: hits.length });
      return seen.includes("BASELINE") && hits.length === 0 && (code === "BASELINE" || code === "NO_NEW");
    }, { timeout: 15_000 }).toBe(true).catch(async (error) => {
      const logPath = path.join(home, "profile", "chrome_debug.log");
      const chromeLog = await readFile(logPath, "utf8").catch(() => "");
      const interesting = chromeLog.split("\n").filter((line) => /native|Native|messaging host|draft_bridge/i.test(line)).slice(-20).join("\n");
      throw new Error(`${error.message}\n${last}\n${interesting}`);
    });
    const rejected = await send(popup, {
      type: "snapshot",
      snapshot: { layout: "unrecognized", header: "", phase: "empty", slots: [] },
      listSignal: poisoned()
    });
    expect(rejected.bridgeForward).toBe("UNTRUSTED_FIELD");
    expect(await readFile(trace, "utf8")).not.toContain("UNTRUSTED_FIELD");
    expect(await readFile(trace, "utf8")).not.toContain(MARKER);
    await page.locator("#mark-unread").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("ONE_UNREAD");
    await expect.poll(() => hits.length, { timeout: 20_000 }).toBe(1);
    const body = hits[0];
    expect(body).toContain("web-page-change");
    expect(body).toContain("contact-a");
    expect(body).not.toContain(MARKER);
    expect(body).not.toContain(PREVIEW);
    expect(body).not.toContain(OTHER);
    expect(body).not.toContain("seed-local");
    expect(body).not.toContain("seed-bound");
    await page.locator("#touch").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("NO_NEW");
    expect(hits).toHaveLength(1);
    await popup.locator("#stop").click();
    await page.locator("#touch").click();
    await expect.poll(() => hits.length).toBe(1);
    await popup.locator("#collection-on").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("NO_NEW");
    expect(hits).toHaveLength(1);
    const stored = await readFile(trace, "utf8");
    expect(stored).not.toContain(MARKER);
    expect(stored).not.toContain(PREVIEW);
    expect(stored).not.toContain(OTHER);
  } finally {
    await context.close();
    await rm(home, { recursive: true, force: true });
    await rm(store, { recursive: true, force: true });
  }
});

test("live-shaped grid reaches the host without a wake or gridcell text", async () => {
  hits.length = 0;
  const home = await mkdtemp(path.join(privateRoot(), "bridge-live-"));
  const store = await mkdtemp(path.join(tmpdir(), "bridge-live-store-"));
  const trace = path.join(store, "trace.txt");
  await writeFile(trace, "");
  await exec("mkdir", ["-p", path.join(home, ".config/draft-bridge")]);
  await writeFile(
    path.join(home, ".config/draft-bridge/wake.env"),
    [
      "WHATSAPP_WAKE_ENABLED=1",
      `WHATSAPP_WAKE_URL=http://127.0.0.1:${hookPort}/`,
      "WHATSAPP_WAKE_AUTHORIZATION=local-test-only",
      "WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a",
      `WHATSAPP_WAKE_STORE=${store}`,
      `WHATSAPP_WAKE_BRIDGE_TRACE=${trace}`,
      ""
    ].join("\n")
  );
  await exec("python3", [
    "-c",
    "from pathlib import Path; from wake.read import bind_local; bind_local(Path('" + store + "'), 'contact-a', 'Me')"
  ], { cwd: repo });
  const extensionId = unpackedExtensionId(extension);
  await exec("sh", [
    path.join(repo, "scripts/install-wake-bridge.sh"),
    "--home",
    home,
    "--repo",
    repo,
    "--extension-id",
    extensionId
  ], {
    env: {
      PATH: process.env.PATH ?? "",
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config")
    }
  });
  const profileHosts = path.join(home, "profile", "NativeMessagingHosts");
  await mkdir(profileHosts, { recursive: true });
  await cp(
    path.join(home, ".config", "google-chrome", "NativeMessagingHosts", "com.draft_bridge.wake.json"),
    path.join(profileHosts, "com.draft_bridge.wake.json")
  );
  const context = await chromium.launchPersistentContext(path.join(home, "profile"), {
    headless: false,
    env: {
      ...process.env,
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config"),
      WHATSAPP_WAKE_CONFIG: "",
      WHATSAPP_WAKE_URL: "",
      WHATSAPP_WAKE_AUTHORIZATION: "",
      WHATSAPP_WAKE_ENABLED: "0"
    },
    ignoreDefaultArgs: ["--disable-extensions"],
    args: [
      "--headless=new",
      "--disable-gpu",
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`
    ]
  });
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:8766/live-list.html");
    await page.waitForSelector("html[data-bridge-probe='ready']");
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.locator("#self-label").fill("Me");
    await popup.locator("#onboarding").check();
    await popup.locator("#peek").click();
    await expect(popup.locator("#header-line")).toContainText("contact-a");
    await popup.locator("#bind").click();
    await popup.locator("#collection-on").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("UNREAD_AMBIGUOUS");
    expect(hits).toHaveLength(0);
    expect(await readFile(trace, "utf8")).toContain("UNREAD_AMBIGUOUS");
    expect(await readFile(trace, "utf8")).not.toContain("ONE_UNREAD");
    const beforeRetitle = (await readFile(trace, "utf8")).length;
    await page.locator("#retitle").click();
    await expect.poll(async () => (await readFile(trace, "utf8")).length > beforeRetitle, { timeout: 15_000 }).toBe(true);
    expect(await disposition(popup)).toBe("UNREAD_AMBIGUOUS");
    expect(hits).toHaveLength(0);
    await page.locator("#add-row").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("SEVERAL_CHANGES");
    expect(hits).toHaveLength(0);
    const stored = await readFile(trace, "utf8");
    const bridgeFiles = await readFile(path.join(store, "binding.json"), "utf8").catch(() => "");
    const popupStore = await popup.evaluate(async () => JSON.stringify(await chrome.storage.local.get(null)));
    const blob = stored + bridgeFiles + popupStore + hits.join("\n");
    for (const secret of [
      "secret-main-gridcell",
      "secret-main-text",
      "secret-other-gridcell",
      "secret-other-text",
      "secret-fixture-gridcell",
      "secret-fixture-cell-text",
      "secret-changed-gridcell",
      "secret-added-gridcell",
      "Sam",
      "Jo"
    ]) {
      expect(blob, secret).not.toContain(secret);
    }
  } finally {
    await context.close();
    await rm(home, { recursive: true, force: true });
    await rm(store, { recursive: true, force: true });
  }
});

test("rendered unread dot does not wake", async () => {
  hits.length = 0;
  const home = await mkdtemp(path.join(privateRoot(), "bridge-dot-"));
  const store = await mkdtemp(path.join(tmpdir(), "bridge-dot-store-"));
  const trace = path.join(store, "trace.txt");
  await writeFile(trace, "");
  await exec("mkdir", ["-p", path.join(home, ".config/draft-bridge")]);
  await writeFile(
    path.join(home, ".config/draft-bridge/wake.env"),
    [
      "WHATSAPP_WAKE_ENABLED=1",
      `WHATSAPP_WAKE_URL=http://127.0.0.1:${hookPort}/`,
      "WHATSAPP_WAKE_AUTHORIZATION=local-test-only",
      "WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a",
      `WHATSAPP_WAKE_STORE=${store}`,
      `WHATSAPP_WAKE_BRIDGE_TRACE=${trace}`,
      ""
    ].join("\n")
  );
  const extensionId = unpackedExtensionId(extension);
  await exec("sh", [
    path.join(repo, "scripts/install-wake-bridge.sh"),
    "--home",
    home,
    "--repo",
    repo,
    "--extension-id",
    extensionId
  ], {
    env: {
      PATH: process.env.PATH ?? "",
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config")
    }
  });
  const profileHosts = path.join(home, "profile", "NativeMessagingHosts");
  await mkdir(profileHosts, { recursive: true });
  await cp(
    path.join(home, ".config", "google-chrome", "NativeMessagingHosts", "com.draft_bridge.wake.json"),
    path.join(profileHosts, "com.draft_bridge.wake.json")
  );
  const context = await chromium.launchPersistentContext(path.join(home, "profile"), {
    headless: false,
    env: {
      ...process.env,
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config"),
      WHATSAPP_WAKE_CONFIG: "",
      WHATSAPP_WAKE_URL: "",
      WHATSAPP_WAKE_AUTHORIZATION: "",
      WHATSAPP_WAKE_ENABLED: "0"
    },
    ignoreDefaultArgs: ["--disable-extensions"],
    args: [
      "--headless=new",
      "--disable-gpu",
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`
    ]
  });
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:8766/unread-dot.html");
    await page.waitForSelector("html[data-bridge-probe='ready']");
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.locator("#onboarding").check();
    await popup.locator("#peek").click();
    await expect(popup.locator("#header-line")).toHaveText("Open chat label: contact-a");
    await popup.locator("#bind-metadata").click();
    await popup.locator("#collection-on").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("COUNT_BASELINE");
    expect(hits).toHaveLength(0);
    await page.locator("#mark-churn").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("UNREAD_DOT");
    await page.locator("#churn").click();
    await expect(popup.locator("#bridge-line")).toContainText("UNREAD_DOT");
    expect(hits).toHaveLength(0);
    await page.locator("#clear-churn").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("NO_NEW");
    expect(hits).toHaveLength(0);
    const stored = await readFile(trace, "utf8");
    expect(stored).toContain("UNREAD_DOT");
    expect(stored).not.toContain("ONE_UNREAD");
    const bridgeFiles = await readFile(path.join(store, "binding.json"), "utf8");
    const windowFile = await readFile(path.join(store, "list-window.json"), "utf8");
    const popupText = await popup.locator("#app").innerText();
    const blob = stored + bridgeFiles + windowFile + popupText;
    expect(blob).not.toContain("未讀");
    expect(blob).not.toContain("Sam");
    expect(blob).not.toContain("secret-dot-cell");
    expect(blob).not.toContain("secret-dot-gridcell");
    expect(blob).not.toContain("local-test-only");
    expect(blob).not.toContain(`127.0.0.1:${hookPort}`);
    expect(windowFile).toContain("\"count\": 0");
    await expect(popup.locator("#bridge-line")).toContainText("This sample posted: no.");
    await expect(popup.locator("#claim-line")).toContainText("Export: off");
  } finally {
    await context.close();
    await rm(home, { recursive: true, force: true });
    await rm(store, { recursive: true, force: true });
  }
});

test("numbered badge posts one hint on a rise and not on a clear", async () => {
  hits.length = 0;
  const home = await mkdtemp(path.join(privateRoot(), "bridge-count-"));
  const store = await mkdtemp(path.join(tmpdir(), "bridge-count-store-"));
  const trace = path.join(store, "trace.txt");
  await writeFile(trace, "");
  await exec("mkdir", ["-p", path.join(home, ".config/draft-bridge")]);
  await writeFile(
    path.join(home, ".config/draft-bridge/wake.env"),
    [
      "WHATSAPP_WAKE_ENABLED=1",
      `WHATSAPP_WAKE_URL=http://127.0.0.1:${hookPort}/`,
      "WHATSAPP_WAKE_AUTHORIZATION=local-test-only",
      "WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a",
      `WHATSAPP_WAKE_STORE=${store}`,
      `WHATSAPP_WAKE_BRIDGE_TRACE=${trace}`,
      ""
    ].join("\n")
  );
  const extensionId = unpackedExtensionId(extension);
  await exec("sh", [
    path.join(repo, "scripts/install-wake-bridge.sh"),
    "--home",
    home,
    "--repo",
    repo,
    "--extension-id",
    extensionId
  ], {
    env: {
      PATH: process.env.PATH ?? "",
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config")
    }
  });
  const profileHosts = path.join(home, "profile", "NativeMessagingHosts");
  await mkdir(profileHosts, { recursive: true });
  await cp(
    path.join(home, ".config", "google-chrome", "NativeMessagingHosts", "com.draft_bridge.wake.json"),
    path.join(profileHosts, "com.draft_bridge.wake.json")
  );
  const context = await chromium.launchPersistentContext(path.join(home, "profile"), {
    headless: false,
    env: {
      ...process.env,
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config"),
      WHATSAPP_WAKE_CONFIG: "",
      WHATSAPP_WAKE_URL: "",
      WHATSAPP_WAKE_AUTHORIZATION: "",
      WHATSAPP_WAKE_ENABLED: "0"
    },
    ignoreDefaultArgs: ["--disable-extensions"],
    args: [
      "--headless=new",
      "--disable-gpu",
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`
    ]
  });
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:8766/unread-count.html");
    await page.waitForSelector("html[data-bridge-probe='ready']");
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.locator("#onboarding").check();
    await popup.locator("#peek").click();
    await expect(popup.locator("#header-line")).toHaveText("Open chat label: contact-a");
    await popup.locator("#bind-metadata").click();
    await popup.locator("#collection-on").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("COUNT_BASELINE");
    expect(hits).toHaveLength(0);
    await page.locator("#show-1").click();
    await expect.poll(() => hits.length, { timeout: 20_000 }).toBe(1);
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("COUNT_UP");
    await page.locator("#clear").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("COUNT_CLEARED");
    expect(hits).toHaveLength(1);
    await page.locator("#show-2").click();
    await expect.poll(() => hits.length, { timeout: 20_000 }).toBe(2);
    const first = JSON.parse(hits[0]) as Record<string, unknown>;
    const second = JSON.parse(hits[1]) as Record<string, unknown>;
    for (const hint of [first, second]) {
      expect(hint.field).toBe("whatsapp-wake-test-v1");
      expect(hint.source).toBe("unread-indicator-hint");
      expect(hint.testOnly).toBe(true);
      expect(hint.conversationScope).toBe("contact-a");
      expect(hint).not.toHaveProperty("body");
      expect(hint).not.toHaveProperty("count");
    }
    expect(first.eventId).not.toBe(second.eventId);
    await page.locator("#same-1").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("COUNT_DOWN");
    expect(hits).toHaveLength(2);
    await page.locator("#mismatch").click();
    await expect.poll(() => disposition(popup), { timeout: 20_000 }).toBe("UNREAD_AMBIGUOUS");
    expect(hits).toHaveLength(2);
    const stored = await readFile(trace, "utf8");
    expect(stored).toContain("COUNT_UP");
    expect(stored).not.toContain("ONE_UNREAD");
    const windowFile = await readFile(path.join(store, "list-window.json"), "utf8");
    expect(windowFile).toContain("\"count\": 1");
    const popupText = await popup.locator("#app").innerText();
    expect(popupText).toContain("This sample posted: no.");
    expect(popupText).toContain("That HTTP ack is not this sample and is not a chat receipt.");
    const blob = stored + windowFile + popupText + hits.join("\n");
    expect(blob).not.toContain("個未讀訊息");
    expect(blob).not.toContain("Sam");
    expect(blob).not.toContain("secret-count-cell");
    expect(blob).not.toContain("secret-count-gridcell");
    expect(blob).not.toContain("local-test-only");
    expect(blob).not.toContain(`127.0.0.1:${hookPort}`);
  } finally {
    await context.close();
    await rm(home, { recursive: true, force: true });
    await rm(store, { recursive: true, force: true });
  }
});

test("metadata scope handshakes locally and posts nothing", async () => {
  hits.length = 0;
  const home = await mkdtemp(path.join(privateRoot(), "bridge-meta-"));
  const store = await mkdtemp(path.join(tmpdir(), "bridge-meta-store-"));
  const trace = path.join(store, "trace.txt");
  await writeFile(trace, "");
  await exec("mkdir", ["-p", path.join(home, ".config/draft-bridge")]);
  await writeFile(
    path.join(home, ".config/draft-bridge/wake.env"),
    [
      "WHATSAPP_WAKE_ENABLED=1",
      `WHATSAPP_WAKE_URL=http://127.0.0.1:${hookPort}/`,
      "WHATSAPP_WAKE_AUTHORIZATION=local-test-only",
      "WHATSAPP_WAKE_ALLOWLIST_LABEL=contact-a",
      `WHATSAPP_WAKE_STORE=${store}`,
      `WHATSAPP_WAKE_BRIDGE_TRACE=${trace}`,
      ""
    ].join("\n")
  );
  const extensionId = unpackedExtensionId(extension);
  await exec("sh", [
    path.join(repo, "scripts/install-wake-bridge.sh"),
    "--home",
    home,
    "--repo",
    repo,
    "--extension-id",
    extensionId
  ], {
    env: {
      PATH: process.env.PATH ?? "",
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config")
    }
  });
  const profileHosts = path.join(home, "profile", "NativeMessagingHosts");
  await mkdir(profileHosts, { recursive: true });
  await cp(
    path.join(home, ".config", "google-chrome", "NativeMessagingHosts", "com.draft_bridge.wake.json"),
    path.join(profileHosts, "com.draft_bridge.wake.json")
  );
  const context = await chromium.launchPersistentContext(path.join(home, "profile"), {
    headless: false,
    env: {
      ...process.env,
      HOME: home,
      XDG_CONFIG_HOME: path.join(home, ".config"),
      WHATSAPP_WAKE_CONFIG: "",
      WHATSAPP_WAKE_URL: "",
      WHATSAPP_WAKE_AUTHORIZATION: "",
      WHATSAPP_WAKE_ENABLED: "0"
    },
    ignoreDefaultArgs: ["--disable-extensions"],
    args: [
      "--headless=new",
      "--disable-gpu",
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`
    ]
  });
  try {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:8766/header-shape.html");
    await page.waitForSelector("html[data-bridge-probe='ready']");
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.locator("#onboarding").check();
    await popup.locator("#peek").click();
    await expect(popup.locator("#header-line")).toHaveText("Open chat label: contact-a");
    await popup.locator("#bind").click();
    await expect(popup.locator("#status")).toHaveText("SELF_LABEL_UNUSABLE");
    await popup.locator("#bind-metadata").click();
    await expect(popup.locator("#binding-line")).toContainText("Metadata scope");
    await expect(popup.locator("#self-label")).toHaveValue("");
    await popup.locator("#collection-on").click();
    await expect.poll(async () => {
      const binding = await readFile(path.join(store, "binding.json"), "utf8").catch(() => "");
      const seen = await readFile(trace, "utf8").catch(() => "");
      return binding.includes('"mode": "metadata"') && seen.includes("BASELINE") && !seen.includes("ONE_UNREAD") && hits.length === 0;
    }, { timeout: 20_000 }).toBe(true);
    const binding = JSON.parse(await readFile(path.join(store, "binding.json"), "utf8")) as { mode: string; selfLabel: string; visibleHeader: string };
    expect(binding.mode).toBe("metadata");
    expect(binding.selfLabel).toBe("");
    expect(binding.visibleHeader).toBe("contact-a");
    expect(hits).toHaveLength(0);
    expect(await readFile(trace, "utf8")).not.toContain("ONE_UNREAD");
    await popup.evaluate(async () => {
      await chrome.runtime.sendMessage({
        type: "snapshot",
        snapshot: {
          layout: "probe-contract",
          header: "contact-a",
          phase: "ready",
          slots: [{ kind: "message", sender: "contact-a", text: "secret-metadata-body", timeText: "09:01" }]
        }
      });
    });
    await expect(popup.locator("#bridge-line")).toContainText("Page bridge: open.");
    await expect(popup.locator("#bridge-line")).toContainText("Hello: READY.");
    await expect(popup.locator("#bridge-line")).toContainText("Scope: SCOPE.");
    await expect(popup.locator("#bridge-line")).toContainText(/List: (COUNT_BASELINE|NO_NEW)\./);
    await expect(popup.locator("#bridge-line")).toContainText("This sample posted: no.");
    await expect(popup.locator("#app")).not.toContainText("UNRECOGNIZED_LAYOUT");
    await expect(popup.locator("#app")).not.toContainText("HOST_ERROR");
    await expect(popup.locator("#messages")).toHaveText("");
    const beforeStop = (await readFile(trace, "utf8")).length;
    await popup.locator("#stop").click();
    await popup.locator("#collection-on").click();
    await expect.poll(async () => (await readFile(trace, "utf8")).length > beforeStop, { timeout: 15_000 }).toBe(true);
    expect(hits).toHaveLength(0);
    const stored = await readFile(trace, "utf8");
    const bridgeFiles = await readFile(path.join(store, "binding.json"), "utf8");
    const popupStore = await popup.evaluate(async () => JSON.stringify(await chrome.storage.local.get(null)));
    const blob = stored + bridgeFiles + popupStore + hits.join("\n") + (await popup.locator("#app").innerText());
    for (const secret of ["secret-metadata-body", "local-test-only", "secret-shape-gridcell", "secret-shape-cell", "secret-shape-longer", "A+B Academy"]) {
      expect(blob, secret).not.toContain(secret);
    }
    expect(blob).not.toContain(`127.0.0.1:${hookPort}`);
  } finally {
    await context.close();
    await rm(home, { recursive: true, force: true });
    await rm(store, { recursive: true, force: true });
  }
});

function poisoned(): Record<string, unknown> {
  return {
    layout: "chat-list-contract",
    boundLabel: "contact-a",
    matches: 1,
    position: 0,
    unread: true,
    otherChanges: 0,
    preview: MARKER,
    rows: [{ name: OTHER }]
  };
}

async function disposition(popup: Page): Promise<string> {
  return popup.evaluate(async () => {
    const reply = await chrome.runtime.sendMessage({ type: "get-view" });
    return String(reply?.bridge?.list ?? "");
  });
}

async function send(popup: Page, message: Record<string, unknown>): Promise<{ bridgeForward?: string }> {
  return popup.evaluate(async (payload) => chrome.runtime.sendMessage(payload), message);
}

function privateRoot(): string {
  const candidates = [process.env.XDG_RUNTIME_DIR, `/run/user/${userInfo().uid}`, homedir(), repo].filter(
    (value): value is string => Boolean(value)
  );
  const seen = new Set<string>();
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (seen.has(resolved) || !installRootOk(resolved)) continue;
    seen.add(resolved);
    return resolved;
  }
  throw new Error("no private directory outside /tmp");
}

function installRootOk(start: string): boolean {
  let current = start;
  try {
    if (!statSync(current).isDirectory()) return false;
  } catch {
    return false;
  }
  while (true) {
    if (current === "/tmp" || current === "/var/tmp" || current === "/dev/shm") return false;
    if (statSync(current).mode & 0o002) return false;
    const parent = path.dirname(current);
    if (parent === current) return true;
    current = parent;
  }
}

function unpackedExtensionId(extensionPath: string): string {
  const hex = createHash("sha256").update(extensionPath).digest("hex").slice(0, 32);
  return [...hex].map((char) => String.fromCharCode("a".charCodeAt(0) + Number.parseInt(char, 16))).join("");
}

async function serviceWorkerId(context: BrowserContext): Promise<string> {
  let worker = context.serviceWorkers()[0];
  if (!worker) worker = await context.waitForEvent("serviceworker");
  return new URL(worker.url()).host;
}
