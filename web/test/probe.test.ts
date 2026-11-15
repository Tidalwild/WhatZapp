import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { readProbe } from "../src/probe.js";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

const row = (sender: string, text: string, time: string, extra = ""): string =>
  `<div role="listitem" ${extra}><span>${sender}</span><p>${text}</p><time datetime="1999-01-01T00:00:00Z">${time}</time></div>`;

function chat(inner: string, status = ""): string {
  return `
    <aside><ul><li>Other chat preview</li></ul><textarea>composer-secret</textarea></aside>
    <main role="main" hidden><h1>Trap chat</h1></main>
    <main role="main">
      <h1>fixture chat</h1>
      ${status}
      <div role="list">${inner}</div>
    </main>`;
}

describe("visible probe", () => {
  it("reads only visible sender, text, and clock text", () => {
    const snapshot = readProbe(
      page(
        chat(
          [
            `<div role="listitem" hidden><span>fixture chat</span><p>hidden-secret-row</p><time>08:00</time></div>`,
            `<div role="listitem" aria-hidden="true" data-id="secret-id"><span>fixture chat</span><p>aria-hidden-row</p><time>08:01</time></div>`,
            `<div role="listitem" style="display:none"><span>fixture chat</span><p>display-none-row</p><time>08:02</time></div>`,
            row("fixture chat", "seed-one", "09:00", 'data-id="secret-id"'),
            `<div role="listitem"><p>Today</p></div>`
          ].join("")
        )
      ),
      { requireLayout: false }
    );
    expect(snapshot.layout).toBe("probe-contract");
    expect(snapshot.header).toBe("fixture chat");
    expect(snapshot.phase).toBe("ready");
    expect(snapshot.slots).toEqual([
      { kind: "message", sender: "fixture chat", text: "seed-one", timeText: "09:00" },
      { kind: "separator" }
    ]);
    const encoded = JSON.stringify(snapshot);
    expect(encoded).not.toContain("secret-id");
    expect(encoded).not.toContain("1999-01-01");
    expect(encoded).not.toContain("hidden-secret-row");
    expect(encoded).not.toContain("composer-secret");
    expect(encoded).not.toContain("Other chat preview");
    expect(encoded).not.toContain("Trap chat");
  });

  it("treats a loading status as empty even if a row is already in the DOM", () => {
    const snapshot = readProbe(
      page(chat(row("fixture chat", "seed-one", "09:00"), `<p role="status">Loading messages</p>`)),
      { requireLayout: false }
    );
    expect(snapshot.phase).toBe("loading");
    expect(snapshot.slots).toEqual([]);
    expect(JSON.stringify(snapshot)).not.toContain("seed-one");
  });

  it("fails closed when the open chat region is ambiguous", () => {
    expect(readProbe(page("<h1>Nowhere</h1>"), { requireLayout: false }).layout).toBe("unrecognized");
    expect(
      readProbe(page("<main role='main'><h1>One</h1><h1>Two</h1></main>"), { requireLayout: false }).layout
    ).toBe("unrecognized");
  });

  it("marks a header echo and a clock-less row without using attributes as ids", () => {
    const snapshot = readProbe(
      page(
        chat(
          [
            row("fixture chat", "fixture chat", "09:12"),
            `<div role="listitem"><span>fixture chat</span><p>yesterday text</p><time>Yesterday</time></div>`
          ].join("")
        )
      ),
      { requireLayout: false }
    );
    expect(snapshot.slots.map((slot) => slot.kind)).toEqual(["header-echo", "bad-time"]);
  });
});
