import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { sanitizeListSignal } from "../src/bridgeSignal.js";
import { classifyPeekTransport, readReportedHeader } from "../src/reportedBinding.js";

describe("sanitized list signal", () => {
  it("drops extra fields instead of forwarding them", () => {
    const clean = sanitizeListSignal(
      {
        layout: "chat-list-contract",
        boundLabel: "contact-a",
        matches: 1,
        position: 0,
        unread: true,
        otherChanges: 0,
        preview: "secret-injected-preview",
        rows: [{ name: "Sam" }]
      },
      "contact-a"
    );
    expect(clean).toEqual({ ok: false, reason: "UNTRUSTED_FIELD" });
    const kept = sanitizeListSignal(
      { layout: "chat-list-contract", boundLabel: "contact-a", matches: 1, position: 0, unread: false, otherChanges: 0 },
      "contact-a"
    );
    expect(kept.ok).toBe(true);
    if (kept.ok) expect(JSON.stringify(kept.signal)).not.toContain("secret");
    const unknown = sanitizeListSignal(
      { layout: "chat-list-contract", boundLabel: "contact-a", matches: 1, position: 1, unread: null, otherChanges: 0 },
      "contact-a"
    );
    expect(unknown.ok).toBe(true);
    if (unknown.ok) expect(unknown.signal.unread).toBeNull();
    const dot = sanitizeListSignal(
      { layout: "chat-list-contract", boundLabel: "contact-a", matches: 1, position: 1, unread: null, mark: "dot", otherChanges: 0 },
      "contact-a"
    );
    expect(dot).toMatchObject({ ok: true, signal: { mark: "dot", unread: null } });
    const counted = sanitizeListSignal(
      { layout: "chat-list-contract", boundLabel: "contact-a", matches: 1, position: 1, unread: true, mark: "dot", otherChanges: 0 },
      "contact-a"
    );
    expect(counted).toEqual({ ok: false, reason: "UNTRUSTED_FIELD" });
    const number = sanitizeListSignal(
      { layout: "chat-list-contract", boundLabel: "contact-a", matches: 1, position: 1, unread: null, mark: "count", count: 1, otherChanges: 0 },
      "contact-a"
    );
    expect(number).toMatchObject({ ok: true, signal: { mark: "count", count: 1, unread: null } });
    const text = sanitizeListSignal(
      {
        layout: "chat-list-contract",
        boundLabel: "contact-a",
        matches: 1,
        position: 1,
        unread: null,
        mark: "count",
        count: 1,
        otherChanges: 0,
        label: "1個未讀訊息"
      },
      "contact-a"
    );
    expect(text).toEqual({ ok: false, reason: "UNTRUSTED_FIELD" });
    const zero = sanitizeListSignal(
      { layout: "chat-list-contract", boundLabel: "contact-a", matches: 1, position: 1, unread: null, mark: "count", count: 0, otherChanges: 0 },
      "contact-a"
    );
    expect(zero).toEqual({ ok: false, reason: "UNTRUSTED_FIELD" });
  });
});

const SECRET = "secret-gridcell-preview";
const PROFILE = "A+B Academy";

function box(sized: boolean) {
  return {
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    bottom: sized ? 20 : 0,
    right: sized ? 20 : 0,
    width: sized ? 20 : 0,
    height: sized ? 20 : 0,
    toJSON() {
      return {};
    }
  };
}

function read(body: string): string {
  const window = new Window();
  window.document.body.innerHTML = body;
  return readReportedHeader(window.document as unknown as Document, { requireLayout: false });
}

describe("reported accessible names", () => {
  it("returns the label only when both reported names agree", () => {
    const header = read(
      [
        `<button aria-label="聯絡資料 contact-a"></button>`,
        `<div aria-placeholder="輸入要傳送去「contact-a 」嘅訊息"></div>`,
        `<span aria-label="secret-other-chat"></span>`
      ].join("")
    );
    expect(header).toBe("contact-a");
    expect(read(`<button aria-label="聯絡資料 contact-a"></button>`)).toBe("");
  });

  it("reads the rendered control text and ignores a longer lookalike", () => {
    const header = read(
      [
        `<div role="grid"><div role="row"><div role="gridcell" aria-label="${SECRET}">secret-cell-text</div><span>contact-a</span></div></div>`,
        `<button type="button">聯絡資料 contact-a</button>`,
        `<div aria-label="聯絡資料 contact-a extra ${SECRET}"></div>`,
        `<div id="named">輸入要傳送去「contact-a 」嘅訊息</div>`,
        `<div aria-labelledby="named"></div>`,
        `<p>${PROFILE}</p>`,
        `<span>secret-message-body</span>`
      ].join("")
    );
    expect(header).toBe("contact-a");
    expect(header).not.toContain(SECRET);
    expect(header).not.toContain(PROFILE);
    expect(header).not.toContain("secret-message-body");
    expect(read(`<h2>contact-a</h2><p>${PROFILE}</p><span>secret-message-body</span>`)).toBe("");
    expect(
      read(`<button>聯絡資料 contact-a</button><div placeholder="輸入要傳送去「Sam 」嘅訊息"></div>`)
    ).toBe("");
    expect(read(`<div hidden><button>聯絡資料 contact-a</button><div placeholder="輸入要傳送去「contact-a 」嘅訊息"></div></div>`)).toBe("");
  });

  it("reads the reported button name and textbox name, not a visible contact-a word", () => {
    const composer = "輸入要傳送去「contact-a 」嘅訊息";
    const shape = [
      `<button type="button"><span><span aria-label="聯絡資料 contact-a"></span></span>contact-a</button>`,
      `<div role="textbox" contenteditable="true">${composer}</div>`,
      `<div role="grid"><div role="row"><span>contact-a</span><div role="gridcell" aria-label="${SECRET}">secret-cell-text</div></div></div>`,
      `<span>contact-a</span>`,
      `<p>${PROFILE}</p>`,
      `<div aria-label="聯絡資料 contact-a extra ${SECRET}"></div>`
    ].join("");
    const header = read(shape);
    expect(header).toBe("contact-a");
    expect(header).not.toContain(SECRET);
    expect(header).not.toContain(PROFILE);
    expect(read(`<div role="grid"><span>contact-a</span></div><span>contact-a</span><p>${PROFILE}</p>`)).toBe("");
    expect(read(`<button type="button">contact-a</button><div role="textbox" contenteditable="true">${composer}</div>`)).toBe("");
    expect(
      read(`<button aria-label="聯絡資料 contact-a ${SECRET}">contact-a</button><div role="textbox">${composer}</div>`)
    ).toBe("");
    expect(
      read(
        `<button aria-labelledby="contact-name">contact-a</button><span id="contact-name" aria-label="聯絡資料 contact-a" hidden></span>` +
          `<div role="textbox" aria-labelledby="composer-name"></div><span id="composer-name" aria-label="${composer}" hidden></span>`
      )
    ).toBe("contact-a");
    expect(
      read(`<button aria-label="聯絡資料 contact-a"></button><div role="textbox">${composer} extra ${SECRET}</div>`)
    ).toBe("");
  });

  it("accepts a nested button name with no box of its own", () => {
    const window = new Window();
    const composer = "輸入要傳送去「contact-a 」嘅訊息";
    window.document.body.innerHTML = [
      `<button type="button" id="contact"><span id="wrap"><span id="name" aria-label="聯絡資料 contact-a"></span></span>contact-a</button>`,
      `<div role="textbox" id="box" contenteditable="true">${composer}</div>`,
      `<div role="grid"><span>contact-a</span></div>`,
      `<span>contact-a</span>`
    ].join("");
    for (const node of window.document.querySelectorAll("*")) {
      const id = node.id;
      const sized = id === "contact" || id === "box" || node.tagName === "BODY";
      node.getBoundingClientRect = (() => box(sized)) as unknown as typeof node.getBoundingClientRect;
    }
    const header = readReportedHeader(window.document as unknown as Document, { requireLayout: true });
    expect(header).toBe("contact-a");
    window.document.body.innerHTML = `<div id="shell"><span id="orphan" aria-label="聯絡資料 contact-a"></span></div><div role="textbox" id="box">${composer}</div><span>contact-a</span>`;
    for (const node of window.document.querySelectorAll("*")) {
      const sized = node.id === "box" || node.tagName === "BODY";
      node.getBoundingClientRect = (() => box(sized)) as unknown as typeof node.getBoundingClientRect;
    }
    expect(readReportedHeader(window.document as unknown as Document, { requireLayout: true })).toBe("");
  });

  it("reads the same pair from an open shadow root", () => {
    const window = new Window();
    const composer = "輸入要傳送去「contact-a 」嘅訊息";
    window.document.body.innerHTML = `<div id="host"></div>`;
    const host = window.document.getElementById("host");
    const root = host?.attachShadow({ mode: "open" });
    root!.innerHTML = `<button type="button"><span><span aria-label="聯絡資料 contact-a"></span></span>contact-a</button><div role="textbox" contenteditable="true">${composer}</div><span>contact-a</span>`;
    expect(readReportedHeader(window.document as unknown as Document, { requireLayout: false })).toBe("contact-a");
    const hidden = window.document.createElement("div");
    hidden.hidden = true;
    window.document.body.append(hidden);
    const buried = hidden.attachShadow({ mode: "open" });
    buried.innerHTML = `<button type="button" aria-label="聯絡資料 Sam"></button>`;
    expect(readReportedHeader(window.document as unknown as Document, { requireLayout: false })).toBe("contact-a");
  });
});

describe("peek transport", () => {
  it("maps a missing content script without keeping the browser message", () => {
    expect(classifyPeekTransport("Could not establish connection. Receiving end does not exist.")).toBe(
      "content-script-missing"
    );
    expect(classifyPeekTransport("something else")).toBe("unavailable");
  });
});
