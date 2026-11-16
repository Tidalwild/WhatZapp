import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { Engine } from "../src/engine.js";
import { allowFixture } from "./scopeFixture.js";
import { acceptSurface, CALIBRATION_OUTGOING_MARKER, classifyContainers, countRowExclusion, readSendSurface, rowStatus } from "../src/sendSurface.js";

const HEADER = "聯絡資料 contact-a";
const NAME = "輸入要傳送去「contact-a 」嘅訊息";

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

function frame(extra: string, composer = ""): string {
  const box = composer === ""
    ? `<div role="textbox" contenteditable="true" aria-label="${NAME}"></div>`
    : `<div role="textbox" contenteditable="true" aria-label="${NAME}">${composer}</div>`;
  return `<button type="button"><span aria-label="${HEADER}"></span>contact-a</button>${box}${extra}`;
}

describe("send surface", () => {
  it("reads an empty composer and does not treat a left row as incoming", () => {
    const doc = page(frame(`
      <div data-testid="chat-info-drawer">
        <span>關於</span>
        <span data-testid="contact-info-subtitle selectable-text">name</span>
        <span data-testid="note-input-field-read-only selectable-text">note</span>
      </div>
      <div data-testid="msg-container" style="text-align: start">
        <span data-testid="selectable-text">contact-a</span>
        <div data-testid="msg-meta"><span>09:01</span></div>
      </div>
    `));
    const surface = readSendSurface(doc, "contact-a", { requireLayout: false });
    expect(surface.composer).toBe("empty");
    expect(surface.identity).toBe("phone-label-absent");
    expect(surface.direction).toBe("unproven");
    expect(surface.outgoingCompared).toBe(false);
    expect(JSON.stringify(surface)).not.toContain("name");
    expect(JSON.stringify(surface)).not.toContain("note");
  });

  it("sees a phone label without reading the value beside it", () => {
    const doc = page(frame(`
      <div data-testid="chat-info-drawer">
        <span>手機</span>
        <span>+852-000</span>
      </div>
    `, "typed"));
    const surface = readSendSurface(doc, "contact-a", { requireLayout: false });
    expect(surface.composer).toBe("occupied");
    expect(surface.identity).toBe("phone-label-present");
    expect(JSON.stringify(surface)).not.toContain("852");
  });

  it("leaves the composer unmeasured when the header does not match", () => {
    const doc = page(frame(""));
    expect(readSendSurface(doc, "Other", { requireLayout: false }).composer).toBe("unmeasured");
    expect(readSendSurface(doc, "contact-a", { requireLayout: false }).identity).toBe("drawer-closed");
  });

  it("excludes only a row with the observed read status pair", () => {
    const outgoing = page(`<div data-testid="msg-container">
      <span data-testid="tail-out" data-icon="tail-out"></span>
      <span role="img" aria-label="read"></span>
      <span aria-label="已讀"></span>
      <span>private-body</span>
    </div>`);
    const incoming = page(`<div data-testid="msg-container" style="text-align: start">
      <span data-testid="selectable-text">contact-a</span>
      <div data-testid="msg-meta"><span>09:01</span></div>
    </div>`);
    const tailOnly = page(`<div data-testid="msg-container"><span data-testid="tail-out" data-icon="tail-out"></span></div>`);
    const labelOnly = page(`<div data-testid="msg-container"><span aria-label="已讀"></span></div>`);
    const imageOnly = page(`<div data-testid="msg-container"><span role="img" aria-label="read"></span></div>`);
    expect(rowStatus(outgoing.querySelector('[data-testid="msg-container"]') as Element)).toBe("outgoing-excluded");
    expect(rowStatus(incoming.querySelector('[data-testid="msg-container"]') as Element)).toBe("unproven");
    expect(rowStatus(tailOnly.querySelector('[data-testid="msg-container"]') as Element)).toBe("unproven");
    expect(rowStatus(labelOnly.querySelector('[data-testid="msg-container"]') as Element)).toBe("unproven");
    expect(rowStatus(imageOnly.querySelector('[data-testid="msg-container"]') as Element)).toBe("unproven");
    expect(JSON.stringify(rowStatus(outgoing.querySelector('[data-testid="msg-container"]') as Element))).not.toContain("private-body");
  });

  it("counts the pair inside the open panel and does not call the other rows incoming", async () => {
    const doc = page(`
      <div data-testid="conversation-panel-wrapper">
        <button type="button"><span aria-label="${HEADER}"></span>contact-a</button>
        <div role="textbox" contenteditable="true" aria-label="${NAME}"></div>
        <div data-testid="msg-container"><span role="img" aria-label="read"></span><span aria-label="已讀"></span></div>
        <div data-testid="msg-container" style="text-align: end"><span data-testid="tail-out"></span></div>
      </div>
    `);
    const surface = readSendSurface(doc, "contact-a", { requireLayout: false });
    expect(surface.direction).toBe("unproven");
    expect(surface.exclusion).toEqual({ excluded: 1, quoteStructure: 0, unproven: 1 });
    let n = 0;
    const engine = new Engine({ now: () => 10, ids: () => `id-${n += 1}`, secretHex: "ab".repeat(32) });
    engine.acceptOnboarding(true);
    engine.bindMetadata("contact-a");
    engine.setScope(allowFixture());
    engine.setReplyGrant(true);
    const onlyOutgoing = engine.assessAutomaticReply({
      disposition: "READ",
      header: "contact-a",
      exclusion: { excluded: 1, unproven: 0 }
    });
    expect(onlyOutgoing.blocked).toContain("OUTGOING_EXCLUDED");
    expect(onlyOutgoing.delivered).toBe(false);
    const mixed = engine.assessAutomaticReply({
      disposition: "READ",
      header: "contact-a",
      exclusion: surface.exclusion
    });
    expect(mixed.blocked).not.toContain("OUTGOING_EXCLUDED");
    expect(mixed.blocked).toContain("DIRECTION_UNPROVEN");
    const refused = await engine.attemptLiveDelivery("hello", surface);
    expect(refused.blocked).not.toContain("OUTGOING_EXCLUDED");
    expect(refused.persisted).toBe(false);
    expect(refused.acted).toBe(false);
  });

  it("drops a forged direction or identity from a page message", () => {
    const accepted = acceptSurface({
      composer: "empty",
      identity: "phone-label-absent",
      direction: "in",
      outgoingCompared: true,
      evidenceId: "guessed-selector"
    });
    expect(accepted.direction).toBe("unproven");
    expect(accepted.outgoingCompared).toBe(false);
    expect(accepted.exclusion).toEqual({ excluded: 0, quoteStructure: 0, unproven: 0 });
    expect(accepted).not.toHaveProperty("evidenceId");
    const forgedOutgoing = acceptSurface({ direction: "in", exclusion: { excluded: 2, unproven: 0 } });
    expect(forgedOutgoing.direction).toBe("unproven");
    expect(forgedOutgoing.exclusion).toEqual({ excluded: 2, quoteStructure: 0, unproven: 0 });
  });

  it("does not persist when the measured surface still lacks identity and direction", async () => {
    let n = 0;
    const engine = new Engine({ now: () => 10, ids: () => `id-${n += 1}`, secretHex: "ab".repeat(32) });
    engine.acceptOnboarding(true);
    engine.bindMetadata("contact-a");
    engine.setScope(allowFixture());
    engine.setReplyGrant(true);
    const doc = page(frame(`
      <div data-testid="chat-info-drawer"><span>關於</span></div>
      <div data-testid="conv-msg-a" data-id="occ-1">
        <div data-testid="msg-container"><span data-testid="selectable-text">contact-a</span></div>
      </div>
    `));
    const result = await engine.attemptLiveDelivery("do not send", readSendSurface(doc, "contact-a", { requireLayout: false }));
    expect(result.reason).toBe("EVIDENCE_NOT_MEASURED");
    expect(result.blocked).toEqual(expect.arrayContaining([
      "IDENTITY_UNPROVEN",
      "PHONE_LABEL_ABSENT",
      "DIRECTION_UNPROVEN",
      "OUTGOING_UNCOMPARED",
      "ACTUATOR_NOT_WIRED"
    ]));
    expect(result.persisted).toBe(false);
    expect(result.acted).toBe(false);
    expect(engine.dump().deliveryRecords).toEqual([]);
  });

  it("records a quote of an earlier outgoing marker as structure, not incoming", async () => {
    const marker = CALIBRATION_OUTGOING_MARKER;
    const outgoing = `<div data-testid="msg-container"><span data-testid="selectable-text">${marker}</span><span data-testid="tail-out"></span><span role="img" aria-label="name-read-xx"></span><span aria-label="已讀"></span></div>`;
    const quoting = `<div data-testid="msg-container"><div data-testid="quoted-message"><span data-testid="selectable-text">${marker}</span></div><button type="button">${marker}</button><button type="button" aria-label="引用甲乙"></button><span data-testid="tail-in"></span></div>`;
    const rows = (html: string) => {
      const doc = page(html);
      return [...doc.querySelectorAll('[data-testid="msg-container"]')];
    };
    expect(classifyContainers(rows(`${outgoing}${quoting}`))).toEqual(["outgoing-excluded", "quote-structure"]);
    const englishQuote = quoting.replace('aria-label="引用甲乙"', 'aria-label="Quoted message"');
    expect(classifyContainers(rows(`${outgoing}${englishQuote}`))).toEqual(["outgoing-excluded", "quote-structure"]);
    const sent = `<div data-testid="msg-container"><span data-testid="selectable-text">hello</span><span aria-label="Sent"></span></div>`;
    expect(classifyContainers(rows(sent))).toEqual(["unproven"]);
    expect(classifyContainers(rows(`${outgoing}<div data-testid="msg-container"><span data-testid="tail-in"></span></div>`))[1]).toBe("unproven");
    expect(classifyContainers(rows(quoting))).toEqual(["unproven"]);
    expect(classifyContainers(rows(`${outgoing}<div data-testid="msg-container"><div data-testid="quoted-message"><span data-testid="selectable-text">not-a-known-outgoing</span></div><button type="button">not-a-known-outgoing</button><button type="button" aria-label="引用甲乙"></button></div>`))[1]).toBe("unproven");
    const quotedOutgoing = `<div data-testid="msg-container"><div data-testid="quoted-message"><span data-testid="selectable-text">${marker}</span></div><button type="button">${marker}</button><button type="button" aria-label="引用甲乙"></button><span role="img" aria-label="read"></span><span aria-label="已讀"></span></div>`;
    expect(classifyContainers(rows(`${outgoing}${quotedOutgoing}`))[1]).toBe("outgoing-excluded");
    expect(classifyContainers(rows(`<div data-testid="msg-container" style="text-align: start"><span data-testid="tail-in"></span></div>`))).toEqual(["unproven"]);
    const doc = page(`
      <div data-testid="conversation-panel-wrapper">
        <button type="button"><span aria-label="${HEADER}"></span>contact-a</button>
        <div role="textbox" contenteditable="true" aria-label="${NAME}"></div>
        ${outgoing}${quoting}
      </div>
    `);
    const surface = readSendSurface(doc, "contact-a", { requireLayout: false });
    expect(surface.direction).toBe("unproven");
    expect(surface.exclusion).toEqual({ excluded: 1, quoteStructure: 1, unproven: 0 });
    expect(JSON.stringify(surface)).not.toContain(marker);
    let n = 0;
    const engine = new Engine({ now: () => 10, ids: () => `id-${n += 1}`, secretHex: "ab".repeat(32) });
    engine.acceptOnboarding(true);
    engine.bindMetadata("contact-a");
    engine.setScope(allowFixture());
    engine.setReplyGrant(true);
    const decision = engine.assessAutomaticReply({ disposition: "READ", header: "contact-a", exclusion: surface.exclusion });
    expect(decision.blocked).toContain("QUOTE_NOT_DIRECTION");
    expect(decision.blocked).toContain("DIRECTION_UNPROVEN");
    expect(decision.blocked).toContain("STABLE_ID_NOT_DIRECTION");
    expect(decision.delivered).toBe(false);
    const delivery = await engine.attemptLiveDelivery("hello", surface);
    expect(delivery.blocked).toContain("DIRECTION_UNPROVEN");
    expect(delivery.blocked).toContain("IDENTITY_UNPROVEN");
    expect(delivery.blocked).toContain("LIVE_SEND_CLOSED");
    expect(delivery.blocked).toContain("ACTUATOR_NOT_WIRED");
    expect(delivery.persisted).toBe(false);
    expect(delivery.acted).toBe(false);
    expect(engine.view().deliveryEnabled).toBe(false);
    expect(engine.view().verifiedRemoteRecipient).toBe(false);
    expect(engine.dump().deliveryRecords).toEqual([]);
  });

  it("keeps an own quote unproven across status, virtualization, mixed rows, and a changed pane", async () => {
    const marker = CALIBRATION_OUTGOING_MARKER;
    const outgoing = `<div data-testid="msg-container"><span data-testid="selectable-text">${marker}</span><span role="img" aria-label="name-read-xx"></span><span aria-label="已讀"></span></div>`;
    const quote = (status: string) =>
      `<div data-testid="msg-container"><div data-testid="quoted-message"><span data-testid="selectable-text">${marker}</span></div><button type="button">${marker}</button><button type="button" aria-label="引用甲乙"></button>${status}</div>`;
    const rowsOf = (html: string) => [...page(html).querySelectorAll('[data-testid="msg-container"]')];
    const pending = `<span aria-label="fixture-pending"></span>`;
    const sent = `<span role="img" aria-label="fixture-sent"></span>`;
    const unread = `<span aria-label="fixture-unread"></span>`;
    for (const status of ["", pending, sent, unread]) {
      const classified = classifyContainers(rowsOf(`${outgoing}${quote(status)}`));
      expect(classified).toEqual(["outgoing-excluded", "quote-structure"]);
    }
    const older = `<div data-testid="msg-container"><span data-testid="tail-in"></span></div>`;
    const mixed = classifyContainers(rowsOf(`${outgoing}${quote("")}${older}`));
    expect(mixed).toEqual(["outgoing-excluded", "quote-structure", "unproven"]);

    const panel = (body: string) => page(`
      <div data-testid="conversation-panel-wrapper">
        <button type="button"><span aria-label="${HEADER}"></span>contact-a</button>
        <div role="textbox" contenteditable="true" aria-label="${NAME}"></div>
        ${body}
      </div>
    `);
    const mounted = panel(`${outgoing}${quote("")}${older}`);
    expect(countRowExclusion(mounted, "contact-a", { requireLayout: false })).toEqual({
      excluded: 1,
      quoteStructure: 1,
      unproven: 1
    });
    const quotedRow = mounted.querySelector('[data-testid="quoted-message"]')?.closest('[data-testid="msg-container"]');
    expect(quotedRow).not.toBeNull();
    quotedRow?.setAttribute("style", "display: none");
    expect(countRowExclusion(mounted, "contact-a", { requireLayout: false }).quoteStructure).toBe(0);
    quotedRow?.remove();
    const afterScroll = countRowExclusion(mounted, "contact-a", { requireLayout: false });
    expect(afterScroll).toEqual({ excluded: 1, quoteStructure: 0, unproven: 1 });

    const other = page(`
      <div data-testid="conversation-panel-wrapper">
        <button type="button"><span aria-label="聯絡資料 Other"></span>Other</button>
        <div role="textbox" contenteditable="true" aria-label="輸入要傳送去「Other 」嘅訊息"></div>
        ${outgoing}${quote("")}
      </div>
    `);
    expect(countRowExclusion(other, "contact-a", { requireLayout: false })).toEqual({
      excluded: 0,
      quoteStructure: 0,
      unproven: 0
    });
    const stale = acceptSurface({
      composer: "empty",
      exclusion: { excluded: 0, quotingIncoming: 3, unproven: 0 }
    });
    expect(stale.exclusion.quoteStructure).toBe(0);
    expect(stale.direction).toBe("unproven");

    let n = 0;
    const engine = new Engine({ now: () => 10, ids: () => `id-${n += 1}`, secretHex: "ab".repeat(32) });
    engine.acceptOnboarding(true);
    engine.bindMetadata("contact-a");
    const off = engine.assessAutomaticReply({
      disposition: "READ",
      header: "contact-a",
      exclusion: { excluded: 1, quoteStructure: 1, unproven: 1 }
    });
    expect(off.blocked).toContain("GRANT_OFF");
    expect(off.blocked).not.toContain("BINDING_MISMATCH");
    expect(off.blocked).toContain("QUOTE_NOT_DIRECTION");
    expect(off.blocked).toContain("DIRECTION_UNPROVEN");
    expect(off.blocked).toContain("STABLE_ID_NOT_DIRECTION");
    expect(off.blocked).toContain("EMPTY_REPLY");
    expect(off.delivered).toBe(false);
    const coverageOnly = engine.assessAutomaticReply({ disposition: "READ", header: "contact-a" });
    expect(coverageOnly.blocked).not.toContain("QUOTE_NOT_DIRECTION");
    expect(coverageOnly.blocked).toContain("DIRECTION_UNPROVEN");
    expect(coverageOnly.blocked).not.toContain("BINDING_MISMATCH");
    const delivery = await engine.attemptLiveDelivery("hello", readSendSurface(mounted, "contact-a", { requireLayout: false }));
    expect(delivery.blocked).toContain("DIRECTION_UNPROVEN");
    expect(delivery.blocked).toContain("LIVE_SEND_CLOSED");
    expect(delivery.persisted).toBe(false);
    expect(delivery.acted).toBe(false);
    expect(engine.view().deliveryEnabled).toBe(false);
  });
});
