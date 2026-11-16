// Opt-in context for the bound chat. Off until the operator enables it.
// Fact text is untrusted data. It is not a scope change and not a send.

export const TOKEN_BUDGET = 2000;
export const CONTEXT_TTL_MS = 4 * 60 * 60 * 1000;

export type ContextGrant = {
  enabled: boolean;
  scopeId: string;
  source: "operator";
  enabledAtMillis: number;
  expiresAtMillis: number;
  revoked: boolean;
};

export type ContextFact = {
  scopeId: string;
  text: string;
  source: string;
};

export type ContextAssembly = {
  status: "off" | "revoked" | "stale" | "wrong-chat" | "abstain" | "ready";
  text: string;
  scopeId: string;
  source: "operator" | "";
  fresh: boolean;
  budget: number;
  dropped: number;
};

const SCOPE = /^[A-Za-z0-9._:-]{1,80}$/;

export function emptyContext(): ContextGrant {
  return { enabled: false, scopeId: "", source: "operator", enabledAtMillis: 0, expiresAtMillis: 0, revoked: false };
}

export function normalizeContext(value: Partial<ContextGrant> | null | undefined): ContextGrant {
  if (value == null || value.enabled !== true || value.revoked === true) {
    const empty = emptyContext();
    if (value?.revoked === true && typeof value.scopeId === "string") empty.scopeId = SCOPE.test(value.scopeId) ? value.scopeId : "";
    empty.revoked = value?.revoked === true;
    return empty;
  }
  if (!SCOPE.test(value.scopeId ?? "") || value.source !== "operator") return emptyContext();
  if (typeof value.enabledAtMillis !== "number" || typeof value.expiresAtMillis !== "number") return emptyContext();
  if (value.expiresAtMillis <= value.enabledAtMillis) return emptyContext();
  return {
    enabled: true,
    scopeId: value.scopeId ?? "",
    source: "operator",
    enabledAtMillis: value.enabledAtMillis,
    expiresAtMillis: value.expiresAtMillis,
    revoked: false
  };
}

export function assembleContext(
  grant: ContextGrant,
  facts: readonly ContextFact[],
  now: number,
  chatScopeId: string
): ContextAssembly {
  const base: ContextAssembly = {
    status: "off",
    text: "",
    scopeId: "",
    source: "",
    fresh: false,
    budget: TOKEN_BUDGET,
    dropped: 0
  };
  if (!grant.enabled || grant.revoked) {
    base.status = grant.revoked ? "revoked" : "off";
    return base;
  }
  if (now >= grant.expiresAtMillis) {
    base.status = "stale";
    return base;
  }
  if (grant.scopeId === "" || grant.scopeId !== chatScopeId) {
    base.status = "wrong-chat";
    return base;
  }
  const kept: string[] = [];
  let dropped = 0;
  for (const fact of facts) {
    if (fact.scopeId !== chatScopeId || fact.text === "") {
      dropped += 1;
      continue;
    }
    kept.push(fact.text);
  }
  const text = budget(kept);
  if (text === "") {
    return { ...base, status: "abstain", scopeId: chatScopeId, source: "operator", dropped };
  }
  return {
    status: "ready",
    text,
    scopeId: chatScopeId,
    source: "operator",
    fresh: true,
    budget: TOKEN_BUDGET,
    dropped
  };
}

function budget(parts: string[]): string {
  const used: string[] = [];
  let size = 0;
  for (const part of parts) {
    const extra = part.length + (used.length > 0 ? 1 : 0);
    if (size + extra > TOKEN_BUDGET) break;
    used.push(part);
    size += extra;
  }
  return used.join("\n");
}
