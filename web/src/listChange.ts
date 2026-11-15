// Visible numbered-unread total. The result is a count, not a row, a name,
// or a slot. Dots are not counts. The host posts a targetless list-change
// only after this total rises.

import { readRowMark } from "./listSignal.js";
import { visible, type ProbeOptions } from "./probe.js";

const COUNT_MAX = 9999;

export function unreadRows(doc: Document, options: ProbeOptions): Element[] | null {
  const rows = listRows(doc, options);
  if (rows === null) return null;
  return rows.filter((row) => readRowMark(row, options).mark === "count");
}

export function readListChange(
  doc: Document,
  options: ProbeOptions
): { mark: "count" | "absent"; count: number } | null {
  const rows = listRows(doc, options);
  if (rows === null) return null;
  let total = 0;
  for (const row of rows) {
    const seen = readRowMark(row, options);
    if (seen.mark !== "count" || seen.count === undefined) continue;
    total += seen.count;
    if (total > COUNT_MAX) return null;
  }
  if (total === 0) return { mark: "absent", count: 0 };
  return { mark: "count", count: total };
}

function listRows(doc: Document, options: ProbeOptions): Element[] | null {
  const grids = [...doc.querySelectorAll("[role='grid']")].filter(
    (node) => visible(node, options) && node.closest("[role='main']") === null
  );
  if (grids.length !== 1) return null;
  return [...grids[0].querySelectorAll("[role='row']")].filter((node) => {
    if (!visible(node, options)) return false;
    return node.parentElement?.closest("[role='grid']") === grids[0];
  });
}
