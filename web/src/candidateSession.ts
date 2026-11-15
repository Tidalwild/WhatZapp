// Session-local row handles. The key is the element object. A slot test id
// and the row's visible text are not keys. The handle dies when the element
// is disconnected or its subtree changes, so a recycled node cannot keep a
// stale route. Handles are not wake targets and do not open a chat.

const HANDLE = /^h-[0-9a-f]{16}$/;

type Held = {
  id: string;
  testId: string | null;
  observer: MutationObserver;
};

const held = new WeakMap<Element, Held>();

export function holdCandidate(row: Element, mint: () => string): string | null {
  if (!row.isConnected) return null;
  const testId = row.getAttribute("data-testid");
  const current = held.get(row);
  if (current && current.testId === testId) return current.id;
  current?.observer.disconnect();
  const id = mint();
  if (!HANDLE.test(id)) return null;
  const Observer = row.ownerDocument.defaultView?.MutationObserver;
  if (!Observer) return null;
  const observer = new Observer(() => {
    dropCandidate(row);
  });
  observer.observe(row, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["data-testid"]
  });
  held.set(row, { id, testId, observer });
  return id;
}

export function candidateLive(row: Element, handle: string): boolean {
  const current = held.get(row);
  if (!current || current.id !== handle) return false;
  if (!row.isConnected || row.getAttribute("data-testid") !== current.testId) {
    dropCandidate(row);
    return false;
  }
  return true;
}

export function dropCandidate(row: Element): void {
  const current = held.get(row);
  current?.observer.disconnect();
  held.delete(row);
}
