import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { emptyPaneMemory, observeOpenPane, type PaneMemory } from "../src/openPane.js";

const SECRET = "secret-body";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

function shell(inner: string, token = "row-a", drawer = contactDrawer()): string {
  return `${drawer}
    <button type="button" aria-label="聯絡資料 ${token}">header</button>
    <div role="textbox" aria-label="輸入要傳送去「${token} 」嘅訊息"></div>
    <div data-testid="conversation-panel-wrapper">
      <div data-testid="conversation-panel-messages">${inner}</div>
    </div>`;
}

function contactDrawer(extra = ""): string {
  return `<div data-testid="chat-info-drawer"><span>聯絡人資料</span>${extra}</div>`;
}

function groupDrawer(): string {
  return `<div data-testid="chat-info-drawer"><div data-testid="group-info-header"><span>群組資料</span></div><div data-testid="group-info-drawer-body"></div></div>`;
}

function bubble(text = SECRET): string {
  return `<div data-testid="msg-container"><span data-testid="selectable-text">${text}</span></div>`;
}

function watch(doc: Document, memory: PaneMemory = emptyPaneMemory()) {
  const decision = observeOpenPane(doc, memory, { requireLayout: false });
  expect(JSON.stringify(decision)).not.toContain(SECRET);
  expect(JSON.stringify(decision)).not.toContain("row-a");
  expect(JSON.stringify(decision)).not.toContain("row-b");
  return decision;
}

describe("open pane attention", () => {
  it("baselines the open chat and hints once for a later tail", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    expect(watch(doc, memory).disposition).toBe("BASELINE");
    doc.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("beforeend", bubble());
    const hinted = watch(doc, memory);
    expect(hinted).toEqual({ disposition: "HINT", generation: 1 });
    expect(watch(doc, memory)).toEqual({ disposition: "SAME", generation: 1 });
  });

  it("hints once when the own reply and a new turn land in the same sample", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    watch(doc, memory);
    const composer = doc.querySelector("[role='textbox']")!;
    composer.textContent = "draft-secret";
    expect(watch(doc, memory).disposition).toBe("SAME");
    composer.textContent = "";
    const root = doc.querySelector("[data-testid='conversation-panel-messages']")!;
    root.insertAdjacentHTML("beforeend", bubble("own-secret"));
    root.insertAdjacentHTML("beforeend", bubble("turn-secret"));
    expect(watch(doc, memory)).toEqual({ disposition: "HINT", generation: 1 });
    expect(watch(doc, memory)).toEqual({ disposition: "SAME", generation: 1 });
  });

  it("hints once for an own-send tail and does not repeat it", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    watch(doc, memory);
    doc.querySelector("[role='textbox']")!.textContent = "draft-secret";
    watch(doc, memory);
    doc.querySelector("[role='textbox']")!.textContent = "";
    doc.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("beforeend", bubble());
    expect(watch(doc, memory)).toEqual({ disposition: "HINT", generation: 1 });
    expect(watch(doc, memory)).toEqual({ disposition: "SAME", generation: 1 });
  });

  it("hints for a new tail that is still mounted as the header closes", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    watch(doc, memory);
    doc.querySelector("button")!.remove();
    doc.querySelector("[role='textbox']")!.remove();
    doc.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("beforeend", bubble("late-secret"));
    expect(watch(doc, memory)).toEqual({ disposition: "HINT", generation: 1 });
    expect(watch(doc, memory).disposition).toBe("CLEAN");
    expect(memory.generation).toBe(1);
  });

  it("ignores older containers mounted above the same tail", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    watch(doc, memory);
    doc.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("afterbegin", bubble("older-secret"));
    expect(watch(doc, memory).disposition).toBe("SAME");
  });

  it("does not hint a group, and a mutual-groups section stays a direct contact", () => {
    const grouped = page(shell(bubble(), "row-a", groupDrawer()));
    const groupMemory = emptyPaneMemory();
    expect(watch(grouped, groupMemory).disposition).toBe("GROUP");
    grouped.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("beforeend", bubble());
    expect(watch(grouped, groupMemory).disposition).toBe("GROUP");
    const doc = page(shell(bubble(), "row-a", contactDrawer("<section>共同群組</section>")));
    const memory = emptyPaneMemory();
    expect(watch(doc, memory).disposition).toBe("BASELINE");
    doc.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("beforeend", bubble());
    expect(watch(doc, memory).disposition).toBe("HINT");
  });

  it("rebaselines a context switch and fails closed when the tail is rebuilt", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    watch(doc, memory);
    doc.querySelector("button")!.setAttribute("aria-label", "聯絡資料 row-b");
    doc.querySelector("[role='textbox']")!.setAttribute("aria-label", "輸入要傳送去「row-b 」嘅訊息");
    doc.querySelector("[data-testid='conversation-panel-messages']")!.innerHTML = bubble("switched-secret");
    expect(watch(doc, memory).disposition).toBe("BASELINE");
    expect(memory.generation).toBe(0);
    const tail = doc.querySelector("[data-testid='msg-container']")!;
    tail.remove();
    doc.querySelector("[data-testid='conversation-panel-messages']")!.insertAdjacentHTML("beforeend", bubble());
    expect(watch(doc, memory).disposition).toBe("STALE");
    expect(memory.generation).toBe(0);
  });

  it("clears the session when the pane closes", () => {
    const doc = page(shell(bubble()));
    const memory = emptyPaneMemory();
    watch(doc, memory);
    doc.body.innerHTML = "";
    expect(watch(doc, memory).disposition).toBe("CLEAN");
    doc.body.innerHTML = shell(bubble());
    expect(watch(doc, memory).disposition).toBe("BASELINE");
    expect(memory.generation).toBe(0);
  });
});
