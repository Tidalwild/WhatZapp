// Attention classification of an already-open info drawer.
// A direct contact is the official contact-info heading, not a natural
// person as opposed to a business, and not a send identity. The list row
// that led here is not re-derived from a name, a slot, or an avatar.
// An unlabeled phone-shaped line is not read and is not enrolled.

import type { ProbeOptions } from "./probe.js";
import { visible } from "./probe.js";
import { candidateLive } from "./candidateSession.js";
import { CONTACT_DRAWER_HEADINGS, GROUP_DRAWER_HEADINGS } from "./observedLocales.js";

export type ContactSurface = "direct-contact" | "group" | "unproven";

const CONTACT_HEADINGS = CONTACT_DRAWER_HEADINGS;
const GROUP_HEADINGS = GROUP_DRAWER_HEADINGS;
const DRAWER = "chat-info-drawer";
const GROUP_PARTS = ["group-info-header", "group-info-drawer-body"];

export function readContactSurface(doc: Document, options: ProbeOptions): { surface: ContactSurface } {
  const drawers = [...doc.querySelectorAll(`[data-testid="${DRAWER}"]`)].filter((node) => visible(node, options));
  if (drawers.length !== 1) return { surface: "unproven" };
  const drawer = drawers[0];
  const contact = labelNodes(drawer, options).filter((node) => CONTACT_HEADINGS.some((heading) => exactText(node, heading))).length === 1;
  const group = groupMarked(drawer, options);
  if (contact && group) return { surface: "unproven" };
  if (group) return { surface: "group" };
  if (contact) return { surface: "direct-contact" };
  return { surface: "unproven" };
}

export function allowAttentionRead(
  surface: ContactSurface,
  row: Element,
  handle: string
): "READ_ATTENTION" | "CLOSE" | "UNPROVEN" | "STALE_CANDIDATE" {
  if (!candidateLive(row, handle)) return "STALE_CANDIDATE";
  if (surface === "group") return "CLOSE";
  if (surface !== "direct-contact") return "UNPROVEN";
  return "READ_ATTENTION";
}

function labelNodes(drawer: Element, options: ProbeOptions): Element[] {
  const found: Element[] = [];
  for (const node of drawer.querySelectorAll("*")) {
    if (!visible(node, options)) continue;
    if (node.closest("[data-testid='msg-container'], [data-testid='selectable-text']") !== null) continue;
    found.push(node);
  }
  return found;
}

function groupMarked(drawer: Element, options: ProbeOptions): boolean {
  if (labelNodes(drawer, options).some((node) => GROUP_HEADINGS.some((heading) => exactText(node, heading)))) return true;
  return [...drawer.querySelectorAll("[data-testid]")].some((node) => {
    if (!visible(node, options)) return false;
    return GROUP_PARTS.includes(node.getAttribute("data-testid") ?? "");
  });
}

function exactText(node: Element, heading: string): boolean {
  const named = (node.getAttribute("aria-label") ?? "").replace(/\s+/g, " ").trim();
  return named === heading || ownText(node) === heading;
}

function ownText(node: Element): string {
  let text = "";
  for (const child of node.childNodes) {
    if (child.nodeType === 3) text += child.textContent ?? "";
  }
  return text.replace(/\s+/g, " ").trim();
}
