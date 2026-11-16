// Bounded delta over message keys. Text is not stored.
// A chat switch, a reconnect, stale order, or unproven identity drops the
// cache instead of reusing it. The cap is a bound, not a quality score.

export const DELTA_CAP = 40;

export type DeltaIdentity = "proven" | "unproven" | "stale" | "reconnected";

export type DeltaCache = {
  scope: string;
  keys: string[];
};

export type DeltaReason = "ok" | "empty" | "cap" | "scope-switch" | "identity" | "stale" | "reconnect";

export type DeltaResult = {
  cache: DeltaCache;
  added: string[];
  invalidated: boolean;
  reason: DeltaReason;
};

const KEY = /^[A-Za-z0-9:._-]{1,80}$/;

export function emptyDelta(): DeltaCache {
  return { scope: "", keys: [] };
}

export function applyDelta(
  cache: DeltaCache,
  input: { scope: string; keys: readonly string[]; identity: DeltaIdentity }
): DeltaResult {
  const had = cache.scope !== "" || cache.keys.length > 0;
  if (input.identity !== "proven") {
    const reason: DeltaReason =
      input.identity === "stale" ? "stale" : input.identity === "reconnected" ? "reconnect" : "identity";
    return { cache: emptyDelta(), added: [], invalidated: had, reason };
  }
  const scope = input.scope;
  const keys = input.keys.filter((key) => KEY.test(key));
  if (scope === "" || !KEY.test(scope)) {
    return { cache: emptyDelta(), added: [], invalidated: had, reason: "identity" };
  }
  if (cache.scope !== "" && cache.scope !== scope) {
    const fresh = keys.slice(0, DELTA_CAP);
    return { cache: { scope, keys: fresh }, added: fresh, invalidated: true, reason: "scope-switch" };
  }
  const known = new Set(cache.keys);
  const added: string[] = [];
  for (const key of keys) {
    if (known.has(key) || added.includes(key)) continue;
    if (cache.keys.length + added.length >= DELTA_CAP) {
      return { cache: { scope, keys: [...cache.keys, ...added] }, added, invalidated: false, reason: "cap" };
    }
    added.push(key);
  }
  return {
    cache: { scope, keys: [...cache.keys, ...added] },
    added,
    invalidated: false,
    reason: added.length === 0 ? "empty" : "ok"
  };
}
