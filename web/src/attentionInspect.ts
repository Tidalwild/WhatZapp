// One current unread row, rechecked immediately before it is opened.
// The open drawer is then classified. Message text is not read. A group is
// not a context read. A direct contact stays an ambiguous visible context,
// not a verified recipient.

import { holdCandidate, candidateLive } from "./candidateSession.js";
import { readContactSurface, type ContactSurface } from "./contactSurface.js";
import { unreadRows } from "./listChange.js";
import { CONTACT_INFO_BUTTON_PREFIX, ENGLISH_GROUP_HEADING, ENGLISH_PROFILE_BUTTON, GROUP_INFO_BUTTON_PREFIX } from "./observedLocales.js";
import { visibleEnglishGroupComposer } from "./reportedBinding.js";
import { visible, type ProbeOptions } from "./probe.js";

const CONTACT_PREFIX = CONTACT_INFO_BUTTON_PREFIX;
const GROUP_PREFIX = GROUP_INFO_BUTTON_PREFIX;

export type InspectResult = {
  disposition: "QUIET" | "STALE" | "GROUP_CLOSE" | "DIRECT_CONTEXT" | "UNPROVEN" | "INFO_UNOPENED";
  identity: "AMBIGUOUS" | "UNPROVEN";
  messagesCollected: false;
};

export function inspectOneUnread(doc: Document, options: ProbeOptions, mint: () => string): InspectResult {
  const rows = unreadRows(doc, options);
  if (rows === null || rows.length === 0) return closed("QUIET");
  for (const row of rows) {
    const handle = holdCandidate(row, mint);
    if (handle === null || !candidateLive(row, handle)) continue;
    if (row.querySelector("[role='textbox']") !== null) return closed("UNPROVEN");
    if (typeof (row as HTMLElement).click === "function") (row as HTMLElement).click();
    return classifyOpened(doc, options);
  }
  return closed("STALE");
}

function classifyOpened(doc: Document, options: ProbeOptions): InspectResult {
  if (visibleEnglishGroupComposer(doc, options)) {
    const surface = readContactSurface(doc, options).surface;
    if (surface === "direct-contact") return closed("UNPROVEN");
    return fromSurface("group");
  }
  let surface = readContactSurface(doc, options).surface;
  if (surface === "unproven") {
    const buttons = infoButtons(doc, options);
    if (buttons.length !== 1) return closed("INFO_UNOPENED");
    if (typeof (buttons[0] as HTMLElement).click === "function") (buttons[0] as HTMLElement).click();
    surface = readContactSurface(doc, options).surface;
  }
  return fromSurface(surface);
}

function fromSurface(surface: ContactSurface): InspectResult {
  if (surface === "group") return { disposition: "GROUP_CLOSE", identity: "UNPROVEN", messagesCollected: false };
  if (surface === "direct-contact") return { disposition: "DIRECT_CONTEXT", identity: "AMBIGUOUS", messagesCollected: false };
  return closed("UNPROVEN");
}

function infoButtons(doc: Document, options: ProbeOptions): Element[] {
  const found: Element[] = [];
  for (const node of doc.querySelectorAll("button, [role='button']")) {
    if (!visible(node, options)) continue;
    if (node.closest("[role='row'], [data-testid='msg-container'], [data-testid='selectable-text']") !== null) continue;
    const name = (node.getAttribute("aria-label") || node.getAttribute("title") || "").replace(/\s+/g, " ").trim();
    if (name.startsWith(CONTACT_PREFIX) || name.startsWith(GROUP_PREFIX) || name === ENGLISH_PROFILE_BUTTON || name === ENGLISH_GROUP_HEADING) found.push(node);
  }
  return found;
}

function closed(disposition: "QUIET" | "STALE" | "UNPROVEN" | "INFO_UNOPENED"): InspectResult {
  return { disposition, identity: "UNPROVEN", messagesCollected: false };
}
