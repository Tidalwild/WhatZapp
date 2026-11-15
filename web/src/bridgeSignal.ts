import type { ListSignal, UnreadMark } from "./listSignal.js";

const TOKEN = /^[A-Za-z0-9._-]{1,40}$/;
const KEYS = new Set(["layout", "boundLabel", "matches", "position", "unread", "mark", "count", "otherChanges"]);
const MARKS = new Set<UnreadMark>(["absent", "dot", "count", "unknown", "ambiguous"]);

export type SanitizeResult =
  | { ok: true; signal: ListSignal }
  | { ok: false; reason: "UNTRUSTED_FIELD" | "SCOPE_MISMATCH" | "EMPTY" };

/** Keep the chat-list contract and nothing else. Extra keys are refused. */
export function sanitizeListSignal(raw: unknown, expectedLabel: string): SanitizeResult {
  if (raw == null) return { ok: false, reason: "EMPTY" };
  if (typeof raw !== "object") return { ok: false, reason: "UNTRUSTED_FIELD" };
  const record = raw as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (!KEYS.has(key)) return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  if (record.layout !== "chat-list-contract") return { ok: false, reason: "UNTRUSTED_FIELD" };
  if (typeof record.boundLabel !== "string" || !TOKEN.test(record.boundLabel)) {
    return { ok: false, reason: "SCOPE_MISMATCH" };
  }
  if (expectedLabel === "" || record.boundLabel !== expectedLabel) {
    return { ok: false, reason: "SCOPE_MISMATCH" };
  }
  if (!count(record.matches) || !count(record.otherChanges)) {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  const matches = record.matches;
  if (matches !== 1) {
    const partial: ListSignal = {
      layout: "chat-list-contract",
      boundLabel: record.boundLabel,
      matches,
      position: null,
      unread: null,
      otherChanges: record.otherChanges
    };
    return { ok: true, signal: partial };
  }
  if (!count(record.position)) return { ok: false, reason: "UNTRUSTED_FIELD" };
  // null means the row was seen and no boolean unread mark is claimed.
  // It is not a false unread mark and it must not become a wake.
  if (record.unread !== null && typeof record.unread !== "boolean") {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  const mark = record.mark;
  if (mark !== undefined && (typeof mark !== "string" || !MARKS.has(mark as UnreadMark))) {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  if (mark === undefined && record.count !== undefined) return { ok: false, reason: "UNTRUSTED_FIELD" };
  if (mark === "dot" && (record.unread !== null || record.count !== undefined)) {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  if ((mark === "unknown" || mark === "ambiguous") && (record.unread !== null || record.count !== undefined)) {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  if (mark === "absent" && record.unread !== false) return { ok: false, reason: "UNTRUSTED_FIELD" };
  if (mark === "absent" && record.count !== undefined && record.count !== 0) {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  if (mark === "count" && (record.unread !== null || !positiveCount(record.count))) {
    return { ok: false, reason: "UNTRUSTED_FIELD" };
  }
  const signal: ListSignal = {
    layout: "chat-list-contract",
    boundLabel: record.boundLabel,
    matches: 1,
    position: record.position,
    unread: record.unread === null ? null : record.unread,
    otherChanges: record.otherChanges
  };
  if (mark !== undefined) signal.mark = mark as UnreadMark;
  if (mark === "count" && positiveCount(record.count)) signal.count = record.count;
  if (mark === "absent" && record.count === 0) signal.count = 0;
  return { ok: true, signal };
}

function positiveCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 && value <= 9999;
}

function count(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 10000;
}
