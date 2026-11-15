// Person-list observation. A row is a person only when the fixture marks
// data-bridge-kind="person". A live list row has no measured type cue:
// the positional data-testid form list-item-<position> is not an identity
// key, and avatar count or absence is not a person or group mark. Those
// rows stay unproven and are not a wake. A duplicate token, an own row,
// or an unproven kind does not receive a ref. The hint carries the opaque
// ref, not the token.

import { readRowMark, type UnreadMark } from "./listSignal.js";
import { visible, type ProbeOptions } from "./probe.js";

export type PersonKind = "person" | "group" | "channel" | "status" | "community" | "unproven";

export type RosterRow = {
  kind: PersonKind;
  token: string | null;
  own: boolean;
  mark: UnreadMark;
  count: number | null;
  index: number;
};

export type PersonHint = {
  chatRef: string;
  mark: "count" | "absent";
  count: number;
};

export type RefMap = Record<string, string>;

export type RouteBlock = "GROUP" | "CHANNEL" | "STATUS" | "COMMUNITY" | "UNPROVEN" | "DUPLICATE_NAME" | "OWN" | "AMBIGUOUS";

const KINDS = new Set<PersonKind>(["person", "group", "channel", "status", "community"]);
const TOKEN = /^[A-Za-z0-9._-]{1,40}$/;
const SLOT = /^list-item-[0-9]+$/;
const REF = /^ref-[0-9a-f]{16}$/;

export function readPersonRoster(doc: Document, options: ProbeOptions): RosterRow[] {
  const rows: RosterRow[] = [];
  let index = 0;
  for (const row of rosterRows(doc, options)) {
    rows.push(classifyRow(row, index, options));
    index += 1;
  }
  return rows;
}

export function routeRoster(
  rows: readonly RosterRow[],
  refs: RefMap,
  mint: () => string
): { hints: PersonHint[]; refs: RefMap; blocked: RouteBlock[] } {
  const next: RefMap = { ...refs };
  const tokens = new Map<string, number>();
  for (const row of rows) {
    if (row.kind === "person" && !row.own && row.token) tokens.set(row.token, (tokens.get(row.token) ?? 0) + 1);
  }
  const hints: PersonHint[] = [];
  const blocked: RouteBlock[] = [];
  for (const row of rows) {
    const reason = blockReason(row, tokens);
    if (reason) {
      blocked.push(reason);
      continue;
    }
    const token = row.token;
    if (!token) continue;
    let ref = next[token];
    if (ref === undefined) {
      ref = mint();
      if (!REF.test(ref) || ref === token) continue;
      next[token] = ref;
    }
    if (!REF.test(ref)) continue;
    if (row.mark === "count" && row.count !== null) hints.push({ chatRef: ref, mark: "count", count: row.count });
    if (row.mark === "absent") hints.push({ chatRef: ref, mark: "absent", count: 0 });
  }
  return { hints, refs: next, blocked };
}

export function resolveOpen(
  rows: readonly RosterRow[],
  refs: RefMap,
  chatRef: string
): { ok: true } | { ok: false; reason: RouteBlock | "UNKNOWN_REF" } {
  if (!REF.test(chatRef)) return { ok: false, reason: "UNKNOWN_REF" };
  const token = Object.entries(refs).find((entry) => entry[1] === chatRef)?.[0];
  if (!token) return { ok: false, reason: "UNKNOWN_REF" };
  const matches = rows.filter((row) => row.token === token);
  if (matches.length !== 1) return { ok: false, reason: matches.length > 1 ? "DUPLICATE_NAME" : "UNKNOWN_REF" };
  const row = matches[0];
  if (row.own) return { ok: false, reason: "OWN" };
  if (row.kind !== "person") return { ok: false, reason: blockReason(row, new Map()) ?? "UNPROVEN" };
  return { ok: true };
}

export function openResolvedRow(
  doc: Document,
  refs: RefMap,
  chatRef: string,
  options: ProbeOptions
): { disposition: string } {
  const decision = resolveOpen(readPersonRoster(doc, options), refs, chatRef);
  if (!decision.ok) return { disposition: decision.reason };
  const token = Object.entries(refs).find((entry) => entry[1] === chatRef)?.[0];
  if (!token) return { disposition: "UNKNOWN_REF" };
  const rows = rosterRows(doc, options).filter((row) => {
    const seen = classifyRow(row, 0, options);
    return seen.kind === "person" && !seen.own && seen.token === token;
  });
  if (rows.length !== 1) return { disposition: rows.length === 0 ? "STALE" : "DUPLICATE_NAME" };
  const row = rows[0];
  if (row.querySelector("[role='textbox']") !== null) return { disposition: "UNSAFE_ROW" };
  if (typeof (row as HTMLElement).click === "function") (row as HTMLElement).click();
  return { disposition: "OPENED" };
}

function blockReason(row: RosterRow, tokens: ReadonlyMap<string, number>): RouteBlock | null {
  if (row.kind === "group") return "GROUP";
  if (row.kind === "channel") return "CHANNEL";
  if (row.kind === "status") return "STATUS";
  if (row.kind === "community") return "COMMUNITY";
  if (row.kind !== "person") return "UNPROVEN";
  if (row.own) return "OWN";
  if (!row.token || (tokens.get(row.token) ?? 0) !== 1) return row.token ? "DUPLICATE_NAME" : "AMBIGUOUS";
  return null;
}

function rosterRows(doc: Document, options: ProbeOptions): Element[] {
  const fixture = [...doc.querySelectorAll("[data-bridge-list='chats']")].filter((node) => visible(node, options));
  if (fixture.length === 1) {
    return [...fixture[0].querySelectorAll("[data-bridge-row='chat']")].filter((node) => visible(node, options));
  }
  const grids = [...doc.querySelectorAll("[role='grid']")].filter((node) => visible(node, options) && node.closest("[role='main']") === null);
  if (grids.length !== 1) return [];
  return [...grids[0].querySelectorAll("[role='row']")].filter((node) => {
    if (!visible(node, options)) return false;
    return node.parentElement?.closest("[role='grid']") === grids[0];
  });
}

function classifyRow(row: Element, index: number, options: ProbeOptions): RosterRow {
  const marked = row.getAttribute("data-bridge-kind");
  const kind = marked !== null && KINDS.has(marked as PersonKind) ? (marked as PersonKind) : "unproven";
  const seen = readRowMark(row, options);
  return {
    kind,
    token: oneToken(row),
    own: row.getAttribute("data-bridge-own") === "1",
    mark: seen.mark,
    count: seen.count ?? (seen.mark === "absent" ? 0 : null),
    index
  };
}

function oneToken(row: Element): string | null {
  const names = new Set<string>();
  for (const node of row.querySelectorAll("span, div")) {
    if (node.closest("[data-bridge-row='chat'], [role='row']") !== row) continue;
    if (node.closest("[role='gridcell']") !== null) continue;
    if (node.getAttribute("data-testid")) continue;
    if (node.childElementCount > 0) continue;
    const text = (node.textContent ?? "").replace(/\s+/g, " ").trim();
    if (!TOKEN.test(text) || /^[0-9]+$/.test(text) || SLOT.test(text)) continue;
    names.add(text);
  }
  if (names.size !== 1) return null;
  return [...names][0];
}
