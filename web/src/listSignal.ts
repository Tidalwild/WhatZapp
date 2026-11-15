import { UNREAD_COUNT_LABEL, UNREAD_DOT_LABELS } from "./observedLocales.js";
import { visible, type ProbeOptions } from "./probe.js";

export type UnreadMark = "absent" | "dot" | "count" | "unknown" | "ambiguous";

export type ListSignal = {
  layout: "chat-list-contract";
  boundLabel: string;
  matches: number;
  position: number | null;
  unread: boolean | null;
  mark?: UnreadMark;
  count?: number;
  otherChanges: number;
};

export type ListMemory = {
  seen: boolean;
  others: string[];
};

const TOKEN = /^[A-Za-z0-9._-]{1,40}$/;

// Live shape reported from one official accessibility read on 2026-11-12.
// The bound chat may not be the open chat. The list is a grid outside main. The bound
// row has no accessible name. A generic descendant is named exactly with
// the allowlist token. Gridcell names are longer and are not labels.
// No unread node was present, so this path does not invent one.
const GENERIC_TAGS = new Set(["DIV", "SPAN"]);

export function emptyMemory(): ListMemory {
  return { seen: false, others: [] };
}

export function readChatListSignal(
  doc: Document,
  boundLabel: string,
  memory: ListMemory,
  options: ProbeOptions
): { signal: ListSignal; memory: ListMemory } {
  const label = boundLabel.trim();
  const blank = signal(label, 0, null, null, 0);
  if (label === "") return { signal: blank, memory };
  const fixture = fixtureList(doc, options);
  if (fixture) return finish(label, memory, collectFixture(fixture, label, options), "fixture");
  const grid = liveGrid(doc, label, options);
  if (!grid) return { signal: blank, memory };
  return finish(label, memory, collectLive(grid, label, options), "live");
}

function signal(
  boundLabel: string,
  matches: number,
  position: number | null,
  unread: boolean | null,
  otherChanges: number,
  mark?: UnreadMark,
  count?: number
): ListSignal {
  const value: ListSignal = { layout: "chat-list-contract", boundLabel, matches, position, unread, otherChanges };
  if (mark) value.mark = mark;
  if (count !== undefined) value.count = count;
  return value;
}

function finish(
  label: string,
  memory: ListMemory,
  read: {
    matched: Array<{ index: number; unread: boolean | null; mark?: UnreadMark; count?: number }>;
    others: string[];
    unreadable: number;
  },
  kind: "fixture" | "live"
): { signal: ListSignal; memory: ListMemory } {
  if (read.unreadable > 0) {
    return { signal: signal(label, 0, null, null, read.unreadable), memory };
  }
  const otherChanges = memory.seen
    ? kind === "live"
      ? multisetDiff(memory.others, read.others)
      : diffCount(memory.others, read.others)
    : 0;
  const next = { seen: true, others: read.others };
  if (read.matched.length !== 1) {
    return { signal: signal(label, read.matched.length, null, null, otherChanges), memory: next };
  }
  const only = read.matched[0];
  return {
    signal: signal(label, 1, only.index, only.unread, otherChanges, only.mark, only.count),
    memory: next
  };
}

function fixtureList(doc: Document, options: ProbeOptions): Element | null {
  // Synthetic pages only. Live WhatsApp Web does not use this marker.
  const marked = [...doc.querySelectorAll("[data-bridge-list='chats']")].filter((node) => visible(node, options));
  return marked.length === 1 ? marked[0] : null;
}

function collectFixture(region: Element, boundLabel: string, options: ProbeOptions): {
  matched: Array<{ index: number; unread: boolean | null }>;
  others: string[];
  unreadable: number;
} {
  const rows = [...region.querySelectorAll("[data-bridge-row='chat']")].filter((node) => visible(node, options));
  const matched: Array<{ index: number; unread: boolean | null }> = [];
  const others: string[] = [];
  let unreadable = 0;
  let index = 0;
  for (const row of rows) {
    const label = fixtureLabel(row);
    if (label === null) {
      unreadable += 1;
      continue;
    }
    const unread = fixtureUnread(row);
    if (label === boundLabel) matched.push({ index, unread });
    else others.push(`${digest(label)}\t${unread ? "1" : "0"}`);
    index += 1;
  }
  others.sort();
  return { matched, others, unreadable };
}

function fixtureLabel(row: Element): string | null {
  const marked = [...row.querySelectorAll("[data-bridge-label]")].filter(
    (node) => node.closest("[data-bridge-row='chat']") === row
  );
  if (marked.length > 1) return null;
  if (marked.length === 1) return bounded(marked[0].textContent ?? "");
  const aria = row.getAttribute("aria-label");
  if (aria === null) return null;
  const text = bounded(aria);
  if (text === null || text.includes(" ")) return null;
  return text;
}

function bounded(value: string): string | null {
  const text = normalize(value);
  if (text === "" || text.length > 80) return null;
  return text;
}

function fixtureUnread(row: Element): boolean {
  if (row.querySelector("[data-bridge-unread]") !== null) return true;
  for (const node of row.querySelectorAll("[aria-label]")) {
    if (node === row) continue;
    if ((node.getAttribute("aria-label") ?? "").trim().toLowerCase() === "unread") return true;
  }
  return false;
}

function liveGrid(doc: Document, boundLabel: string, options: ProbeOptions): Element | null {
  const grids = [...doc.querySelectorAll("[role='grid']")].filter((node) => {
    if (!visible(node, options)) return false;
    return node.closest("[role='main']") === null;
  });
  if (grids.length !== 1) return null;
  // The reported list name is not the bound token. A grid named exactly
  // with that token is a different node, so it is not this list.
  if (authorName(grids[0]) === boundLabel) return null;
  return grids[0];
}

function collectLive(grid: Element, boundLabel: string, options: ProbeOptions): {
  matched: Array<{ index: number; unread: boolean | null; mark?: UnreadMark; count?: number }>;
  others: string[];
  unreadable: number;
} {
  const matched: Array<{ index: number; unread: boolean | null; mark?: UnreadMark; count?: number }> = [];
  const others: string[] = [];
  let index = 0;
  for (const row of liveRows(grid, options)) {
    if (hasExactGeneric(row, boundLabel, options)) {
      const seen = liveMark(row, options);
      matched.push({ index, unread: seen.unread, mark: seen.mark, count: seen.count });
    } else {
      others.push(otherDigest(row, options));
    }
    index += 1;
  }
  others.sort();
  return { matched, others, unreadable: 0 };
}

// The 2026-11-12 manual mark was a span, data-testid icon-unread-count,
// aria-label exactly 未讀, no role, and empty text, inside the row's trailing
// gridcell. That empty dot is not the numbered badge.
//
// The 2026-11-13 live numbered badge was one visible span, the same test id,
// no role, aria-label exactly 1個未讀訊息, and visible text 1. Its gridcell
// ancestry was not captured, so a count does not require a trailing cell.
// Only the digit 1 was seen live. A larger positive integer with the same
// label template is accepted in fixtures and fail-closed if the label and
// the visible text disagree. The label text is not copied into the signal.
const DOT_LABELS = new Set<string>(UNREAD_DOT_LABELS);
const DOT_TESTID = "icon-unread-count";
const COUNT_LABEL = UNREAD_COUNT_LABEL;

export function readRowMark(row: Element, options: ProbeOptions): { unread: boolean | null; mark: UnreadMark; count?: number } {
  return liveMark(row, options);
}

function liveMark(row: Element, options: ProbeOptions): { unread: boolean | null; mark: UnreadMark; count?: number } {
  const related = badgeNodes(row).filter((node) => badgeRelated(node));
  if (related.length === 0) {
    const cells = rowCells(row, options);
    if (cells.length === 0) return { unread: null, mark: "unknown" };
    return { unread: false, mark: "absent", count: 0 };
  }
  const counts = related
    .map((node) => exactCount(node, options))
    .filter((value): value is number => value !== null);
  if (counts.length === 1 && related.length === 1) return { unread: null, mark: "count", count: counts[0] };
  const exact = related.filter((node) => exactDot(node, options));
  if (exact.length === 1 && related.length === 1 && trailingCell(exact[0], row, options)) {
    return { unread: null, mark: "dot" };
  }
  return { unread: null, mark: "ambiguous" };
}

function exactCount(node: Element, options: ProbeOptions): number | null {
  if (node.tagName !== "SPAN") return null;
  if (node.getAttribute("data-testid") !== DOT_TESTID) return null;
  if (node.hasAttribute("role")) return null;
  if (!visible(node, options)) return null;
  const matched = COUNT_LABEL.exec(node.getAttribute("aria-label") ?? "");
  if (!matched) return null;
  if (normalize(node.textContent ?? "") !== matched[1]) return null;
  const count = Number(matched[1]);
  if (!Number.isInteger(count) || count < 1 || count > 9999) return null;
  return count;
}

function badgeNodes(row: Element): Element[] {
  return [...row.querySelectorAll("*")].filter((node) => owningRow(node) === row);
}

function badgeRelated(node: Element): boolean {
  if (node.getAttribute("data-testid") === DOT_TESTID) return true;
  const label = node.getAttribute("aria-label");
  if (DOT_LABELS.has(label ?? "")) return true;
  // Any other casing is related enough to refuse an "absent" mark. It is not
  // the exact public-source dot label, so it still fails closed.
  return (label ?? "").trim().toLowerCase() === "unread";
}

function exactDot(node: Element, options: ProbeOptions): boolean {
  if (node.tagName !== "SPAN") return false;
  if (node.getAttribute("data-testid") !== DOT_TESTID) return false;
  if (!DOT_LABELS.has(node.getAttribute("aria-label") ?? "")) return false;
  if (node.hasAttribute("role")) return false;
  if (!visible(node, options)) return false;
  return normalize(node.textContent ?? "") === "";
}

function trailingCell(node: Element, row: Element, options: ProbeOptions): boolean {
  const cell = node.closest("[role='gridcell']");
  if (!cell || owningRow(cell) !== row) return false;
  const cells = rowCells(row, options);
  return cells.length > 0 && cells[cells.length - 1] === cell;
}

function rowCells(row: Element, options: ProbeOptions): Element[] {
  return [...row.querySelectorAll("[role='gridcell']")].filter((cell) => visible(cell, options) && owningRow(cell) === row);
}

function liveRows(grid: Element, options: ProbeOptions): Element[] {
  return [...grid.querySelectorAll("[role='row']")].filter((node) => {
    if (!visible(node, options)) return false;
    return node.parentElement?.closest("[role='grid']") === grid;
  });
}

function hasExactGeneric(row: Element, boundLabel: string, options: ProbeOptions): boolean {
  for (const node of labelCandidates(row, options)) {
    if (shortName(node) === boundLabel) return true;
  }
  return false;
}

function labelCandidates(row: Element, options: ProbeOptions): Element[] {
  const found: Element[] = [];
  for (const node of row.querySelectorAll("span, div, [role='generic']")) {
    if (!isGeneric(node) || !visible(node, options)) continue;
    if (owningRow(node) !== row) continue;
    found.push(node);
  }
  return found;
}

function isGeneric(node: Element): boolean {
  const role = node.getAttribute("role");
  if (role === "generic") return true;
  if (role !== null) return false;
  return GENERIC_TAGS.has(node.tagName);
}

function owningRow(node: Element): Element | null {
  return node.parentElement?.closest("[role='row']") ?? null;
}

function otherDigest(row: Element, options: ProbeOptions): string {
  const names: string[] = [];
  for (const node of labelCandidates(row, options)) {
    const name = shortName(node);
    if (name !== null) names.push(name);
  }
  names.sort();
  if (names.length > 0) return digest(names.join("\u001f"));
  let cells = 0;
  for (const cell of row.querySelectorAll("[role='gridcell']")) {
    if (!visible(cell, options) || owningRow(cell) !== row) continue;
    cells += 1;
  }
  return digest(`cells:${cells}`);
}

function shortName(node: Element): string | null {
  if (node.hasAttribute("aria-label") || node.hasAttribute("aria-labelledby")) {
    const authored = authorName(node);
    return authored !== null && TOKEN.test(authored) ? authored : null;
  }
  if (node.childElementCount > 0) return null;
  const raw = node.textContent ?? "";
  if (raw.length > 40) return null;
  const text = normalize(raw);
  return TOKEN.test(text) ? text : null;
}

function authorName(node: Element): string | null {
  if (node.hasAttribute("aria-labelledby")) {
    const ids = (node.getAttribute("aria-labelledby") ?? "").trim().split(/\s+/).filter(Boolean);
    if (ids.length === 0) return null;
    const parts: string[] = [];
    for (const id of ids) {
      const raw = node.ownerDocument.getElementById(id)?.textContent ?? "";
      if (raw.length > 40) return null;
      const text = normalize(raw);
      if (text.length === 0 || text.length > 40) return null;
      parts.push(text);
    }
    const combined = normalize(parts.join(" "));
    if (combined.length === 0 || combined.length > 40) return null;
    return combined;
  }
  if (node.hasAttribute("aria-label")) {
    const raw = node.getAttribute("aria-label") ?? "";
    if (raw.length > 40) return null;
    const text = normalize(raw);
    if (text.length > 40) return null;
    return text;
  }
  return null;
}

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function digest(value: string): string {
  let hash = 2166136261;
  for (const char of value) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function diffCount(previous: string[], current: string[]): number {
  const left = new Map<string, string>();
  for (const item of previous) {
    const [id, unread] = item.split("\t");
    left.set(id, unread);
  }
  const seen = new Set<string>();
  let changes = 0;
  for (const item of current) {
    const [id, unread] = item.split("\t");
    seen.add(id);
    if (!left.has(id) || left.get(id) !== unread) changes += 1;
  }
  for (const id of left.keys()) if (!seen.has(id)) changes += 1;
  return changes;
}

function multisetDiff(previous: string[], current: string[]): number {
  const left = tally(previous);
  const right = tally(current);
  let changes = 0;
  for (const key of new Set([...left.keys(), ...right.keys()])) {
    changes += Math.abs((left.get(key) ?? 0) - (right.get(key) ?? 0));
  }
  return changes;
}

function tally(values: string[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return counts;
}
