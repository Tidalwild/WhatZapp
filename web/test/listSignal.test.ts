import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { emptyMemory, readChatListSignal } from "../src/listSignal.js";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

const row = (label: string, preview: string, unread = false): string =>
  `<div data-bridge-row="chat"><span data-bridge-label>${label}</span><span data-bridge-preview>${preview}</span>${
    unread ? `<span data-bridge-unread></span>` : ""
  }</div>`;

describe("chat list signal", () => {
  it("returns only the bound row and does not return other names or previews", () => {
    const doc = page(
      `<div data-bridge-list="chats">${row("Sam", "secret-sam")}${row("contact-a", "secret-fixture")}</div>`
    );
    const first = readChatListSignal(doc, "contact-a", emptyMemory(), { requireLayout: false });
    expect(first.signal).toMatchObject({ matches: 1, position: 1, unread: false, otherChanges: 0 });
    expect(JSON.stringify(first.signal)).not.toContain("secret");
    expect(JSON.stringify(first.signal)).not.toContain("Sam");
    const changed = page(
      `<div data-bridge-list="chats">${row("Sam", "secret-sam", true)}${row("contact-a", "secret-fixture", true)}</div>`
    );
    const second = readChatListSignal(changed, "contact-a", first.memory, { requireLayout: false });
    expect(second.signal.otherChanges).toBe(1);
    expect(second.signal.unread).toBe(true);
    expect(JSON.stringify(second.signal)).not.toContain("secret-sam");
  });

  it("fail-closes when the bound label is not unique or a row cannot be read", () => {
    const doubled = page(
      `<div data-bridge-list="chats">${row("contact-a", "one")}${row("contact-a", "two")}</div>`
    );
    expect(readChatListSignal(doubled, "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(2);
    const messy = page(
      `<div role="grid"><div role="row" aria-label="contact-a unread hello"><span>ignored-preview</span></div></div>`
    );
    const signal = readChatListSignal(messy, "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(signal.matches).toBe(0);
    expect(signal.otherChanges).toBe(0);
    expect(JSON.stringify(signal)).not.toContain("ignored-preview");
    expect(JSON.stringify(signal)).not.toContain("hello");
  });
});

const LONG = "secret-gridcell-preview-not-a-label";
const OTHER = "secret-other-gridcell-name";

function liveList(fixture: string, extra = ""): string {
  return `<main role="main"><h1>contact-a</h1><div role="grid"><div role="row"><div role="gridcell" aria-label="secret-main-only">secret-main-text</div></div></div></main>
    <div role="grid" aria-label="Chats">
      <div role="row"><div role="gridcell" aria-label="${OTHER}">secret-other-text</div><span>Sam</span></div>
      <div role="row">${fixture}</div>
      ${extra}
    </div>`;
}

describe("reported live list shape", () => {
  it("identifies contact-a only from the generic child and drops longer gridcell names", () => {
    const sibling = liveList(
      `<div role="gridcell" aria-label="${LONG}">secret-fixture-cell</div><span>contact-a</span><span style="color:green" aria-label="unread"></span>`
    );
    const first = readChatListSignal(page(sibling), "contact-a", emptyMemory(), { requireLayout: false });
    expect(first.signal).toMatchObject({ matches: 1, position: 1, unread: null, mark: "ambiguous", otherChanges: 0 });
    const dumped = JSON.stringify(first);
    expect(dumped).not.toContain(LONG);
    expect(dumped).not.toContain(OTHER);
    expect(dumped).not.toContain("secret-fixture-cell");
    expect(dumped).not.toContain("secret-other-text");
    expect(dumped).not.toContain("secret-main");
    expect(dumped).not.toContain("Sam");
    expect(first.signal.unread).toBeNull();

    const nested = liveList(
      `<div role="gridcell" aria-label="${LONG}"><span>contact-a</span><span>secret-nested-preview</span></div>`
    );
    const inside = readChatListSignal(page(nested), "contact-a", emptyMemory(), { requireLayout: false });
    expect(inside.signal).toMatchObject({ matches: 1, position: 1, unread: false, mark: "absent" });
    expect(JSON.stringify(inside)).not.toContain("secret-nested-preview");
    expect(JSON.stringify(inside)).not.toContain(LONG);

    const explicit = liveList(`<div role="gridcell" aria-label="${LONG}"></div><div role="generic">contact-a</div>`);
    expect(readChatListSignal(page(explicit), "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(1);
  });

  it("does not match a longer row name, a gridcell named contact-a, or a grid inside main", () => {
    const rowNamed = `<div role="grid"><div role="row" aria-label="contact-a"></div></div>`;
    expect(readChatListSignal(page(rowNamed), "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(0);
    const cellNamed = `<div role="grid"><div role="row"><div role="gridcell">contact-a</div></div></div>`;
    const cell = readChatListSignal(page(cellNamed), "contact-a", emptyMemory(), { requireLayout: false });
    expect(cell.signal.matches).toBe(0);
    expect(JSON.stringify(cell)).not.toContain("preview");
    const longer = `<div role="grid"><div role="row"><div role="gridcell" aria-label="${LONG}"><span>contact-a extra</span></div></div></div>`;
    const missed = readChatListSignal(page(longer), "contact-a", emptyMemory(), { requireLayout: false });
    expect(missed.signal.matches).toBe(0);
    expect(JSON.stringify(missed)).not.toContain(LONG);
    const insideMain = `<main role="main"><div role="grid"><div role="row"><span>contact-a</span></div></div></main>`;
    expect(readChatListSignal(page(insideMain), "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(0);
    const namedGrid = `<div role="grid" aria-label="contact-a"><div role="row"><span>contact-a</span></div></div>`;
    expect(readChatListSignal(page(namedGrid), "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(0);
    const two = `<div role="grid"><div role="row"><span>contact-a</span></div></div><div role="grid"><div role="row"><span>contact-a</span></div></div>`;
    expect(readChatListSignal(page(two), "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(0);
  });

  it("counts another row without keeping its name, and ignores a gridcell rewrite", () => {
    const doc = page(liveList(`<div role="gridcell" aria-label="${LONG}"></div><span>contact-a</span>`));
    const first = readChatListSignal(doc, "contact-a", emptyMemory(), { requireLayout: false });
    const cell = doc.querySelector("[aria-label='" + LONG + "']");
    cell?.setAttribute("aria-label", "secret-rewritten-gridcell");
    const rewritten = readChatListSignal(doc, "contact-a", first.memory, { requireLayout: false });
    expect(rewritten.signal.otherChanges).toBe(0);
    expect(rewritten.signal).toMatchObject({ unread: false, mark: "absent" });
    expect(JSON.stringify(rewritten)).not.toContain("secret-rewritten-gridcell");
    const added = doc.createElement("div");
    added.setAttribute("role", "row");
    added.innerHTML = `<div role="gridcell" aria-label="secret-added-gridcell"></div><span>Jo</span>`;
    doc.querySelector("[aria-label='Chats']")?.append(added);
    const second = readChatListSignal(doc, "contact-a", rewritten.memory, { requireLayout: false });
    expect(second.signal.matches).toBe(1);
    expect(second.signal.otherChanges).toBe(1);
    expect(JSON.stringify(second)).not.toContain("Jo");
    expect(JSON.stringify(second)).not.toContain("Sam");
    expect(JSON.stringify(second)).not.toContain("secret-added-gridcell");
    const doubled = page(
      liveList(`<span>contact-a</span>`) + ""
    );
    doubled.querySelector("[aria-label='Chats']")?.insertAdjacentHTML(
      "beforeend",
      `<div role="row"><span>contact-a</span><div role="gridcell" aria-label="${LONG}"></div></div>`
    );
    expect(readChatListSignal(doubled, "contact-a", emptyMemory(), { requireLayout: false }).signal.matches).toBe(2);
  });
});

const DOT = `<span data-testid="icon-unread-count" aria-label="未讀" class="generated-not-a-selector"></span>`;

function markedRow(inner: string): string {
  return `<div role="grid" aria-label="Chats"><div role="row" id="fixture">${inner}</div></div>`;
}

function countBadge(count: number, label = `${count}個未讀訊息`, text = String(count)): string {
  return `<span data-testid="icon-unread-count" aria-label="${label}">${text}</span>`;
}

describe("numbered unread badge", () => {
  it("reads the observed numeric shape without copying its label", () => {
    const inCell = markedRow(
      `<span>contact-a</span><div role="gridcell" aria-label="${LONG}">secret-fixture-cell</div><div role="gridcell">${countBadge(1)}</div>`
    );
    const first = readChatListSignal(page(inCell), "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(first).toMatchObject({ matches: 1, unread: null, mark: "count", count: 1 });
    const beforeCell = markedRow(
      `<span>contact-a</span>${countBadge(2)}<div role="gridcell" aria-label="${LONG}">secret-fixture-cell</div>`
    );
    const second = readChatListSignal(page(beforeCell), "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(second).toMatchObject({ mark: "count", count: 2 });
    const dumped = JSON.stringify(first) + JSON.stringify(second);
    expect(dumped).not.toContain("個未讀訊息");
    expect(dumped).not.toContain("未讀");
    expect(dumped).not.toContain("icon-unread-count");
    expect(dumped).not.toContain(LONG);
    expect(dumped).not.toContain("secret-fixture-cell");
  });

  it("fail-closes on a mismatched, hidden, duplicate, or invalid number and does not treat that as absent", () => {
    const cases = [
      markedRow(`<span>contact-a</span><div role="gridcell">${countBadge(1, "1個未讀訊息", "2")}</div>`),
      markedRow(`<span>contact-a</span><div role="gridcell">${countBadge(1, "1 unread message", "1")}</div>`),
      markedRow(`<span>contact-a</span><div role="gridcell">${countBadge(0, "0個未讀訊息", "0")}</div>`),
      markedRow(`<span>contact-a</span><div role="gridcell"><span data-testid="icon-unread-count" aria-label="1個未讀訊息" role="status">1</span></div>`),
      markedRow(`<span>contact-a</span><div role="gridcell"><span hidden data-testid="icon-unread-count" aria-label="1個未讀訊息">1</span></div>`),
      markedRow(`<span>contact-a</span><div role="gridcell">${countBadge(1)}${countBadge(1)}</div>`),
      markedRow(`<span>contact-a</span><div role="gridcell"><span data-testid="icon-unread-count" aria-label="99+個未讀訊息">99+</span></div>`)
    ];
    for (const body of cases) {
      const signal = readChatListSignal(page(body), "contact-a", emptyMemory(), { requireLayout: false }).signal;
      expect(signal.mark).toBe("ambiguous");
      expect(signal.unread).toBeNull();
      expect(signal.count).toBeUndefined();
      expect(JSON.stringify(signal)).not.toContain("個");
    }
  });

  it("keeps a transient count on the signal that sees it and a later clear as absent", () => {
    const doc = page(markedRow(`<span>contact-a</span><div role="gridcell" id="cell"></div>`));
    const absent = readChatListSignal(doc, "contact-a", emptyMemory(), { requireLayout: false });
    expect(absent.signal).toMatchObject({ mark: "absent", count: 0, unread: false });
    const cell = doc.querySelector("#cell");
    cell?.insertAdjacentHTML("beforeend", countBadge(1));
    const shown = readChatListSignal(doc, "contact-a", absent.memory, { requireLayout: false });
    expect(shown.signal).toMatchObject({ mark: "count", count: 1, unread: null });
    cell?.querySelector("[data-testid='icon-unread-count']")?.remove();
    const cleared = readChatListSignal(doc, "contact-a", shown.memory, { requireLayout: false });
    expect(cleared.signal).toMatchObject({ mark: "absent", count: 0 });
    expect(JSON.stringify(cleared.signal)).not.toContain("個");
  });
});

describe("rendered unread dot", () => {
  it("recognizes the exact public-source unread dot with the same structure", () => {
    const doc = page(
      markedRow(`<span>contact-a</span><div role="gridcell" aria-label="${LONG}">secret-fixture-cell</div><div role="gridcell"><span data-testid="icon-unread-count" aria-label="unread"></span></div>`)
    );
    const signal = readChatListSignal(doc, "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(signal).toMatchObject({ matches: 1, unread: null, mark: "dot" });
    expect(JSON.stringify(signal)).not.toContain("icon-unread-count");
    expect(JSON.stringify(signal)).not.toContain("secret-fixture-cell");
  });

  it("recognizes an empty traditional-Chinese dot and ignores its class", () => {
    const doc = page(
      markedRow(`<span>contact-a</span><div role="gridcell" aria-label="${LONG}">secret-fixture-cell</div><div role="gridcell">${DOT}</div>`)
    );
    const signal = readChatListSignal(doc, "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(signal).toMatchObject({ matches: 1, unread: null, mark: "dot" });
    const dumped = JSON.stringify(signal);
    expect(dumped).not.toContain("未讀");
    expect(dumped).not.toContain("icon-unread-count");
    expect(dumped).not.toContain("generated-not-a-selector");
    expect(dumped).not.toContain("secret-fixture-cell");
    expect(dumped).not.toContain(LONG);
  });

  it("calls a structurally clear row absent and keeps a row without a cell unknown", () => {
    const clear = readChatListSignal(
      page(markedRow(`<span>contact-a</span><div role="gridcell"></div>`)),
      "contact-a",
      emptyMemory(),
      { requireLayout: false }
    ).signal;
    expect(clear).toMatchObject({ unread: false, mark: "absent" });
    const stub = readChatListSignal(page(markedRow(`<span>contact-a</span>`)), "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(stub).toMatchObject({ unread: null, mark: "unknown" });
  });

  it("keeps malformed, hidden, numeric, and unrelated badges out of the signal", () => {
    const cases = [
      markedRow(`<span>contact-a</span><div role="gridcell">${DOT.replace("></span>", ">12</span>")}</div>`),
      markedRow(`<span>contact-a</span><div role="gridcell"><span data-testid="icon-unread-count" aria-label="未讀" role="status"></span></div>`),
      markedRow(`<span>contact-a</span><div role="gridcell">${DOT}</div><div role="gridcell"></div>`),
      markedRow(`<span>contact-a</span><div role="gridcell"><span hidden data-testid="icon-unread-count" aria-label="未讀"></span></div>`),
      markedRow(`<span>contact-a</span><div role="gridcell">${DOT}${DOT}</div>`),
      markedRow(`<span>contact-a</span><div role="gridcell"></div><span aria-label="unread" style="color:green"></span>`)
    ];
    for (const body of cases) {
      const signal = readChatListSignal(page(body), "contact-a", emptyMemory(), { requireLayout: false }).signal;
      expect(signal.mark).toBe("ambiguous");
      expect(signal.unread).toBeNull();
      const dumped = JSON.stringify(signal);
      expect(dumped).not.toContain("未讀");
      expect(dumped).not.toContain("12");
      expect(dumped).not.toContain("icon-unread-count");
    }
    const other = page(
      `<div role="grid"><div role="row"><span>Sam</span><div role="gridcell">${DOT}</div></div><div role="row"><span>contact-a</span><div role="gridcell"></div></div></div>`
    );
    const fixture = readChatListSignal(other, "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(fixture).toMatchObject({ matches: 1, mark: "absent", unread: false });
    expect(JSON.stringify(fixture)).not.toContain("未讀");
    expect(JSON.stringify(fixture)).not.toContain("Sam");
    const doubled = page(
      `<div role="grid"><div role="row"><span>contact-a</span><div role="gridcell">${DOT}</div></div><div role="row"><span>contact-a</span><div role="gridcell">${DOT}</div></div></div>`
    );
    const both = readChatListSignal(doubled, "contact-a", emptyMemory(), { requireLayout: false }).signal;
    expect(both.matches).toBe(2);
    expect(JSON.stringify(both)).not.toContain("未讀");
  });

  it("reports a dot and another row mount in the same read", () => {
    const start = page(markedRow(`<span>contact-a</span><div role="gridcell"></div>`));
    const first = readChatListSignal(start, "contact-a", emptyMemory(), { requireLayout: false });
    expect(first.signal).toMatchObject({ mark: "absent", otherChanges: 0 });
    const grid = start.querySelector("[role='grid']");
    const trail = start.querySelector("#fixture");
    trail?.insertAdjacentHTML("beforeend", `<div role="gridcell">${DOT}</div>`);
    const extra = start.createElement("div");
    extra.setAttribute("role", "row");
    extra.innerHTML = `<div role="gridcell"></div><span>Sam</span>`;
    grid?.append(extra);
    const second = readChatListSignal(start, "contact-a", first.memory, { requireLayout: false });
    expect(second.signal).toMatchObject({ matches: 1, mark: "dot", unread: null });
    expect(second.signal.otherChanges).toBe(1);
    const dumped = JSON.stringify(second.signal);
    expect(dumped).not.toContain("Sam");
    expect(dumped).not.toContain("未讀");
    expect(dumped).not.toContain("icon-unread-count");
  });
});
