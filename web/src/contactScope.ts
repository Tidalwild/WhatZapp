// Who a reply may consider. Default is nobody.
// A display label is not a verified recipient. Groups stay out unless
// the operator sets groups to include. This module does not send.

export type ContactKind = "direct" | "group" | "unknown";
export type ScopeMode = "off" | "allowlist" | "direct";

export type ContactScope = {
  mode: ScopeMode;
  allow: string[];
  deny: string[];
  groups: "exclude" | "include";
  maxReplies: number;
};

export const DEFAULT_SCOPE: ContactScope = {
  mode: "off",
  allow: [],
  deny: [],
  groups: "exclude",
  maxReplies: 0
};

const LABEL = /^[A-Za-z0-9._-]{1,40}$/;

export function normalizeScope(value: Partial<ContactScope> | null | undefined): ContactScope {
  const mode = value?.mode === "allowlist" || value?.mode === "direct" ? value.mode : "off";
  const groups = value?.groups === "include" ? "include" : "exclude";
  const max = value?.maxReplies;
  const maxReplies = typeof max === "number" && Number.isInteger(max) && max > 0 && max <= 10000 ? max : 0;
  return { mode, allow: labels(value?.allow), deny: labels(value?.deny), groups, maxReplies };
}

export function contactInScope(scope: ContactScope, contact: { label: string; kind: ContactKind }): boolean {
  const policy = normalizeScope(scope);
  if (policy.mode === "off") return false;
  const label = contact.label.trim();
  if (!LABEL.test(label) || policy.deny.includes(label)) return false;
  if (contact.kind === "group") {
    return policy.groups === "include" && (policy.mode === "direct" || policy.allow.includes(label));
  }
  if (contact.kind !== "direct") return false;
  if (policy.mode === "direct") return true;
  return policy.allow.includes(label);
}

function labels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item === "string" && LABEL.test(item)) seen.add(item);
    if (seen.size === 200) break;
  }
  return [...seen];
}
