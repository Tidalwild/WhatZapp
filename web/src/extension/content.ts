import { collectOpenChat } from "../chatRead.js";
import { emptyMemory, readChatListSignal, type ListMemory } from "../listSignal.js";
import { readProbe } from "../probe.js";
import { readReportedHeader } from "../reportedBinding.js";
import { inspectOneUnread } from "../attentionInspect.js";
import { readListChange } from "../listChange.js";
import { emptyPaneMemory, observeOpenPane, type PaneMemory } from "../openPane.js";
import { readPersonRoster, routeRoster, openResolvedRow, type RefMap } from "../personWatch.js";
import { readContactSurface } from "../contactSurface.js";
import { countRowExclusion, readSendSurface } from "../sendSurface.js";

let watching = false;
let observer: MutationObserver | null = null;
let timer = 0;
let boundLabel = "";
let watchMode = "messages";
let listMemory: ListMemory = emptyMemory();
let personRefs: RefMap = {};
let personSerial = 0;
let lastListKey = "";
let paneMemory: PaneMemory = emptyPaneMemory();
let paneSent = 0;
let paneTimer = 0;

document.documentElement.dataset.bridgeProbe = "ready";

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "do-peek") {
    sendResponse({ header: peekHeader() });
    return;
  }
  if (message?.type === "do-scan") {
    sendResponse({ snapshot: readProbe(document, { requireLayout: true }) });
    return;
  }
  if (message?.type === "do-send-surface") {
    const boundToken = typeof message.boundToken === "string" ? message.boundToken : "";
    sendResponse(readSendSurface(document, boundToken, { requireLayout: true }));
    return;
  }
  if (message?.type === "do-read") {
    const boundLabel = typeof message.boundLabel === "string" ? message.boundLabel : "";
    void collectOpenChat(document, boundLabel, { requireLayout: true }).then((report) => {
      // Count only the rows still mounted after the reader scroll. That is a
      // different sample from the keyed history, and a quote is not direction.
      sendResponse({ ...report, exclusion: countRowExclusion(document, boundLabel, { requireLayout: true }) });
    });
    return true;
  }
  if (message?.type === "inspect-unread") {
    const result = inspectOneUnread(document, { requireLayout: true }, mintHandle);
    sendResponse(result);
    return;
  }
  if (message?.type === "attention-gate") {
    const surface = readContactSurface(document, { requireLayout: true }).surface;
    sendResponse({ surface, attention: surface === "direct-contact" ? "VISIBLE_CONTEXT" : "CLOSED" });
    return;
  }
  if (message?.type === "open-ref") {
    const chatRef = typeof message.chatRef === "string" ? message.chatRef : "";
    sendResponse(openResolvedRow(document, personRefs, chatRef, { requireLayout: true }));
    return;
  }
  if (message?.type === "watch") {
    if (message.on) {
      boundLabel = typeof message.boundLabel === "string" ? message.boundLabel : "";
      watchMode = message.mode === "metadata" ? "metadata" : "messages";
      startWatching();
    } else stopWatching();
    sendResponse({ ok: true });
  }
});

chrome.runtime.sendMessage({ type: "get-watch" }, (response) => {
  if (response?.watch) {
    boundLabel = typeof response?.boundLabel === "string" ? response.boundLabel : "";
    watchMode = response?.mode === "metadata" ? "metadata" : "messages";
    startWatching();
  }
});

function peekHeader(): string {
  const probe = readProbe(document, { requireLayout: true });
  if (probe.layout === "probe-contract" && probe.header.trim() !== "") return probe.header.trim();
  return readReportedHeader(document, { requireLayout: true });
}

function startWatching(): void {
  watching = true;
  observer?.disconnect();
  // Settled mutations are the page-change input. They are not a FreeDesktop
  // notification. When a chat is bound, the list signal names only that row.
  observer = new MutationObserver(() => schedule());
  // Watch the open page. The list reader uses the reported grid outside main,
  // or the synthetic fixture marker. It does not choose a chat.
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
  schedule();
}

function stopWatching(): void {
  watching = false;
  boundLabel = "";
  watchMode = "messages";
  personRefs = {};
  personSerial = 0;
  lastListKey = "";
  paneMemory = emptyPaneMemory();
  paneSent = 0;
  window.clearTimeout(paneTimer);
  listMemory = emptyMemory();
  observer?.disconnect();
  observer = null;
  window.clearTimeout(timer);
}

function mintHandle(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `h-${[...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function mintPersonRef(): string {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  personSerial += 1;
  if (personSerial > 0xffffffff) personSerial = 1;
  return `ref-${[...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function schedule(): void {
  if (!watching) return;
  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    const read = boundLabel === "" ? null : readChatListSignal(document, boundLabel, listMemory, { requireLayout: true });
    if (read) listMemory = read.memory;
    const routed = routeRoster(readPersonRoster(document, { requireLayout: true }), personRefs, mintPersonRef);
    personRefs = routed.refs;
    const change = readListChange(document, { requireLayout: true });
    if (change) {
      const key = `${change.mark}:${change.count}`;
      if (key !== lastListKey) {
        lastListKey = key;
        chrome.runtime.sendMessage({ type: "list-change", mark: change.mark, count: change.count });
      }
    }
    const pane = observeOpenPane(document, paneMemory, { requireLayout: true });
    if (pane.disposition === "HINT" && pane.generation !== paneSent) {
      paneSent = pane.generation;
      const generation = pane.generation;
      chrome.runtime.sendMessage({ type: "pane-hint", generation });
      window.clearTimeout(paneTimer);
      paneTimer = window.setTimeout(() => {
        if (!watching || paneSent !== generation) return;
        chrome.runtime.sendMessage({ type: "pane-hint", generation });
      }, 2000);
    }
    if (routed.hints.length > 0) {
      chrome.runtime.sendMessage({ type: "person-roster", hints: routed.hints });
    }
    if (watchMode === "metadata") {
      chrome.runtime.sendMessage({ type: "list-signal", listSignal: read?.signal ?? null });
      return;
    }
    chrome.runtime.sendMessage({
      type: "snapshot",
      snapshot: readProbe(document, { requireLayout: true }),
      listSignal: read?.signal
    });
  }, 50);
}
