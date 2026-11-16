import { sanitizeListSignal } from "../bridgeSignal.js";
import { composerFrame } from "../composerSample.js";
import { Engine } from "../engine.js";
import { acceptSurface, closedSurface } from "../sendSurface.js";
import { bridgeLifecycle, classifyHostExit, safeHostDetail, type HostCause } from "../hostStatus.js";
import { FilteringLog } from "../log.js";
import type { ProbeSnapshot } from "../model.js";
import { classifyPeekTransport } from "../reportedBinding.js";

declare const __BRIDGE_HOSTS__: string[];

const STORAGE_KEY = "bridge-state-v1";
const HOST_NAME = "com.draft_bridge.wake";
const TOKEN = /^[A-Za-z0-9._-]{1,40}$/;
const log = new FilteringLog();
let engine = new Engine({ log });
let lastHeader = "";
let port: chrome.runtime.Port | null = null;
let hostLabel = "";
let helloState = "none";
let scopeState = "none";
let listState = "none";
let listRecent: string[] = [];
let forwardState = "none";
let forwardEvent = "";
let samplePosted = false;
let sampleCount: number | null = null;
let sampleCountKnown = false;
let samplePrior: number | null = null;
let sampleStored: number | null = null;
let sampleChange = "";
let sampleAt = "";
let lastForward = "none";
let lastEvent = "";
let lastAt = "";
let hostCause: HostCause = "";
let hostDetail = "";
let holdConnect = false;

const SAMPLE_CHANGES = new Set(["baseline", "up", "down", "clear", "same", "held"]);
const EVENT_ID = /^evt-[0-9a-f]{32}$/;
const OBSERVED_AT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const ACK_KEYS = new Set([
  "v",
  "kind",
  "disposition",
  "posted",
  "forward",
  "event",
  "count",
  "prior",
  "stored",
  "change",
  "at",
  "lastForward",
  "lastEvent",
  "lastAt"
]);

const ready = load();

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  ready
    .then(() => dispatch(message))
    .then((result) => sendResponse(result))
    .catch(() => sendResponse({ error: "unavailable" }));
  return true;
});

async function load(): Promise<void> {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  const raw = stored[STORAGE_KEY];
  if (raw) {
    try {
      const parsed = JSON.parse(raw as string);
      if (parsed.historyComplete !== false) throw new Error("history");
      engine = new Engine({ log, state: parsed });
      engine.restart();
    } catch {
      engine.stop();
      engine.log.event("store", { disposition: "unreadable" });
    }
  }
  if (engine.view().settings.collectionEnabled) ensurePort();
}

async function dispatch(message: { type?: string; [key: string]: unknown }): Promise<unknown> {
  switch (message.type) {
    case "get-view":
      return { view: engine.view(), logs: engine.log.lines.slice(-40), bridge: bridgeView() };
    case "get-watch":
      return {
        watch: engine.view().settings.collectionEnabled,
        boundLabel: engine.view().binding?.visibleHeader ?? "",
        mode: engine.view().binding?.mode === "metadata" ? "metadata" : "messages"
      };
    case "peek":
      return peek();
    case "read-chat":
      return readBoundChat();
    case "bind":
      return bind(String(message.selfLabel ?? ""));
    case "bind-metadata":
      return bindMetadata();
    case "set-onboarding":
      engine.acceptOnboarding(Boolean(message.accepted));
      await persist();
      return { view: engine.view() };
    case "set-collection":
      return setCollection(Boolean(message.enabled));
    case "set-export": {
      const disposition = engine.setExport(Boolean(message.enabled));
      await persist();
      return { view: engine.view(), disposition };
    }
    case "deliver-reply": {
      const surface = await sendSurface();
      noteComposer(surface.composer);
      const delivery = await engine.attemptLiveDelivery(String(message.replyText ?? ""), surface);
      if (delivery.persisted) await persist();
      return { delivery, view: engine.view() };
    }
    case "set-context": {
      const disposition = engine.setContextOptIn(message.enabled === true);
      if (disposition === "CONTEXT_ON" || disposition === "CONTEXT_REVOKED") {
        const scope = engine.dump().context.scopeId;
        noteFrame({ v: 1, kind: "context-policy", action: disposition === "CONTEXT_ON" ? "enable" : "revoke", scope });
      }
      await persist();
      return { view: engine.view(), disposition };
    }
    case "approve-exact": {
      const disposition = await engine.approveExact(String(message.text ?? ""), String(message.event ?? ""));
      if (disposition === "APPROVED_NOT_SENT") {
        const approval = engine.dump().approval;
        noteFrame({
          v: 1,
          kind: "approval-note",
          action: "approve",
          scope: approval.scopeId,
          event: approval.event,
          digest: approval.digest
        });
      }
      await persist();
      return { view: engine.view(), disposition };
    }
    case "pause-approval": {
      const disposition = engine.pauseApproval();
      if (disposition === "PAUSED") noteFrame({ v: 1, kind: "approval-note", action: "pause" });
      await persist();
      return { view: engine.view(), disposition };
    }
    case "revoke-approval": {
      const disposition = engine.revokeApproval();
      noteFrame({ v: 1, kind: "approval-note", action: "revoke" });
      await persist();
      return { view: engine.view(), disposition };
    }
    case "set-reply-grant": {
      const disposition = engine.setReplyGrant(Boolean(message.enabled));
      await persist();
      return { view: engine.view(), disposition };
    }
    case "set-scope": {
      const raw = (message.scope ?? {}) as { mode?: "off" | "allowlist" | "direct"; allow?: unknown; deny?: unknown; groups?: "exclude" | "include"; maxReplies?: unknown };
      const list = (value: unknown) => (Array.isArray(value) ? value.map((item) => String(item)) : []);
      const scope = engine.setScope({
        mode: raw.mode,
        allow: list(raw.allow),
        deny: list(raw.deny),
        groups: raw.groups,
        maxReplies: typeof raw.maxReplies === "number" ? raw.maxReplies : Number(raw.maxReplies)
      });
      await persist();
      return { view: engine.view(), disposition: `scope-${scope.mode}` };
    }
    case "enroll-identity": {
      const disposition = engine.enrollIdentity({
        contactDigest: String(message.contactDigest ?? ""),
        profileDigest: String(message.profileDigest ?? ""),
        openedHeader: String(message.openedHeader ?? ""),
        openedByNumber: message.openedByNumber === true
      });
      if (disposition === "IDENTITY_ENROLLED" || disposition === "SELF_CHAT") await persist();
      return { view: engine.view(), disposition };
    }
    case "stop":
      engine.stop();
      closePort();
      await tellTabs(false);
      await persist();
      return { view: engine.view(), bridge: bridgeView() };
    case "purge":
      engine.purgeBodies();
      await persist();
      return { view: engine.view() };
    case "reload-queue":
      await load();
      return { view: engine.view() };
    case "confirm-draft": {
      const attempt = await engine.confirmDraft(String(message.commandId ?? ""), String(message.exactBody ?? ""));
      await persist();
      return { attempt, view: engine.view() };
    }
    case "list-signal":
      return { bridgeForward: forwardList(message.listSignal), view: engine.view(), bridge: bridgeView() };
    case "person-roster":
      return { bridgeForward: forwardPersons(message.hints), view: engine.view(), bridge: bridgeView() };
    case "list-change":
      return { bridgeForward: forwardListChange(message.mark, message.count), view: engine.view(), bridge: bridgeView() };
    case "pane-hint":
      return { bridgeForward: forwardPaneHint(message.generation), view: engine.view(), bridge: bridgeView() };
    case "inspect-unread":
      return inspectUnread();
    case "open-wake":
      return openWake();
    case "contact-surface":
      return contactSurface();
    case "snapshot":
      if (engine.view().binding?.mode === "metadata") {
        return {
          result: { disposition: "METADATA_ONLY" },
          view: engine.view(),
          bridge: bridgeView(),
          bridgeForward: forwardList(message.listSignal)
        };
      }
      return takeSnapshot(message.snapshot as ProbeSnapshot, message.listSignal);
    default:
      return { error: "unknown" };
  }
}

async function readBoundChat(): Promise<unknown> {
  const binding = engine.view().binding;
  if (!binding) return { error: "NOT_BOUND", view: engine.view(), bridge: bridgeView() };
  const tab = await oneTab();
  if (!tab.ok) return { error: tab.error, view: engine.view(), bridge: bridgeView() };
  try {
    const report = await chrome.tabs.sendMessage(tab.id, { type: "do-read", boundLabel: binding.visibleHeader });
    const surface = await sendSurface();
    noteComposer(surface.composer);
    if (report?.disposition === "READ") noteFrame({ v: 1, kind: "read-note", event: EVENT_ID.test(lastEvent) ? lastEvent : "" });
    const replyGate = engine.assessAutomaticReply(report);
    return { read: report, replyGate, view: engine.view(), bridge: bridgeView() };
  } catch (error) {
    const text = error instanceof Error ? error.message : "";
    return { error: classifyPeekTransport(text), view: engine.view(), bridge: bridgeView() };
  }
}

async function peek(): Promise<unknown> {
  const tab = await oneTab();
  if (!tab.ok) return { error: tab.error, header: "", view: engine.view() };
  try {
    const result = await chrome.tabs.sendMessage(tab.id, { type: "do-peek" });
    lastHeader = typeof result?.header === "string" ? result.header.trim() : "";
  } catch (error) {
    lastHeader = "";
    const message = error instanceof Error ? error.message : "";
    return { error: classifyPeekTransport(message), header: "", view: engine.view() };
  }
  return { header: lastHeader, view: engine.view() };
}

async function bind(selfLabel: string): Promise<unknown> {
  if (lastHeader === "") return { error: "header-not-read", view: engine.view() };
  const result = engine.bind(lastHeader, selfLabel);
  return finishBind(result);
}

async function bindMetadata(): Promise<unknown> {
  if (lastHeader === "") return { error: "header-not-read", view: engine.view() };
  const result = engine.bindMetadata(lastHeader);
  return finishBind(result);
}

async function finishBind(result: { ok: true } | { ok: false; reason: string }): Promise<unknown> {
  closePort();
  if (result.ok && engine.view().settings.collectionEnabled) {
    ensurePort();
    await tellTabs(true);
  }
  await persist();
  return result.ok ? { view: engine.view(), bridge: bridgeView() } : { error: result.reason, view: engine.view() };
}

async function setCollection(enabled: boolean): Promise<unknown> {
  if (enabled) holdConnect = false;
  const disposition = engine.setCollection(enabled);
  if (disposition === "collection-on") {
    ensurePort();
    await tellTabs(true);
  } else if (disposition === "collection-off") {
    closePort();
    await tellTabs(false);
  }
  await persist();
  return { view: engine.view(), disposition, bridge: bridgeView() };
}

async function takeSnapshot(snapshot: ProbeSnapshot, listSignal: unknown): Promise<unknown> {
  const result = await engine.observe(snapshot);
  const bridgeForward = forwardList(listSignal);
  await persist();
  return { result, view: engine.view(), bridge: bridgeView(), bridgeForward };
}

async function persist(): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY]: JSON.stringify(engine.dump()) });
}

async function tellTabs(on: boolean): Promise<void> {
  const tab = await oneTab();
  if (!tab.ok) return;
  await chrome.tabs.sendMessage(tab.id, {
    type: "watch",
    on,
    boundLabel: on ? engine.view().binding?.visibleHeader ?? "" : "",
    mode: on && engine.view().binding?.mode === "metadata" ? "metadata" : "messages"
  }).catch(() => undefined);
}

function rememberBridge(): void {
  const view = bridgeView();
  void chrome.storage.local.set({
    "bridge-status-v1": JSON.stringify({
      state: view.state,
      hello: view.hello,
      scope: view.scope,
      list: view.list,
      recent: view.recent,
      forward: view.forward,
      event: view.event,
      posted: view.posted,
      count: view.count,
      prior: view.prior,
      stored: view.stored,
      change: view.change,
      at: view.at,
      lastForward: view.lastForward,
      lastEvent: view.lastEvent,
      lastAt: view.lastAt,
      cause: view.cause
    })
  });
}

function desiredLabel(): string {
  const header = engine.view().binding?.visibleHeader ?? "";
  return TOKEN.test(header) ? header : "";
}

function bridgeView(): {
  state: string;
  hello: string;
  scope: string;
  list: string;
  recent: string;
  forward: string;
  event: string;
  posted: boolean;
  count: number | null;
  prior: number | null;
  stored: number | null;
  change: string;
  at: string;
  lastForward: string;
  lastEvent: string;
  lastAt: string;
  cause: string;
  detail: string;
} {
  const state = bridgeLifecycle({ port: port !== null, hello: helloState, cause: hostCause });
  const visible = state !== "off";
  return {
    state,
    hello: visible ? helloState : "none",
    scope: visible ? scopeState : "none",
    list: visible ? listState : "none",
    recent: listRecent.join(" "),
    forward: forwardState,
    event: forwardEvent,
    posted: samplePosted,
    count: sampleCountKnown ? sampleCount : null,
    prior: samplePrior,
    stored: sampleStored,
    change: sampleChange,
    at: sampleAt,
    lastForward,
    lastEvent,
    lastAt,
    cause: state === "exited" ? hostCause : "",
    detail: state === "exited" ? hostDetail : ""
  };
}

function ensurePort(): void {
  if (holdConnect || port || !engine.view().settings.collectionEnabled || desiredLabel() === "") return;
  let created: chrome.runtime.Port;
  try {
    created = chrome.runtime.connectNative(HOST_NAME);
  } catch {
    hostCause = "HOST_ERROR";
    hostDetail = "connectNative";
    holdConnect = true;
    rememberBridge();
    return;
  }
  port = created;
  helloState = "pending";
  scopeState = "pending";
  listState = "none";
  clearSample();
  hostCause = "";
  hostDetail = "";
  created.onDisconnect.addListener(() => {
    if (port !== created) return;
    port = null;
    hostLabel = "";
    const message = chrome.runtime.lastError?.message ?? "";
    hostCause = classifyHostExit(message);
    hostDetail = safeHostDetail(message);
    holdConnect = true;
    rememberBridge();
  });
  created.onMessage.addListener((message) => handleHost(message));
  try {
    created.postMessage({ v: 1, kind: "hello" });
    const label = desiredLabel();
    if (engine.view().binding?.mode === "metadata" && label !== "") {
      created.postMessage({ v: 1, kind: "scope-offer", label });
    }
  } catch {
    port = null;
    hostCause = "HOST_PROTOCOL";
    holdConnect = true;
  }
  rememberBridge();
}

function closePort(): void {
  hostLabel = "";
  helloState = "none";
  scopeState = "none";
  listState = "none";
  listRecent = [];
  clearSample();
  hostCause = "";
  hostDetail = "";
  holdConnect = false;
  const current = port;
  port = null;
  try {
    current?.disconnect();
  } catch {
    // The host is already gone.
  }
}

function handleHost(message: unknown): void {
  if (!message || typeof message !== "object") return;
  const record = message as Record<string, unknown>;
  if (record.kind === "permit" && permitWait) {
    const disposition = typeof record.disposition === "string" && /^[A-Z_]{1,40}$/.test(record.disposition) ? record.disposition : "NONE";
    const chatRef = typeof record.chatRef === "string" && /^ref-[0-9a-f]{16}$/.test(record.chatRef) ? record.chatRef : undefined;
    const finish = permitWait;
    permitWait = null;
    finish({ disposition, chatRef });
    return;
  }
  const keys = Object.keys(record);
  if (record.kind === "scope" && keys.every((key) => key === "v" || key === "kind" || key === "label")) {
    hostLabel = typeof record.label === "string" && TOKEN.test(record.label) ? record.label : "";
    scopeState = hostLabel === "" ? "NOT_BOUND" : hostLabel === desiredLabel() ? "SCOPE" : "SCOPE_MISMATCH";
    if (hostLabel !== "" && hostLabel === desiredLabel()) void tellTabs(true);
    rememberBridge();
    return;
  }
  if (record.kind === "ack" && keys.every((key) => ACK_KEYS.has(key))) {
    const code =
      typeof record.disposition === "string" && /^[A-Z_]{1,40}$/.test(record.disposition)
        ? record.disposition
        : "UNREADABLE";
    const forward =
      record.forward === "attempted" || record.forward === "accepted" || record.forward === "error"
        ? record.forward
        : "";
    const event = typeof record.event === "string" && EVENT_ID.test(record.event) ? record.event : "";
    const count = optionalCount(record.count);
    const prior = optionalCount(record.prior);
    const stored = optionalCount(record.stored);
    const change = typeof record.change === "string" && SAMPLE_CHANGES.has(record.change) ? record.change : "";
    const at = typeof record.at === "string" && OBSERVED_AT.test(record.at) ? record.at : "";
    const priorForward =
      record.lastForward === "attempted" || record.lastForward === "accepted" || record.lastForward === "error"
        ? record.lastForward
        : "";
    const priorEvent = typeof record.lastEvent === "string" && EVENT_ID.test(record.lastEvent) ? record.lastEvent : "";
    const priorAt = typeof record.lastAt === "string" && OBSERVED_AT.test(record.lastAt) ? record.lastAt : "";
    if (
      (record.forward !== undefined && forward === "") ||
      (record.event !== undefined && event === "") ||
      (record.count !== undefined && count === null) ||
      (record.prior !== undefined && prior === null) ||
      (record.stored !== undefined && stored === null) ||
      (record.change !== undefined && change === "") ||
      (record.at !== undefined && at === "") ||
      (record.lastForward !== undefined && priorForward === "") ||
      (record.lastEvent !== undefined && priorEvent === "") ||
      (record.lastAt !== undefined && priorAt === "")
    ) {
      listState = "UNTRUSTED_FIELD";
      rememberBridge();
      return;
    }
    applyAck(code, {
      posted: record.posted === true,
      forward,
      event,
      count,
      countPresent: record.count !== undefined,
      prior,
      priorPresent: record.prior !== undefined,
      stored,
      storedPresent: record.stored !== undefined,
      change,
      at,
      lastForward: priorForward,
      lastEvent: priorEvent,
      lastAt: priorAt
    });
    rememberBridge();
    return;
  }
  if (helloState === "pending") helloState = "UNTRUSTED_FIELD";
  else scopeState = "UNTRUSTED_FIELD";
  rememberBridge();
}

function clearSample(): void {
  forwardState = "none";
  forwardEvent = "";
  samplePosted = false;
  sampleCount = null;
  sampleCountKnown = false;
  samplePrior = null;
  sampleStored = null;
  sampleChange = "";
  sampleAt = "";
  lastForward = "none";
  lastEvent = "";
  lastAt = "";
}

function optionalCount(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0 || value > 9999) return null;
  return value;
}

function applyAck(
  code: string,
  sample: {
    posted: boolean;
    forward: string;
    event: string;
    count: number | null;
    countPresent: boolean;
    prior: number | null;
    priorPresent: boolean;
    stored: number | null;
    storedPresent: boolean;
    change: string;
    at: string;
    lastForward: string;
    lastEvent: string;
    lastAt: string;
  }
): void {
  if (code === "READY") {
    helloState = "READY";
    hostCause = "";
    return;
  }
  if (
    code === "SCOPE" ||
    code === "SCOPE_MISMATCH" ||
    code === "NOT_BOUND" ||
    code === "MODE_MISMATCH" ||
    code === "HEADER_UNUSABLE"
  ) {
    scopeState = code;
    return;
  }
  if (
    code === "COMPOSER_NOTED" ||
    code === "CONTEXT_NOTED" ||
    code === "CONTEXT_ABSENT" ||
    code === "READ_NOTED" ||
    code === "APPROVED_NOT_SENT" ||
    code === "PAUSED" ||
    code === "REVOKED" ||
    code === "AMBIGUOUS_HOLD" ||
    code === "SEND_DISARMED"
  ) {
    return;
  }
  if (code === "UNTRUSTED_FIELD" || code === "UNPARSEABLE" || code === "OVERSIZE" || code === "SHORT" || code === "UNREADABLE") {
    if (helloState === "pending") helloState = code;
    else if (scopeState === "pending") scopeState = code;
    else listState = code;
    return;
  }
  listState = code;
  if (listRecent[listRecent.length - 1] !== code) {
    listRecent.push(code);
    if (listRecent.length > 8) listRecent.splice(0, listRecent.length - 8);
  }
  samplePosted = sample.posted;
  forwardState = sample.forward || "none";
  forwardEvent = sample.event;
  sampleChange = sample.change;
  sampleAt = sample.at;
  if (sample.countPresent && sample.count !== null) {
    sampleCount = sample.count;
    sampleCountKnown = true;
  } else if (sample.change === "held") {
    sampleCount = null;
    sampleCountKnown = false;
  }
  samplePrior = sample.priorPresent ? sample.prior : null;
  if (sample.storedPresent) sampleStored = sample.stored;
  if (sample.forward === "attempted" || sample.forward === "accepted" || sample.forward === "error") {
    lastForward = sample.forward;
    lastEvent = sample.event;
    if (sample.at) lastAt = sample.at;
  } else if (sample.lastEvent) {
    lastForward = sample.lastForward || "none";
    lastEvent = sample.lastEvent;
    lastAt = sample.lastAt;
  }
}

let permitWait: ((value: { disposition: string; chatRef?: string }) => void) | null = null;

function forwardPersons(raw: unknown): string {
  if (!Array.isArray(raw) || raw.length === 0) return "EMPTY";
  if (!engine.view().settings.collectionEnabled) return "COLLECTION_OFF";
  ensurePort();
  if (!port) return hostCause || "UNAVAILABLE";
  for (const hint of raw) {
    if (!hint || typeof hint !== "object") return "UNTRUSTED_FIELD";
    const record = hint as Record<string, unknown>;
    const keys = Object.keys(record);
    if (keys.some((key) => key !== "chatRef" && key !== "mark" && key !== "count")) return "UNTRUSTED_FIELD";
    if (typeof record.chatRef !== "string" || !/^ref-[0-9a-f]{16}$/.test(record.chatRef)) return "UNTRUSTED_FIELD";
    if (record.mark !== "count" && record.mark !== "absent") return "UNTRUSTED_FIELD";
    if (typeof record.count !== "number" || !Number.isInteger(record.count) || record.count < 0 || record.count > 9999) {
      return "UNTRUSTED_FIELD";
    }
    if (record.mark === "absent" && record.count !== 0) return "UNTRUSTED_FIELD";
    if (record.mark === "count" && record.count < 1) return "UNTRUSTED_FIELD";
    try {
      port.postMessage({ v: 2, kind: "person-hint", chatRef: record.chatRef, mark: record.mark, count: record.count });
    } catch {
      port = null;
      hostCause = "HOST_PROTOCOL";
      holdConnect = true;
      rememberBridge();
      return "HOST_PROTOCOL";
    }
  }
  return "FORWARDED";
}

function forwardListChange(mark: unknown, count: unknown): string {
  if (!engine.view().settings.collectionEnabled) return "COLLECTION_OFF";
  ensurePort();
  if (!port) return hostCause || "UNAVAILABLE";
  if (mark !== "count" && mark !== "absent") return "UNTRUSTED_FIELD";
  if (typeof count !== "number" || !Number.isInteger(count) || count < 0 || count > 9999) return "UNTRUSTED_FIELD";
  if (mark === "absent" && count !== 0) return "UNTRUSTED_FIELD";
  if (mark === "count" && count < 1) return "UNTRUSTED_FIELD";
  try {
    port.postMessage({ v: 3, kind: "list-change", mark, count });
  } catch {
    port = null;
    hostCause = "HOST_PROTOCOL";
    holdConnect = true;
    rememberBridge();
    return "HOST_PROTOCOL";
  }
  return "FORWARDED";
}

function forwardPaneHint(generation: unknown): string {
  if (!engine.view().settings.collectionEnabled) return "COLLECTION_OFF";
  ensurePort();
  if (!port) return hostCause || "UNAVAILABLE";
  if (typeof generation !== "number" || !Number.isInteger(generation) || generation < 1 || generation > 9999) {
    return "UNTRUSTED_FIELD";
  }
  try {
    port.postMessage({ v: 3, kind: "pane-hint", generation });
  } catch {
    port = null;
    hostCause = "HOST_PROTOCOL";
    holdConnect = true;
    rememberBridge();
    return "HOST_PROTOCOL";
  }
  return "FORWARDED";
}

async function inspectUnread(): Promise<unknown> {
  if (!engine.view().settings.collectionEnabled) {
    return { disposition: "COLLECTION_OFF", identity: "UNPROVEN", messagesCollected: false, view: engine.view() };
  }
  const tab = await oneTab();
  if (!tab.ok) return { disposition: "NO_TAB", identity: "UNPROVEN", messagesCollected: false, view: engine.view() };
  try {
    const result = await chrome.tabs.sendMessage(tab.id, { type: "inspect-unread" });
    const disposition = typeof result?.disposition === "string" && /^[A-Z_]{1,40}$/.test(result.disposition) ? result.disposition : "UNPROVEN";
    const identity = result?.identity === "AMBIGUOUS" ? "AMBIGUOUS" : "UNPROVEN";
    return { disposition, identity, messagesCollected: false, view: engine.view() };
  } catch {
    return { disposition: "STALE", identity: "UNPROVEN", messagesCollected: false, view: engine.view() };
  }
}

function openWake(): Promise<unknown> {
  if (!engine.view().settings.collectionEnabled) return Promise.resolve({ disposition: "COLLECTION_OFF", view: engine.view() });
  ensurePort();
  if (!port) return Promise.resolve({ disposition: "UNAVAILABLE", view: engine.view() });
  const current = port;
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => finish({ disposition: "TIMEOUT" }), 2000);
    function finish(value: { disposition: string; chatRef?: string }) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (permitWait === finish) permitWait = null;
      void deliverOpen(value).then((disposition) => resolve({ disposition, view: engine.view() }));
    }
    permitWait = finish;
    try {
      current.postMessage({ v: 2, kind: "take-permit" });
    } catch {
      finish({ disposition: "HOST_PROTOCOL" });
    }
  });
}

async function contactSurface(): Promise<unknown> {
  const tab = await oneTab();
  if (!tab.ok) return { surface: "unproven", attention: "CLOSED", view: engine.view() };
  try {
    const result = await chrome.tabs.sendMessage(tab.id, { type: "attention-gate" });
    const surface = result?.surface === "direct-contact" ? "direct-contact" : "unproven";
    return { surface, attention: surface === "direct-contact" ? "VISIBLE_CONTEXT" : "CLOSED", view: engine.view() };
  } catch {
    return { surface: "unproven", attention: "CLOSED", view: engine.view() };
  }
}

async function deliverOpen(permit: { disposition: string; chatRef?: string }): Promise<string> {
  if (permit.disposition !== "READY" || typeof permit.chatRef !== "string") return permit.disposition;
  const tab = await oneTab();
  if (!tab.ok) return "NO_TAB";
  try {
    const result = await chrome.tabs.sendMessage(tab.id, { type: "open-ref", chatRef: permit.chatRef });
    const disposition = typeof result?.disposition === "string" ? result.disposition : "STALE";
    return /^[A-Z_]{1,40}$/.test(disposition) ? disposition : "STALE";
  } catch {
    return "STALE";
  }
}

function forwardList(raw: unknown): string {
  if (raw == null) return "EMPTY";
  if (!engine.view().settings.collectionEnabled) return "COLLECTION_OFF";
  const local = desiredLabel();
  if (local === "") return "LABEL_UNUSABLE";
  const clean = sanitizeListSignal(raw, local);
  if (!clean.ok) {
    listState = clean.reason;
    rememberBridge();
    return clean.reason;
  }
  if (hostLabel === "") {
    ensurePort();
    if (!port) return hostCause || "UNAVAILABLE";
    return helloState === "READY" ? "WAITING_SCOPE" : "CONNECTING";
  }
  if (hostLabel !== local || clean.signal.boundLabel !== hostLabel) {
    scopeState = "SCOPE_MISMATCH";
    rememberBridge();
    return "SCOPE_MISMATCH";
  }
  ensurePort();
  if (!port) return "UNAVAILABLE";
  try {
    const frame: Record<string, unknown> = {
      v: 1,
      kind: "list-signal",
      layout: clean.signal.layout,
      boundLabel: clean.signal.boundLabel,
      matches: clean.signal.matches,
      position: clean.signal.position,
      unread: clean.signal.unread,
      otherChanges: clean.signal.otherChanges
    };
    if (clean.signal.mark) frame.mark = clean.signal.mark;
    if (typeof clean.signal.count === "number") frame.count = clean.signal.count;
    port.postMessage(frame);
  } catch {
    port = null;
    hostCause = "HOST_PROTOCOL";
    holdConnect = true;
    rememberBridge();
    return "HOST_PROTOCOL";
  }
  return "FORWARDED";
}

function noteComposer(state: string): void {
  const frame = composerFrame(state, lastEvent);
  if (!frame) return;
  noteFrame(frame);
}

function noteFrame(frame: Record<string, unknown>): void {
  if (!engine.view().settings.collectionEnabled) return;
  ensurePort();
  if (!port) return;
  try {
    port.postMessage(frame);
  } catch {
    port = null;
    hostCause = "HOST_PROTOCOL";
    holdConnect = true;
    rememberBridge();
  }
}

async function sendSurface() {
  const token = engine.view().binding?.visibleHeader ?? "";
  const tab = await oneTab();
  if (!tab.ok || token === "") return closedSurface();
  try {
    const raw = await chrome.tabs.sendMessage(tab.id, { type: "do-send-surface", boundToken: token });
    return acceptSurface(raw);
  } catch {
    return closedSurface();
  }
}

async function oneTab(): Promise<{ ok: true; id: number } | { ok: false; error: string }> {
  const tabs = await chrome.tabs.query({ url: __BRIDGE_HOSTS__ });
  if (tabs.length !== 1 || tabs[0].id == null) {
    return { ok: false, error: tabs.length === 0 ? "no-matching-tab" : "ambiguous-tab" };
  }
  return { ok: true, id: tabs[0].id };
}
