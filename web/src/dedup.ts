import { sha256Hex } from "./crypto.js";

export type AlignResult = {
  fresh: string[];
  duplicateCount: number;
  continuityGap: boolean;
};

export async function fingerprint(row: { sender: string; text: string; timeText: string }): Promise<string> {
  const content = await sha256Hex(`text:${row.text}`);
  return [b64(row.sender), b64(row.timeText), b64(content)].join("|");
}

export function align(previous: string[], snapshot: string[]): AlignResult {
  if (snapshot.length === 0) return { fresh: [], duplicateCount: 0, continuityGap: false };
  if (previous.length === 0) return { fresh: snapshot, duplicateCount: 0, continuityGap: false };
  let overlap = Math.min(previous.length, snapshot.length);
  while (overlap > 0 && !same(previous.slice(-overlap), snapshot.slice(0, overlap))) overlap -= 1;
  if (overlap > 0) {
    return { fresh: snapshot.slice(overlap), duplicateCount: overlap, continuityGap: false };
  }
  if (containsContiguous(previous, snapshot)) {
    return { fresh: [], duplicateCount: snapshot.length, continuityGap: false };
  }
  return { fresh: snapshot, duplicateCount: 0, continuityGap: true };
}

export function containsContiguous(haystack: string[], needle: string[]): boolean {
  if (needle.length === 0) return true;
  if (needle.length > haystack.length) return false;
  for (let start = 0; start <= haystack.length - needle.length; start += 1) {
    if (same(haystack.slice(start, start + needle.length), needle)) return true;
  }
  return false;
}

function same(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function b64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
