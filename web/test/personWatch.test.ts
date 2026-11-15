import { Window } from "happy-dom";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { emptyMemory, readChatListSignal } from "../src/listSignal.js";
import { readPersonRoster, resolveOpen, routeRoster, openResolvedRow, type RefMap } from "../src/personWatch.js";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

function mintFrom(start = 0): () => string {
  let n = start;
  return () => {
    n += 1;
    return `ref-${n.toString(16).padStart(16, "0")}`;
  };
}

function badge(count: number): string {
  return `<span data-testid="icon-unread-count" aria-label="${count}個未讀訊息">${count}</span>`;
}

function gridRow(token: string, kind: string, extra = ""): string {
  return `<div role="row" data-bridge-kind="${kind}"><span>${token}</span><div role="gridcell">${extra}</div></div>`;
}

describe("person roster", () => {
  it("routes distinct person rows by opaque ref and leaves the contact-a list signal alone", () => {
    const body = `<div role="grid" aria-label="Chats">${gridRow("contact-a", "person", badge(1))}${gridRow("person-b", "person", badge(2))}</div>`;
    const doc = page(body);
    const roster = readPersonRoster(doc, { requireLayout: false });
    const routed = routeRoster(roster, {}, mintFrom());
    expect(routed.hints).toEqual([
      { chatRef: "ref-0000000000000001", mark: "count", count: 1 },
      { chatRef: "ref-0000000000000002", mark: "count", count: 2 }
    ]);
    expect(JSON.stringify(routed.hints)).not.toContain("contact-a");
    expect(JSON.stringify(routed.hints)).not.toContain("person-b");
    expect(JSON.stringify(routed.hints)).not.toContain("個未讀訊息");
    const legacy = readChatListSignal(doc, "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(legacy).toMatchObject({ boundLabel: "contact-a", matches: 1, mark: "count", count: 1 });
    const opened = resolveOpen(roster, routed.refs, routed.hints[1].chatRef);
    expect(opened).toEqual({ ok: true });
  });

  it("fail-closes duplicates, groups, own rows, and an unclassified live row", () => {
    const body = `<div role="grid" aria-label="Chats">
      ${gridRow("person-a", "person", badge(1))}
      ${gridRow("person-a", "person", badge(4))}
      ${gridRow("group-a", "group", badge(3))}
      ${gridRow("channel-a", "channel", badge(1))}
      ${gridRow("status-a", "status")}
      ${gridRow("community-a", "community", badge(1))}
      ${gridRow("person-c", "person", badge(2)).replace("<div", '<div data-bridge-own="1"')}
      <div role="row"><span>contact-a</span><div role="gridcell">${badge(1)}</div></div>
    </div>`;
    const routed = routeRoster(readPersonRoster(page(body), { requireLayout: false }), {}, mintFrom());
    expect(routed.hints).toEqual([]);
    expect(routed.blocked).toEqual(
      expect.arrayContaining(["DUPLICATE_NAME", "GROUP", "CHANNEL", "STATUS", "COMMUNITY", "OWN", "UNPROVEN"])
    );
    expect(JSON.stringify(routed.hints)).not.toContain("person-a");
    expect(JSON.stringify(routed)).not.toContain("group-a");
  });

  it("does not open an ambiguous, duplicate, or reclassified row", () => {
    const one = page(`<div role="grid">${gridRow("person-a", "person", badge(1))}</div>`);
    const first = routeRoster(readPersonRoster(one, { requireLayout: false }), {}, mintFrom());
    const ref = first.hints[0].chatRef;
    const doubled = page(
      `<div role="grid">${gridRow("person-a", "person", badge(1))}${gridRow("person-a", "person", badge(2))}</div>`
    );
    expect(resolveOpen(readPersonRoster(doubled, { requireLayout: false }), first.refs, ref).ok).toBe(false);
    const grouped = page(`<div role="grid">${gridRow("person-a", "group", badge(1))}</div>`);
    const closed = resolveOpen(readPersonRoster(grouped, { requireLayout: false }), first.refs, ref);
    expect(closed).toEqual({ ok: false, reason: "GROUP" });
    const refs: RefMap = { "person-a": ref };
    expect(resolveOpen(readPersonRoster(one, { requireLayout: false }), refs, "ref-ffffffffffffffff").ok).toBe(false);
    const unnamed = page(`<div role="grid"><div role="row" data-bridge-kind="person"><div role="gridcell">${badge(1)}</div></div></div>`);
    const ambiguous = routeRoster(readPersonRoster(unnamed, { requireLayout: false }), {}, mintFrom());
    expect(ambiguous.hints).toEqual([]);
    expect(ambiguous.blocked).toContain("AMBIGUOUS");
  });

  it("opens only the one current person row named by that ref", () => {
    const body = `<div role="grid">${gridRow("contact-a", "person", badge(1))}${gridRow("person-b", "person", badge(2))}</div>`;
    const doc = page(body);
    const routed = routeRoster(readPersonRoster(doc, { requireLayout: false }), {}, mintFrom());
    const clicks: string[] = [];
    for (const row of doc.querySelectorAll("[role='row']")) {
      row.addEventListener("click", () => {
        clicks.push(row.querySelector("span")?.textContent ?? "");
      });
    }
    const opened = openResolvedRow(doc, routed.refs, "ref-0000000000000002", { requireLayout: false });
    expect(opened.disposition).toBe("OPENED");
    expect(clicks).toEqual(["person-b"]);
    expect(openResolvedRow(doc, routed.refs, "ref-ffffffffffffffff", { requireLayout: false }).disposition).toBe("UNKNOWN_REF");
    const group = page(`<div role="grid">${gridRow("person-b", "group", badge(2))}</div>`);
    expect(openResolvedRow(group, routed.refs, "ref-0000000000000002", { requireLayout: false }).disposition).toBe("GROUP");
    const doubled = page(`<div role="grid">${gridRow("person-b", "person", badge(2))}${gridRow("person-b", "person", badge(3))}</div>`);
    expect(openResolvedRow(doubled, routed.refs, "ref-0000000000000002", { requireLayout: false }).disposition).toBe("DUPLICATE_NAME");
    const unsafe = page(`<div role="grid">${gridRow("person-b", "person", badge(2) + "<div role='textbox'></div>")}</div>`);
    expect(openResolvedRow(unsafe, routed.refs, "ref-0000000000000002", { requireLayout: false }).disposition).toBe("UNSAFE_ROW");
    expect(clicks).toEqual(["person-b"]);
  });

  it("rejects the measured list: duplicate slot labels and avatar shape are not a route", () => {
    const cues = JSON.parse(readFileSync(new URL("./fixtures/live-list-cues.json", import.meta.url), "utf8")) as {
      observations: { positiveTypeCue: null; tokenMultiplicity?: number; accessibleImageRoleCount?: number; domImageCount?: number }[];
      listTokenSummary: { roleRowCount: number; distinctIndexTokenCount: number; duplicatedTokenFrequencies: number[] };
    };
    expect(cues.observations.every((row) => row.positiveTypeCue === null)).toBe(true);
    const duplicated = [...cues.listTokenSummary.duplicatedTokenFrequencies].sort((left, right) => right - left);
    expect(duplicated[0]).toBe(cues.observations[0].tokenMultiplicity);
    const uniqueCount = cues.listTokenSummary.distinctIndexTokenCount - duplicated.length;
    const slots: string[] = [];
    duplicated.forEach((count, index) => {
      for (let copy = 0; copy < count; copy += 1) slots.push(`list-item-${index}`);
    });
    for (let index = 0; index < uniqueCount; index += 1) slots.push(`list-item-${duplicated.length + index}`);
    expect(new Set(slots).size).toBe(cues.listTokenSummary.distinctIndexTokenCount);
    expect(slots).toHaveLength(cues.listTokenSummary.roleRowCount);
    const plain = "<img>";
    const avatars = `<div role="img" aria-label="aa"></div><div role="img" aria-label="bb"></div><div role="img" aria-label="cc"></div>`;
    const rows = slots.map((slot, index) => {
      const images = index === 0 ? plain : index === duplicated[0] ? avatars : "";
      return `<div role="row" data-testid="${slot}"><span>${slot}</span><div role="gridcell"><div data-testid="cell-frame-container"><span data-testid="cell-frame-title"></span><span data-testid="cell-frame-primary-detail"></span><span data-testid="chat-list-timestamp"></span><span data-testid="cell-frame-secondary"></span><span data-testid="last-msg-status"></span>${images}</div></div></div>`;
    });
    const doc = page(`<div role="grid">${rows.join("")}</div>`);
    const roster = readPersonRoster(doc, { requireLayout: false });
    expect(roster).toHaveLength(cues.listTokenSummary.roleRowCount);
    expect(roster.every((row) => row.kind === "unproven" && row.token === null)).toBe(true);
    const routed = routeRoster(roster, {}, mintFrom());
    expect(routed.hints).toEqual([]);
    expect(routed.blocked.every((reason) => reason === "UNPROVEN")).toBe(true);
    expect(JSON.stringify(routed)).not.toContain("list-item");
    const clicks: string[] = [];
    for (const row of doc.querySelectorAll("[role='row']")) {
      row.addEventListener("click", () => clicks.push(row.getAttribute("data-testid") ?? ""));
    }
    const forced = openResolvedRow(doc, { "list-item-0": "ref-0000000000000001" }, "ref-0000000000000001", { requireLayout: false });
    expect(forced.disposition).not.toBe("OPENED");
    expect(clicks).toEqual([]);
    const marked = page(`<div role="grid"><div role="row" data-bridge-kind="person" data-testid="list-item-3"><span>list-item-3</span><div role="gridcell">${avatars}</div></div></div>`);
    const markedRoute = routeRoster(readPersonRoster(marked, { requireLayout: false }), {}, mintFrom());
    expect(markedRoute.hints).toEqual([]);
    expect(markedRoute.blocked).toContain("AMBIGUOUS");
    expect(JSON.stringify(markedRoute)).not.toContain("list-item-3");
  });
});
