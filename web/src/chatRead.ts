import { CLOCK_PERIOD_PREFIXES, PHONE_HISTORY_CONTROL } from "./observedLocales.js";
import { visible, type ProbeOptions } from "./probe.js";
import { locateReportedFrame } from "./reportedBinding.js";

const TOKEN = /^[A-Za-z0-9._-]{1,40}$/;
const TIME = new RegExp(
  `^(?:(?:${CLOCK_PERIOD_PREFIXES.join("|")})\\s*)?(?:[01]?\\d|2[0-3])[:：][0-5]\\d(?:\\s?[AP]M)?$`,
  "i"
);
const WEEKDAY =
  /^(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday|星期[一二三四五六日天])(?:\s+[01]?\d[:：][0-5]\d(?:\s?[AP]M)?)?$/i;
const MAX_SCROLLS = 30;
const QUIET_MS = 80;
const SETTLE_CAP_MS = 350;
const PHONE_HISTORY = PHONE_HISTORY_CONTROL;
const PANEL = "conversation-panel-wrapper";
const MESSAGES = "conversation-panel-messages";
const CONTAINER = "msg-container";
const MEDIA = new Set(["document-thumb", "document-detail", "pdf-icon"]);
const LIMIT =
  "Each message container is one row, keyed by the data-id on the nearest conv-msg wrapper inside the conversation panel. The same id stays one occurrence when a later window omits ids in the middle. Different ids stay distinct when the time and text match. Containers with no wrapper id are counted apart from that total. Order is the document order of those ids, not timestamp order. A window that reverses two known ids keeps both and marks order unproven. historyComplete stays false. The phone-history control is not the start of the chat.";

export type ReadDirection = "unknown";
export type OccurrenceJoin = "none" | "single" | "stable-id" | "sequence" | "uncertain";

export type ReadRow = {
  timeText: string;
  text: string;
  direction: ReadDirection;
  senderLabel: string;
};

type Held = ReadRow & { occurrenceId: string };

export type ReadCoverage = {
  historyComplete: false;
  phoneHistoryBoundary: boolean;
  occurrenceJoin: OccurrenceJoin;
  uiTopReached: boolean;
  continuityGap: boolean;
  renderGap: boolean;
  orderProven: boolean;
  samples: number;
  scrolls: number;
  capped: boolean;
  keyed: number;
  unkeyed: number;
  unique: number;
  duplicates: number;
  withoutText: number;
  unparsed: number;
  stopped: string;
  limit: string;
};

export type ChatReadReport = {
  disposition: string;
  header: string;
  rows: ReadRow[];
  coverage: ReadCoverage;
};

type Sample = {
  disposition: string;
  header: string;
  rows: ReadRow[];
  pane: Element | null;
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  withoutText: number;
  unparsed: number;
  keyed: Held[];
  unkeyed: Held[];
  phoneHistory: boolean;
};

export type CollectHooks = {
  settle?: (pane: Element) => Promise<void>;
  maxScrolls?: number;
};

export function sampleOpenChat(doc: Document, boundLabel: string, options: ProbeOptions): Sample {
  const bound = boundLabel.trim();
  const empty = blankSample("NOT_BOUND");
  if (!TOKEN.test(bound)) return empty;
  const frame = locateReportedFrame(doc, options);
  if (!frame) return blankSample("HEADER_UNPROVEN");
  if (frame.token !== bound) return blankSample("HEADER_MISMATCH");
  const panel = findBoundPanel(doc, frame.header, frame.composer, options);
  if (!panel) return { ...blankSample("PANE_UNPROVEN"), header: bound };
  const messages = messageRoot(panel, options);
  if (!messages) return { ...blankSample("PANE_UNPROVEN"), header: bound };
  const pane = scrollTarget(messages, options);
  if (!pane) return { ...blankSample("PANE_UNPROVEN"), header: bound };
  const parsed = readPanel(messages, panel, bound, options);
  return {
    disposition: "VISIBLE",
    header: bound,
    rows: parsed.keyed.map(publish),
    pane,
    scrollTop: pane.scrollTop,
    scrollHeight: pane.scrollHeight,
    clientHeight: pane.clientHeight,
    withoutText: parsed.withoutText,
    unparsed: parsed.unparsed,
    keyed: parsed.keyed,
    unkeyed: parsed.unkeyed,
    phoneHistory: seesPhoneHistory(panel, options)
  };
}

export async function collectOpenChat(
  doc: Document,
  boundLabel: string,
  options: ProbeOptions,
  hooks: CollectHooks = {}
): Promise<ChatReadReport> {
  const first = sampleOpenChat(doc, boundLabel, options);
  if (first.disposition !== "VISIBLE" || !first.pane) {
    return reportFrom(first, [], 0, false, first.disposition === "VISIBLE" ? "visible-window" : stoppedFor(first.disposition));
  }
  const steps: Sample[] = [first];
  const pane = first.pane;
  const max = hooks.maxScrolls ?? MAX_SCROLLS;
  let scrolls = 0;
  let capped = false;
  let stopped = "visible-window";
  while (pane.isConnected && scrolls < max) {
    const beforeTop = pane.scrollTop;
    const beforeHeight = pane.scrollHeight;
    if (pane.scrollHeight <= pane.clientHeight + 1) {
      stopped = "no-overflow";
      break;
    }
    if (beforeTop <= 0) {
      stopped = "scroll-top";
      break;
    }
    const stepPx = Math.max(40, Math.floor(pane.clientHeight * 0.7) || 40);
    const nextTop = Math.max(0, beforeTop - stepPx);
    if (nextTop === beforeTop) {
      stopped = "no-movement";
      break;
    }
    pane.scrollTop = nextTop;
    scrolls += 1;
    await (hooks.settle ?? quietSettle)(pane);
    if (!pane.isConnected) {
      stopped = "pane-lost";
      break;
    }
    const next = sampleOpenChat(doc, boundLabel, options);
    if (next.disposition !== "VISIBLE" || next.pane !== pane) {
      stopped = next.header === "" ? "chat-switch" : "pane-changed";
      break;
    }
    steps.push(next);
    if (pane.scrollTop <= 0 && pane.scrollHeight <= beforeHeight) {
      stopped = "scroll-top";
      break;
    }
  }
  if (scrolls >= max && (stopped === "visible-window" || stopped === "scroll-top") && pane.scrollTop > 0) {
    capped = true;
    stopped = "sample-cap";
  }
  return reportFrom(steps[0], steps, scrolls, capped, stopped);
}

export function isTimestamp(value: string): boolean {
  const text = value.trim();
  if (text.length === 0 || text.length > 40) return false;
  return TIME.test(text) || WEEKDAY.test(text);
}

export function quietSettle(pane: Element): Promise<void> {
  const view = pane.ownerDocument.defaultView;
  if (!view) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    let quietTimer = 0;
    let capTimer = 0;
    const finish = () => {
      if (done) return;
      done = true;
      observer.disconnect();
      view.clearTimeout(quietTimer);
      view.clearTimeout(capTimer);
      resolve();
    };
    const observer = new view.MutationObserver(() => {
      view.clearTimeout(quietTimer);
      quietTimer = view.setTimeout(finish, QUIET_MS);
    });
    observer.observe(pane, { subtree: true, childList: true, characterData: true, attributes: true });
    quietTimer = view.setTimeout(finish, QUIET_MS);
    capTimer = view.setTimeout(finish, SETTLE_CAP_MS);
  });
}

function reportFrom(first: Sample, steps: Sample[], scrolls: number, capped: boolean, stopped: string): ChatReadReport {
  if (first.disposition !== "VISIBLE") {
    return {
      disposition: first.disposition,
      header: first.disposition === "PANE_UNPROVEN" ? first.header : "",
      rows: [],
      coverage: coverage({
        uiTopReached: false,
        continuityGap: false,
        renderGap: false,
        orderProven: false,
        phoneHistoryBoundary: false,
        occurrenceJoin: "none",
        samples: 0,
        scrolls: 0,
        capped: false,
        keyed: 0,
        unkeyed: 0,
        unique: 0,
        duplicates: 0,
        withoutText: 0,
        unparsed: 0,
        stopped
      })
    };
  }
  const merged = accumulate(steps.map((step) => ({ keyed: step.keyed, unkeyed: step.unkeyed })));
  const last = steps[steps.length - 1];
  const uiTopReached = last.scrollTop <= 0 || stopped === "no-overflow" || stopped === "scroll-top";
  const chatSwitch = stopped === "chat-switch";
  const join: OccurrenceJoin = merged.unkeyed > 0 ? "uncertain" : merged.keyed > 0 ? "stable-id" : "none";
  return {
    disposition: chatSwitch ? "CHAT_SWITCH" : "READ",
    header: first.header,
    rows: merged.rows.map(publish),
    coverage: coverage({
      phoneHistoryBoundary: steps.some((step) => step.phoneHistory),
      occurrenceJoin: join,
      uiTopReached,
      continuityGap: merged.renderGap,
      renderGap: merged.renderGap,
      orderProven: !merged.contradicted,
      samples: steps.length,
      scrolls,
      capped,
      keyed: merged.keyed,
      unkeyed: merged.unkeyed,
      unique: merged.keyed,
      duplicates: merged.duplicates,
      withoutText: steps.reduce((sum, step) => sum + step.withoutText, 0),
      unparsed: steps.reduce((sum, step) => sum + step.unparsed, 0),
      stopped
    })
  };
}

function accumulate(windows: Array<{ keyed: Held[]; unkeyed: Held[] }>): {
  rows: Held[];
  keyed: number;
  unkeyed: number;
  duplicates: number;
  renderGap: boolean;
  contradicted: boolean;
} {
  let order: string[] = [];
  const byId = new Map<string, Held>();
  let duplicates = 0;
  let renderGap = false;
  let contradicted = false;
  let unkeyedRows: Held[] = [];
  for (const windowRows of windows) {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const row of windowRows.keyed) {
      if (!row.occurrenceId || seen.has(row.occurrenceId)) {
        duplicates += 1;
        continue;
      }
      seen.add(row.occurrenceId);
      ids.push(row.occurrenceId);
      if (byId.has(row.occurrenceId)) duplicates += 1;
      else byId.set(row.occurrenceId, row);
    }
    const merged = mergeOrder(order, ids);
    order = merged.order;
    if (merged.contradicted) contradicted = true;
    if (merged.interiorGap) renderGap = true;
    const absorbed = absorbUnkeyed(unkeyedRows, windowRows.unkeyed);
    unkeyedRows = absorbed.stored;
    duplicates += absorbed.replays;
  }
  return {
    rows: order.map((id) => byId.get(id)).filter((row): row is Held => row !== undefined),
    keyed: byId.size,
    unkeyed: unkeyedRows.length,
    duplicates,
    renderGap,
    contradicted
  };
}

function mergeOrder(existing: string[], windowIds: string[]): { order: string[]; contradicted: boolean; interiorGap: boolean } {
  const pos = new Map(existing.map((id, index) => [id, index]));
  let prev = -1;
  let contradicted = false;
  for (const id of windowIds) {
    const at = pos.get(id);
    if (at === undefined) continue;
    if (at < prev) contradicted = true;
    else prev = at;
  }
  const known = windowIds.filter((id) => pos.has(id));
  let interiorGap = false;
  if (!contradicted && known.length >= 2) {
    const first = pos.get(known[0]) ?? 0;
    const last = pos.get(known[known.length - 1]) ?? first;
    const present = new Set(known);
    for (let index = first; index <= last; index += 1) {
      if (!present.has(existing[index])) interiorGap = true;
    }
  }
  return { order: spliceNewIds(existing, windowIds), contradicted, interiorGap };
}

function spliceNewIds(existing: string[], windowIds: string[]): string[] {
  const result = [...existing];
  for (let index = 0; index < windowIds.length; index += 1) {
    const id = windowIds[index];
    const pos = new Map(result.map((item, at) => [item, at]));
    if (pos.has(id)) continue;
    let insertAt = result.length;
    for (let later = index + 1; later < windowIds.length; later += 1) {
      const at = pos.get(windowIds[later]);
      if (at !== undefined) {
        insertAt = at;
        break;
      }
    }
    if (insertAt === result.length) {
      for (let earlier = index - 1; earlier >= 0; earlier -= 1) {
        const at = pos.get(windowIds[earlier]);
        if (at !== undefined) {
          insertAt = at + 1;
          break;
        }
      }
    }
    result.splice(insertAt, 0, id);
  }
  return result;
}

function absorbUnkeyed(stored: Held[], incoming: Held[]): { stored: Held[]; replays: number } {
  const available = new Map<string, number>();
  for (const row of stored) available.set(unkeyedKey(row), (available.get(unkeyedKey(row)) ?? 0) + 1);
  const next = [...stored];
  let replays = 0;
  for (const row of incoming) {
    const key = unkeyedKey(row);
    const have = available.get(key) ?? 0;
    if (have > 0) {
      available.set(key, have - 1);
      replays += 1;
      continue;
    }
    next.push(row);
    available.set(key, 0);
  }
  return { stored: next, replays };
}

function unkeyedKey(row: Held): string {
  return `${row.timeText}\u0000${row.text}\u0000${row.senderLabel}`;
}

function publish(row: Held): ReadRow {
  return {
    timeText: row.timeText,
    text: row.text,
    direction: "unknown",
    senderLabel: row.senderLabel
  };
}

function findBoundPanel(doc: Document, header: Element, composer: Element, options: ProbeOptions): Element | null {
  const panels = [...doc.querySelectorAll(`[data-testid="${PANEL}"]`)].filter(
    (node) => visible(node, options) && !insideGrid(node)
  );
  // The live panel contains the proven header and composer. A fixture panel
  // may instead sit between them. Either way there must be exactly one.
  const containing = panels.filter((node) => node.contains(header) && node.contains(composer));
  if (containing.length === 1) return containing[0];
  if (containing.length > 1) return null;
  const between = panels.filter(
    (node) => !node.contains(header) && !node.contains(composer) && sitsBetween(header, node, composer)
  );
  return between.length === 1 ? between[0] : null;
}

function messageRoot(panel: Element, options: ProbeOptions): Element | null {
  const roots = [...panel.querySelectorAll(`[data-testid="${MESSAGES}"]`)].filter(
    (node) => visible(node, options) && panel.contains(node) && !insideGrid(node)
  );
  if (roots.length > 1) return null;
  return roots.length === 1 ? roots[0] : panel;
}

function sitsBetween(header: Element, node: Element, composer: Element): boolean {
  const following = node.ownerDocument.defaultView?.Node.DOCUMENT_POSITION_FOLLOWING ?? 4;
  const preceding = node.ownerDocument.defaultView?.Node.DOCUMENT_POSITION_PRECEDING ?? 2;
  const afterHeader = (header.compareDocumentPosition(node) & following) !== 0;
  const beforeComposer = (composer.compareDocumentPosition(node) & preceding) !== 0;
  return afterHeader && beforeComposer;
}

function readPanel(
  root: Element,
  panel: Element,
  token: string,
  options: ProbeOptions
): { keyed: Held[]; unkeyed: Held[]; withoutText: number; unparsed: number } {
  const keyed: Held[] = [];
  const unkeyed: Held[] = [];
  let withoutText = 0;
  let unparsed = 0;
  for (const container of messageContainers(root, options)) {
    const read = readContainer(container, token, panel, options);
    if (!read) {
      unparsed += 1;
      continue;
    }
    if (read.text === "") {
      withoutText += 1;
      continue;
    }
    if (read.occurrenceId) keyed.push(read);
    else unkeyed.push(read);
  }
  return { keyed, unkeyed, withoutText, unparsed };
}

function messageContainers(panel: Element, options: ProbeOptions): Element[] {
  return [...panel.querySelectorAll(`[data-testid="${CONTAINER}"]`)].filter((node) => {
    if (!visible(node, options) || insideGrid(node) || !panel.contains(node)) return false;
    const nested = node.parentElement?.closest(`[data-testid="${CONTAINER}"]`);
    return !(nested && panel.contains(nested));
  });
}

function readContainer(container: Element, token: string, panel: Element, options: ProbeOptions): Held | null {
  const parts: string[] = [];
  let senderLabel = "";
  for (const leaf of container.querySelectorAll('[data-testid="selectable-text"]')) {
    if (!visible(leaf, options) || !container.contains(leaf)) continue;
    const text = textOf(leaf);
    if (text === "") continue;
    if (text === token) {
      senderLabel = token;
      continue;
    }
    parts.push(text);
  }
  let text = parts.join(" ").replace(/\s+/g, " ").trim();
  if (hasMedia(container)) text = text === "" ? "[document]" : `${text} [document]`;
  return {
    timeText: clockIn(container, options),
    text,
    direction: "unknown",
    senderLabel,
    occurrenceId: wrapperId(container, panel)
  };
}

function wrapperId(container: Element, panel: Element): string {
  let node: Element | null = container.parentElement;
  while (node && node !== panel) {
    if (panel.contains(node) && isConvMsg(node)) return cleanId(node.getAttribute("data-id"));
    node = node.parentElement;
  }
  return "";
}

function isConvMsg(node: Element): boolean {
  const testId = node.getAttribute("data-testid") ?? "";
  return testId.startsWith("conv-msg-") && node.hasAttribute("data-id");
}

function cleanId(raw: string | null): string {
  const id = (raw ?? "").trim();
  if (id.length < 1 || id.length > 180 || /\s/.test(id)) return "";
  return id;
}

function clockIn(container: Element, options: ProbeOptions): string {
  const meta = [...container.querySelectorAll('[data-testid="msg-meta"]')].find((node) => container.contains(node) && visible(node, options));
  if (!meta) return "";
  const leaf = leaves(meta, options).find((node) => isTimestamp(textOf(node)));
  return leaf ? textOf(leaf) : "";
}

function hasMedia(container: Element): boolean {
  return [...container.querySelectorAll("[data-testid]")].some((node) => MEDIA.has((node.getAttribute("data-testid") ?? "").toLowerCase()));
}

function seesPhoneHistory(panel: Element, options: ProbeOptions): boolean {
  return leaves(panel, options).some((leaf) => textOf(leaf) === PHONE_HISTORY);
}

function leaves(root: Element, options: ProbeOptions): Element[] {
  const found: Element[] = [];
  const walk = (node: Element) => {
    if (!visible(node, options) || editable(node)) return;
    if (node.childElementCount === 0) {
      if (textOf(node) !== "") found.push(node);
      return;
    }
    for (const child of node.children) walk(child);
  };
  walk(root);
  return found;
}

function scrollTarget(node: Element, options: ProbeOptions): Element | null {
  const found = scrollers(node, options);
  if (found.length > 1) return null;
  if (found.length === 1) return found[0];
  return node;
}

function scrollers(node: Element, options: ProbeOptions): Element[] {
  const found: Element[] = [];
  const walk = (current: Element) => {
    if (!visible(current, options) || isGrid(current)) return;
    if (scrolls(current)) found.push(current);
    for (const child of current.children) walk(child);
  };
  walk(node);
  return found;
}

function scrolls(node: Element): boolean {
  const style = node.ownerDocument.defaultView?.getComputedStyle(node);
  const overflow = `${style?.overflowY ?? ""} ${style?.overflow ?? ""}`;
  return /\b(?:auto|scroll)\b/.test(overflow);
}

function blankSample(disposition: string): Sample {
  return {
    disposition,
    header: "",
    rows: [],
    pane: null,
    scrollTop: 0,
    scrollHeight: 0,
    clientHeight: 0,
    withoutText: 0,
    unparsed: 0,
    keyed: [],
    unkeyed: [],
    phoneHistory: false
  };
}

function coverage(values: Omit<ReadCoverage, "historyComplete" | "limit">): ReadCoverage {
  return { historyComplete: false, limit: LIMIT, ...values };
}

function stoppedFor(disposition: string): string {
  if (disposition === "HEADER_MISMATCH" || disposition === "HEADER_UNPROVEN") return "chat-switch";
  if (disposition === "PANE_UNPROVEN") return "pane-unproven";
  if (disposition === "NOT_BOUND") return "not-bound";
  return disposition.toLowerCase();
}

function insideGrid(node: Element): boolean {
  let current: Element | null = node;
  while (current) {
    if (isGrid(current)) return true;
    current = current.parentElement;
  }
  return false;
}

function isGrid(node: Element): boolean {
  return node.getAttribute("role") === "grid";
}

function editable(node: Element): boolean {
  const editableValue = node.getAttribute("contenteditable");
  return editableValue === "" || editableValue === "true";
}

function textOf(node: Element): string {
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}
