import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { inspectOneUnread } from "../src/attentionInspect.js";
import { readContactSurface } from "../src/contactSurface.js";
import { readListChange } from "../src/listChange.js";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

function badge(count: number): string {
  return `<span data-testid="icon-unread-count" aria-label="${count}個未讀訊息">${count}</span>`;
}

function containers(text: string): string {
  return Array.from({ length: 10 }, () => `<div data-testid="msg-container"><span data-testid="selectable-text">${text}</span></div>`).join("");
}

describe("list change and open classification", () => {
  it("sums numbered badges and does not name the rows", () => {
    const doc = page(`<div role="grid">${row("list-item-0", badge(1))}${row("list-item-0", badge(2))}</div>`);
    const change = readListChange(doc, { requireLayout: false });
    expect(change).toEqual({ mark: "count", count: 3 });
    expect(JSON.stringify(change)).not.toContain("list-item");
  });

  it("classifies a mounted group without reading the containers", () => {
    const secret = "secret-body";
    const doc = page(`
      <div role="grid">${row("list-item-0", badge(1), `<button type="button">row-button</button>`)}</div>
      <div data-testid="chat-info-drawer">
        <div data-testid="group-info-header"><span>群組資料</span></div>
        <div data-testid="group-info-drawer-body"></div>
      </div>
      ${containers(secret)}
    `);
    const buttonClicks: string[] = [];
    doc.querySelector("button")?.addEventListener("click", () => buttonClicks.push("row"));
    const result = inspectOneUnread(doc, { requireLayout: false }, mint());
    expect(result).toEqual({ disposition: "GROUP_CLOSE", identity: "UNPROVEN", messagesCollected: false });
    expect(JSON.stringify(result)).not.toContain(secret);
    expect(buttonClicks).toEqual([]);
    expect(readContactSurface(doc, { requireLayout: false }).surface).toBe("group");
  });

  it("opens one live unread row, then a direct-contact drawer stays ambiguous", () => {
    const secret = "secret-body";
    const doc = page(`
      <div role="grid">
        ${row("list-item-0", badge(1))}
        ${row("list-item-1", "")}
      </div>
      <button type="button" aria-label="聯絡資料 row-A" hidden></button>
      <div data-testid="chat-info-drawer" hidden><span>聯絡人資料</span></div>
      ${containers(secret)}
    `);
    const rowClicks: string[] = [];
    const infoClicks: string[] = [];
    const unread = doc.querySelector("[role='row']");
    unread?.addEventListener("click", () => {
      rowClicks.push("row");
      doc.querySelector("button")?.removeAttribute("hidden");
    });
    doc.querySelector("button")?.addEventListener("click", () => {
      infoClicks.push("info");
      doc.querySelector("[data-testid='chat-info-drawer']")?.removeAttribute("hidden");
    });
    const result = inspectOneUnread(doc, { requireLayout: false }, mint());
    expect(result).toEqual({ disposition: "DIRECT_CONTEXT", identity: "AMBIGUOUS", messagesCollected: false });
    expect(rowClicks).toEqual(["row"]);
    expect(infoClicks).toEqual(["info"]);
    expect(JSON.stringify(result)).not.toContain(secret);
    expect(JSON.stringify(result)).not.toContain("row-A");
  });

  it("does not open when the handle cannot be held", () => {
    const doc = page(`<div role="grid">${row("list-item-0", badge(1))}</div>`);
    const clicks: string[] = [];
    doc.querySelector("[role='row']")?.addEventListener("click", () => clicks.push("row"));
    const result = inspectOneUnread(doc, { requireLayout: false }, () => "not-a-handle");
    expect(result.disposition).toBe("STALE");
    expect(clicks).toEqual([]);
  });

  it("does not call a group composer a direct contact when the drawer says Contact info", () => {
    const doc = page(`
      <div role="grid">${row("list-item-0", badge(1))}</div>
      <header><span dir="auto">contact-a</span></header>
      <div role="textbox" contenteditable="true" aria-label="Type a message to group contact-a"></div>
      <div data-testid="chat-info-drawer"><span>Contact info</span></div>
    `);
    const result = inspectOneUnread(doc, { requireLayout: false }, mint());
    expect(result).toEqual({ disposition: "UNPROVEN", identity: "UNPROVEN", messagesCollected: false });
  });

  it("uses Profile details only as an opener", () => {
    const doc = page(`
      <div role="grid">${row("list-item-0", badge(1))}</div>
      <button type="button" title="Profile details"></button>
      <div data-testid="chat-info-drawer" hidden><span>Contact info</span></div>
    `);
    doc.querySelector("button")?.addEventListener("click", () => {
      doc.querySelector("[data-testid='chat-info-drawer']")?.removeAttribute("hidden");
    });
    const result = inspectOneUnread(doc, { requireLayout: false }, mint());
    expect(result).toEqual({ disposition: "DIRECT_CONTEXT", identity: "AMBIGUOUS", messagesCollected: false });
    const both = page(`
      <div role="grid">${row("list-item-0", badge(1))}</div>
      <button type="button" title="Profile details"></button>
      <button type="button" aria-label="聯絡資料 contact-a"></button>
    `);
    expect(inspectOneUnread(both, { requireLayout: false }, mint()).disposition).toBe("INFO_UNOPENED");
  });
});

function row(slot: string, extra: string, inner = ""): string {
  return `<div role="row" data-testid="${slot}"><span>${slot}</span>${inner}<div role="gridcell">${extra}</div></div>`;
}

function mint(): () => string {
  let serial = 0;
  return () => `h-${(++serial).toString(16).padStart(16, "0")}`;
}
