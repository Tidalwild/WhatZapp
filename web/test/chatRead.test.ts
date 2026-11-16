import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { collectOpenChat, sampleOpenChat } from "../src/chatRead.js";

const HEADER = "聯絡資料 contact-a";
const COMPOSER = "輸入要傳送去「contact-a 」嘅訊息";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

function frame(panel: string, header = HEADER, composer = COMPOSER): string {
  return `<button type="button"><span aria-label="${header}"></span>contact-a</button><div id="pane" data-testid="conversation-panel-wrapper">${panel}</div><div role="textbox" contenteditable="true">${composer}</div><div role="grid"><div role="row"><span>secret-other-chat</span></div></div>`;
}

function message(id: string, text: string, time = "09:01", extra = ""): string {
  return `<div data-testid="conv-msg-${id}" data-id="${id}"><div><div><div><div data-testid="msg-container">${extra}<span data-testid="selectable-text">${text}</span><div data-testid="msg-meta"><span>${time}</span></div></div></div></div></div></div>`;
}

function showLayout(doc: Document): void {
  const proto = doc.defaultView?.Element.prototype;
  if (!proto) throw new Error("layout");
  proto.getBoundingClientRect = () =>
    ({ width: 80, height: 24, top: 0, left: 0, right: 80, bottom: 24, x: 0, y: 0 }) as DOMRect;
}

function ids(prefix: string, from: number, to: number): string[] {
  const found: string[] = [];
  for (let index = from; index <= to; index += 1) found.push(`${prefix}${String(index).padStart(3, "0")}`);
  return found;
}

function windowHtml(labels: string[]): string {
  return labels.map((label) => message(label, `fixture-${label}`)).join("");
}

describe("open chat read", () => {
  it("keys the outer conv-msg wrapper and keeps direction unknown", () => {
    const doc = page(
      frame(
        message("wrap-1", "fixture-alpha", "09:01", `<span data-testid="selectable-text">contact-a</span>`) +
          message("wrap-2", "fixture-beta", "上午10:24")
      )
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.disposition).toBe("VISIBLE");
    expect(sample.rows).toEqual([
      { timeText: "09:01", text: "fixture-alpha", direction: "unknown", senderLabel: "contact-a" },
      { timeText: "上午10:24", text: "fixture-beta", direction: "unknown", senderLabel: "" }
    ]);
    expect(JSON.stringify(sample.rows)).not.toContain("secret-other-chat");
    const container = doc.querySelector('[data-testid="msg-container"]');
    expect(container?.getAttribute("data-id")).toBeNull();
    expect(container?.querySelector('[data-testid="msg-meta"]')?.getAttribute("data-id")).toBeNull();
    expect(container?.querySelector('[data-testid="selectable-text"]')?.getAttribute("data-id")).toBeNull();
  });

  it("returns message keys for a delta and does not put the text in those keys", async () => {
    const doc = page(frame(message("wrap-1", "fixture-alpha")));
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: false }, { maxScrolls: 0 });
    expect(report.coverage.keyIds).toEqual(["wrap-1"]);
    expect(report.coverage.keyIds.join(" ")).not.toContain("fixture-alpha");
    expect(report.rows[0]?.direction).toBe("unknown");
  });

  it("keeps two ids that share a timestamp and text", () => {
    const doc = page(frame(message("occ-a", "fixture-same", "09:04") + message("occ-b", "fixture-same", "09:04")));
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.rows.map((row) => row.text)).toEqual(["fixture-same", "fixture-same"]);
    expect(sample.rows.every((row) => row.direction === "unknown")).toBe(true);
  });

  it("keeps document order when the clock times run the other way", () => {
    const doc = page(frame(message("later-id", "fixture-second", "09:00") + message("earlier-id", "fixture-first", "11:30")));
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.rows.map((row) => row.text)).toEqual(["fixture-second", "fixture-first"]);
  });

  it("reads the wrapper id when the container, text, and meta have none", () => {
    const doc = page(
      frame(
        `<span>昨天</span><div data-testid="conv-msg-wrap" data-id="wrap-1"><div><div><div><div data-testid="msg-container"><span data-testid="selectable-text">fixture-same</span><div data-testid="msg-meta"><span>09:04</span><span>09:04</span></div></div></div></div></div></div>`
      )
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.rows).toEqual([{ timeText: "09:04", text: "fixture-same", direction: "unknown", senderLabel: "" }]);
  });

  it("does not take a data-id from outside the conversation panel", () => {
    const doc = page(
      `<div data-testid="conv-msg-out" data-id="OUTSIDE"><button type="button"><span aria-label="${HEADER}"></span>contact-a</button><div id="pane" data-testid="conversation-panel-wrapper"><div data-testid="msg-container"><span data-testid="selectable-text">fixture-loose</span><div data-testid="msg-meta"><span>09:08</span></div></div></div><div role="textbox" contenteditable="true">${COMPOSER}</div></div>`
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.keyed).toEqual([]);
    expect(sample.unkeyed).toHaveLength(1);
    expect(sample.rows).toEqual([]);
  });

  it("counts an unkeyed container apart from the keyed total", () => {
    const doc = page(
      frame(
        message("keyed-1", "fixture-alpha", "09:01") +
          `<div data-testid="msg-container"><span data-testid="selectable-text">fixture-loose</span><div data-testid="msg-meta"><span>09:08</span></div></div>`
      )
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.rows.map((row) => row.text)).toEqual(["fixture-alpha"]);
    expect(sample.keyed).toHaveLength(1);
    expect(sample.unkeyed).toHaveLength(1);
  });

  it("excludes date chips, status marks, and media nodes as extra rows", () => {
    const doc = page(
      frame(
        `<span>星期一</span><span>昨天</span>` +
          message(
            "media-1",
            "fixture-file",
            "09:05",
            `<div data-testid="document-thumb"><span>not-a-row</span></div><div data-testid="tail-in">status-mark</div>`
          )
      )
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.rows).toEqual([
      { timeText: "09:05", text: "fixture-file [document]", direction: "unknown", senderLabel: "" }
    ]);
    const blob = JSON.stringify(sample.rows);
    expect(blob).not.toContain("星期一");
    expect(blob).not.toContain("昨天");
    expect(blob).not.toContain("status-mark");
    expect(blob).not.toContain("not-a-row");
  });

  it("records the phone-history control without calling the chat complete", () => {
    const doc = page(
      frame(`<button type="button">點擊此處從手機取得較舊的訊息。</button>${message("alpha", "fixture-alpha", "09:01")}`)
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.phoneHistory).toBe(true);
    expect(sample.rows.map((row) => row.text)).toEqual(["fixture-alpha"]);
  });

  it("reads nothing when the header is a different chat", () => {
    const doc = page(frame(message("alpha", "fixture-alpha"), "聯絡資料 Sam", "輸入要傳送去「Sam 」嘅訊息"));
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.disposition).toBe("HEADER_MISMATCH");
    expect(sample.rows).toEqual([]);
    expect(sample.header).toBe("");
  });

  it("does not treat the chat list grid as the transcript", () => {
    const doc = page(
      `<button type="button"><span aria-label="${HEADER}"></span>contact-a</button><div role="grid"><div data-testid="conversation-panel-wrapper">${message("secret", "secret-other-chat")}</div></div><div role="textbox" contenteditable="true">${COMPOSER}</div>`
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.disposition).toBe("PANE_UNPROVEN");
    expect(sample.rows).toEqual([]);
    expect(JSON.stringify(sample)).not.toContain("secret-other-chat");
  });

  it("stops when two conversation panels sit between the header and the composer", () => {
    const doc = page(
      `<button type="button"><span aria-label="${HEADER}"></span>contact-a</button><div data-testid="conversation-panel-wrapper">${message("one", "fixture-alpha")}</div><div data-testid="conversation-panel-wrapper">${message("two", "fixture-beta")}</div><div role="textbox" contenteditable="true">${COMPOSER}</div>`
    );
    const sample = sampleOpenChat(doc, "contact-a", { requireLayout: false });
    expect(sample.disposition).toBe("PANE_UNPROVEN");
    expect(JSON.stringify(sample)).not.toContain("fixture-alpha");
  });

  it("unions 17 then 19 then 15 windows to 19 ids and keeps the interior hole", async () => {
    const first = ids("D", 1, 17);
    const second = [...ids("D", 18, 19), ...first];
    const third = [...ids("D", 18, 19), ...ids("D", 1, 12), "D017"];
    const doc = page(frame(windowHtml(first)));
    const pane = doc.getElementById("pane");
    if (!pane) throw new Error("pane");
    Object.defineProperty(pane, "scrollHeight", { configurable: true, get: () => 400 });
    Object.defineProperty(pane, "clientHeight", { configurable: true, get: () => 80 });
    pane.scrollTop = 200;
    let step = 0;
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: false }, {
      maxScrolls: 2,
      settle: async () => {
        step += 1;
        pane.innerHTML = windowHtml(step === 1 ? second : third);
      }
    });
    expect(report.disposition).toBe("READ");
    expect(report.coverage.unique).toBe(19);
    expect(report.coverage.keyed).toBe(19);
    expect(report.coverage.unkeyed).toBe(0);
    expect(report.coverage.unique).toBe(report.rows.length);
    expect(report.coverage.duplicates).toBe(32);
    expect(report.coverage.renderGap).toBe(true);
    expect(report.coverage.orderProven).toBe(true);
    expect(report.coverage.occurrenceJoin).toBe("stable-id");
    expect(report.coverage.historyComplete).toBe(false);
    expect(report.rows.map((row) => row.text)).toEqual(
      [...ids("D", 18, 19), ...ids("D", 1, 17)].map((label) => `fixture-${label}`)
    );
    for (const label of ["D013", "D014", "D015", "D016", "D017"]) {
      expect(report.rows.map((row) => row.text)).toContain(`fixture-${label}`);
    }
  });

  it("keeps a reversed pair once and marks order unproven", async () => {
    const doc = page(frame(message("D001", "fixture-D001") + message("D002", "fixture-D002")));
    const pane = doc.getElementById("pane");
    if (!pane) throw new Error("pane");
    Object.defineProperty(pane, "scrollHeight", { configurable: true, get: () => 200 });
    Object.defineProperty(pane, "clientHeight", { configurable: true, get: () => 80 });
    pane.scrollTop = 100;
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: false }, {
      maxScrolls: 1,
      settle: async () => {
        pane.innerHTML = message("D002", "fixture-D002") + message("D001", "fixture-D001");
      }
    });
    expect(report.rows.map((row) => row.text)).toEqual(["fixture-D001", "fixture-D002"]);
    expect(report.coverage.unique).toBe(2);
    expect(report.coverage.keyed).toBe(2);
    expect(report.coverage.orderProven).toBe(false);
    expect(report.coverage.occurrenceJoin).toBe("stable-id");
    expect(report.coverage.historyComplete).toBe(false);
  });

  it("does not add an uncertain unkeyed resample to the keyed total", async () => {
    const doc = page(
      frame(
        message("keyed-1", "fixture-alpha", "09:01") +
          `<div data-testid="msg-container"><span data-testid="selectable-text">fixture-loose</span><div data-testid="msg-meta"><span>09:08</span></div></div>`
      )
    );
    const pane = doc.getElementById("pane");
    if (!pane) throw new Error("pane");
    Object.defineProperty(pane, "scrollHeight", { configurable: true, get: () => 200 });
    Object.defineProperty(pane, "clientHeight", { configurable: true, get: () => 80 });
    pane.scrollTop = 100;
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: false }, {
      maxScrolls: 1,
      settle: async () => {
        pane.innerHTML =
          message("keyed-1", "fixture-alpha", "09:01") +
          `<div data-testid="msg-container"><span data-testid="selectable-text">fixture-loose</span><div data-testid="msg-meta"><span>09:08</span></div></div>`;
      }
    });
    expect(report.coverage.unique).toBe(1);
    expect(report.coverage.keyed).toBe(1);
    expect(report.coverage.unkeyed).toBe(1);
    expect(report.coverage.occurrenceJoin).toBe("uncertain");
    expect(report.rows.map((row) => row.text)).toEqual(["fixture-alpha"]);
    expect(report.coverage.historyComplete).toBe(false);
  });

  it("drops the sample after the header changes and does not keep the other chat", async () => {
    const doc = page(frame(message("alpha", "fixture-alpha", "09:01")));
    const pane = doc.getElementById("pane");
    if (!pane) throw new Error("pane");
    Object.defineProperty(pane, "scrollHeight", { configurable: true, get: () => 200 });
    Object.defineProperty(pane, "clientHeight", { configurable: true, get: () => 80 });
    pane.scrollTop = 100;
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: false }, {
      maxScrolls: 3,
      settle: async () => {
        const label = doc.querySelector("span[aria-label]");
        label?.setAttribute("aria-label", "聯絡資料 Sam");
        const box = doc.querySelector("[role='textbox']");
        if (box) box.textContent = "輸入要傳送去「Sam 」嘅訊息";
        pane.innerHTML = message("sam", "fixture-sam", "09:09");
      }
    });
    expect(report.disposition).toBe("CHAT_SWITCH");
    expect(report.rows.map((row) => row.text)).toEqual(["fixture-alpha"]);
    expect(report.header).toBe("contact-a");
    expect(JSON.stringify(report)).not.toContain("fixture-sam");
    expect(report.coverage.historyComplete).toBe(false);
  });

  it("reads seventeen containers when the panel contains the header, body, and composer", async () => {
    const rows = ids("D", 1, 17).map((id) => message(id, `fixture-${id}`)).join("");
    const doc = page(
      `<div data-testid="conversation-panel-wrapper" id="pane"><div data-testid="conversation-header"><button type="button" data-testid="conversation-info-header-button"><span aria-label="${HEADER}"></span>contact-a</button></div><div data-testid="conversation-panel-body"><div data-testid="conversation-panel-messages" style="overflow-y:scroll">${rows}</div></div><div data-testid="conversation-compose-box-input" role="textbox" contenteditable="true">${COMPOSER}</div></div><div role="grid"><span>secret-other-chat</span></div>`
    );
    showLayout(doc);
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: true }, { maxScrolls: 1 });
    expect(report.disposition).toBe("READ");
    expect(report.header).toBe("contact-a");
    expect(report.coverage.unique).toBe(17);
    expect(report.coverage.keyed).toBe(17);
    expect(report.coverage.samples).toBeGreaterThan(0);
    expect(report.coverage.historyComplete).toBe(false);
    expect(report.rows.every((row) => row.direction === "unknown")).toBe(true);
    expect(JSON.stringify(report)).not.toContain("secret-other-chat");
  });

  it("keeps the proven contact-a header when more than one containing panel is unproven", async () => {
    const doc = page(
      `<div data-testid="conversation-panel-wrapper"><div data-testid="conversation-panel-wrapper"><div data-testid="conversation-header"><button type="button"><span aria-label="${HEADER}"></span>contact-a</button></div><div data-testid="conversation-panel-body"><div data-testid="conversation-panel-messages">${message("D001", "fixture-alpha")}</div></div><div role="textbox" contenteditable="true">${COMPOSER}</div></div></div>`
    );
    showLayout(doc);
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: true });
    expect(report.disposition).toBe("PANE_UNPROVEN");
    expect(report.header).toBe("contact-a");
    expect(report.coverage.samples).toBe(0);
    expect(report.rows).toEqual([]);
  });

  it("reads the quiet window after a later mutation, not the first partial insert", async () => {
    const doc = page(frame(message("D001", "fixture-first", "09:01")));
    const pane = doc.getElementById("pane");
    if (!pane) throw new Error("pane");
    Object.defineProperty(pane, "scrollHeight", { configurable: true, get: () => 400 });
    Object.defineProperty(pane, "clientHeight", { configurable: true, get: () => 80 });
    let top = 120;
    Object.defineProperty(pane, "scrollTop", {
      configurable: true,
      get: () => top,
      set: (value: number) => {
        top = value;
        if (value === 120) return;
        const view = pane.ownerDocument.defaultView;
        if (!view) return;
        view.setTimeout(() => {
          pane.insertAdjacentHTML("afterbegin", message("partial", "fixture-partial", "09:02"));
        }, 0);
        view.setTimeout(() => {
          pane.innerHTML = message("quiet", "fixture-quiet", "09:03") + message("D001", "fixture-first", "09:01");
        }, 30);
      }
    });
    const report = await collectOpenChat(doc, "contact-a", { requireLayout: false }, { maxScrolls: 1 });
    expect(report.rows.map((row) => row.text)).toEqual(["fixture-quiet", "fixture-first"]);
    expect(JSON.stringify(report.rows)).not.toContain("fixture-partial");
    expect(report.coverage.unique).toBe(2);
    expect(report.coverage.historyComplete).toBe(false);
  });
});
