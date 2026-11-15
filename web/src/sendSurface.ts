// Live send-surface reader.
// Composer emptiness uses the same header and composer names the reader already
// accepts. An open contact drawer is checked only for the exact labels 手機,
// 電話, and 電話號碼. Their values are not read. A missing label is not an
// enrolled identity.
// One measured outgoing row carried aria-label "已讀" and an image role whose
// accessible name contains "read". A row with both is excluded as outgoing.
// tail-out, tail-in, alignment, a self prefix, and a missing status stay
// unproven. A later row is quote-structure when it quotes the own body of an
// earlier outgoing-excluded row, with a quoted-message subtree, a button named
// exactly with that text, and a 4-letter 引用 control. That is the shape of
// the quote. It is not proof the later row was sent by the other person: an
// outgoing reply can quote the same text before a read receipt. Pending, sent,
// unread, and missing status do not fill that gap. The count is the rows
// passed in, not a pane-wide direction. The classifier does not return message
// text.

import { ENGLISH_QUOTE_LABEL, PHONE_FIELD_LABELS, QUOTE_LABEL_LENGTH, QUOTE_MARK, READ_RECEIPT_LABEL } from "./observedLocales.js";
import type { ProbeOptions } from "./probe.js";
import { visible } from "./probe.js";
import { locateReportedFrame } from "./reportedBinding.js";

export const CALIBRATION_OUTGOING_MARKER = "fixture-outgoing-marker";

export type RowStatus = "outgoing-excluded" | "quote-structure" | "unproven";

export type RowExclusion = {
  excluded: number;
  quoteStructure: number;
  unproven: number;
};

export type SendSurface = {
  composer: "empty" | "occupied" | "unmeasured";
  identity: "drawer-closed" | "phone-label-absent" | "phone-label-present";
  direction: "unproven";
  outgoingCompared: false;
  exclusion: RowExclusion;
};

const PHONE_LABELS = PHONE_FIELD_LABELS;
const READ_NAME = "read";
const READ_LABEL = READ_RECEIPT_LABEL;
const PANEL = "conversation-panel-wrapper";

export function closedSurface(): SendSurface {
  return {
    composer: "unmeasured",
    identity: "drawer-closed",
    direction: "unproven",
    outgoingCompared: false,
    exclusion: { excluded: 0, quoteStructure: 0, unproven: 0 }
  };
}

export function visibleSetIsOutgoing(exclusion: RowExclusion): boolean {
  return exclusion.excluded > 0 && exclusion.quoteStructure === 0 && exclusion.unproven === 0;
}

export function acceptSurface(raw: unknown): SendSurface {
  if (!raw || typeof raw !== "object") return closedSurface();
  const value = raw as Partial<SendSurface>;
  const composer = value.composer === "empty" || value.composer === "occupied" ? value.composer : "unmeasured";
  const identity =
    value.identity === "phone-label-absent" || value.identity === "phone-label-present"
      ? value.identity
      : "drawer-closed";
  const exclusion = countFrom(value.exclusion);
  return { composer, identity, direction: "unproven", outgoingCompared: false, exclusion };
}

export function readSendSurface(doc: Document, boundToken: string, options: ProbeOptions): SendSurface {
  const frame = locateReportedFrame(doc, options);
  const agreed = frame !== null && frame.token === boundToken;
  let composer: SendSurface["composer"] = "unmeasured";
  if (agreed && frame) {
    const value = (frame.composer.textContent ?? "").replace(/\s+/g, " ").trim();
    composer = value.length === 0 ? "empty" : "occupied";
  }
  const drawers = [...doc.querySelectorAll('[data-testid="chat-info-drawer"]')].filter((node) => visible(node, options));
  let identity: SendSurface["identity"] = "drawer-closed";
  if (drawers.length === 1) {
    identity = phoneLabelVisible(drawers[0], options) ? "phone-label-present" : "phone-label-absent";
  }
  const exclusion = agreed && frame ? countPanel(frame.header, options) : { excluded: 0, quoteStructure: 0, unproven: 0 };
  return { composer, identity, direction: "unproven", outgoingCompared: false, exclusion };
}

export function countRowExclusion(doc: Document, boundToken: string, options: ProbeOptions): RowExclusion {
  const frame = locateReportedFrame(doc, options);
  if (frame === null || frame.token !== boundToken) return { excluded: 0, quoteStructure: 0, unproven: 0 };
  return countPanel(frame.header, options);
}

export function rowStatus(row: Element): Exclude<RowStatus, "quote-structure"> {
  if (imageNamed(row, READ_NAME) && ariaLabelled(row, READ_LABEL)) return "outgoing-excluded";
  return "unproven";
}

export function classifyContainers(rows: readonly Element[]): RowStatus[] {
  const known = new Set<string>();
  const result: RowStatus[] = [];
  for (const row of rows) {
    if (rowStatus(row) === "outgoing-excluded") {
      result.push("outgoing-excluded");
      for (const body of ownBodies(row)) known.add(body);
      continue;
    }
    result.push(quotesEarlierOutgoing(row, known) ? "quote-structure" : "unproven");
  }
  return result;
}

function countFrom(raw: unknown): RowExclusion {
  if (!raw || typeof raw !== "object") return { excluded: 0, quoteStructure: 0, unproven: 0 };
  const value = raw as Partial<RowExclusion>;
  return { excluded: whole(value.excluded), quoteStructure: whole(value.quoteStructure), unproven: whole(value.unproven) };
}

function whole(value: unknown): number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 10000 ? value : 0;
}

function countPanel(header: Element, options: ProbeOptions): RowExclusion {
  const panel = header.closest(`[data-testid="${PANEL}"]`);
  if (!panel) return { excluded: 0, quoteStructure: 0, unproven: 0 };
  const rows = [...panel.querySelectorAll('[data-testid="msg-container"]')].filter((node) => visible(node, options));
  let excluded = 0;
  let quoteStructure = 0;
  let unproven = 0;
  for (const status of classifyContainers(rows)) {
    if (status === "outgoing-excluded") excluded += 1;
    else if (status === "quote-structure") quoteStructure += 1;
    else unproven += 1;
  }
  return { excluded, quoteStructure, unproven };
}

function imageNamed(row: Element, name: string): boolean {
  const nodes = row.getAttribute("role") === "img" ? [row] : [];
  for (const node of [...nodes, ...row.querySelectorAll('[role="img"]')]) {
    const label = (node.getAttribute("aria-label") ?? node.getAttribute("alt") ?? "").trim();
    if (label.includes(name)) return true;
  }
  return false;
}

function ariaLabelled(row: Element, label: string): boolean {
  if ((row.getAttribute("aria-label") ?? "").trim() === label) return true;
  for (const node of row.querySelectorAll("[aria-label]")) {
    if ((node.getAttribute("aria-label") ?? "").trim() === label) return true;
  }
  return false;
}

function ownBodies(row: Element): string[] {
  const bodies: string[] = [];
  for (const node of row.querySelectorAll('[data-testid="selectable-text"]')) {
    if (node.closest('[data-testid="quoted-message"]')) continue;
    const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
    if (text !== "") bodies.push(text);
  }
  return bodies;
}

function quotesEarlierOutgoing(row: Element, known: ReadonlySet<string>): boolean {
  if (known.size === 0 || !citeControl(row)) return false;
  for (const quote of row.querySelectorAll('[data-testid="quoted-message"]')) {
    for (const node of quote.querySelectorAll('[data-testid="selectable-text"]')) {
      const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
      if (known.has(text) && buttonNamed(row, text)) return true;
    }
  }
  return false;
}

function buttonNamed(row: Element, text: string): boolean {
  for (const button of row.querySelectorAll("button")) {
    const label = (button.getAttribute("aria-label") ?? "").trim();
    const name = label !== "" ? label : (button.textContent ?? "").replace(/\s+/g, " ").trim();
    if (name === text) return true;
  }
  return false;
}

function citeControl(row: Element): boolean {
  for (const button of row.querySelectorAll("button")) {
    const label = (button.getAttribute("aria-label") ?? "").trim();
    if (label === ENGLISH_QUOTE_LABEL) return true;
    if (label.length === QUOTE_LABEL_LENGTH && label.includes(QUOTE_MARK) && /^[\p{L}]+$/u.test(label)) return true;
  }
  return false;
}

function phoneLabelVisible(drawer: Element, options: ProbeOptions): boolean {
  for (const node of drawer.querySelectorAll("*")) {
    if (node.childElementCount !== 0) continue;
    if (!visible(node, options)) continue;
    const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
    if (PHONE_LABELS.has(text)) return true;
  }
  return false;
}
