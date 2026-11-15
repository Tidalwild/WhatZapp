import { Window } from "happy-dom";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { candidateLive, holdCandidate } from "../src/candidateSession.js";
import { allowAttentionRead, readContactSurface } from "../src/contactSurface.js";
import { readSendSurface } from "../src/sendSurface.js";
import { openResolvedRow } from "../src/personWatch.js";

const cues = JSON.parse(readFileSync(new URL("./fixtures/contact-info-cues.json", import.meta.url), "utf8")) as {
  openedSurface: { row: string; panelTestId: string; heading: string; groupInfoHeadingPresent: boolean };
  identityCandidate: {
    explicitPhoneLabelPresent: boolean;
    lengthCharacters: number;
    digitCount: number;
    plusSign: boolean;
    punctuation: boolean;
    letters: number;
    uniqueOrStableIdentityProven: boolean;
  };
  limits: { naturalPersonVsBusinessProven: boolean; groupInfoInspected: boolean };
};

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

function phoneShape(): string {
  const spec = cues.identityCandidate;
  const digits = "12345678901".slice(0, spec.digitCount);
  const value = `+${digits.slice(0, 4)}-${digits.slice(4, 7)}-${digits.slice(7)}`;
  expect(value).toHaveLength(spec.lengthCharacters);
  expect(value.replace(/\D/g, "")).toHaveLength(spec.digitCount);
  expect(value.includes("+")).toBe(spec.plusSign);
  expect(/[^0-9+]/.test(value)).toBe(spec.punctuation);
  expect(/[A-Za-z]/.test(value)).toBe(spec.letters > 0);
  return value;
}

function drawer(inner: string): string {
  return `<div data-testid="${cues.openedSurface.panelTestId}">${inner}</div>`;
}

describe("open contact info", () => {
  it("classifies the measured heading as a direct contact and does not enroll the unlabeled number", () => {
    expect(cues.limits.naturalPersonVsBusinessProven).toBe(false);
    expect(cues.limits.groupInfoInspected).toBe(false);
    expect(cues.identityCandidate.explicitPhoneLabelPresent).toBe(false);
    expect(cues.identityCandidate.uniqueOrStableIdentityProven).toBe(false);
    const phone = phoneShape();
    const row = cues.openedSurface.row;
    const doc = page(`
      <button type="button" aria-label="聯絡資料 ${row}"></button>
      <div role="textbox" contenteditable="true" aria-label="輸入要傳送去「${row} 」嘅訊息"></div>
      ${drawer(`<span>${cues.openedSurface.heading}</span><span>關於</span><span>${phone}</span>`)}
    `);
    const surface = readContactSurface(doc, { requireLayout: false });
    expect(surface).toEqual({ surface: "direct-contact" });
    const serialized = JSON.stringify(surface);
    expect(serialized).not.toContain(phone);
    expect(serialized).not.toContain(row);
    expect(serialized).not.toContain("關於");
    const send = readSendSurface(doc, row, { requireLayout: false });
    expect(send.identity).toBe("phone-label-absent");
    expect(send.direction).toBe("unproven");
    expect(JSON.stringify(send)).not.toContain(phone);
  });

  it("does not treat a header name, a phone shape, or a missing heading as a direct contact", () => {
    const phone = phoneShape();
    const named = page(`<button aria-label="聯絡資料 ${cues.openedSurface.row}"></button>`);
    expect(readContactSurface(named, { requireLayout: false }).surface).toBe("unproven");
    const unlabeled = page(drawer(`<span>關於</span><span>${phone}</span>`));
    expect(readContactSurface(unlabeled, { requireLayout: false }).surface).toBe("unproven");
    const other = page(drawer("<span>其他</span>"));
    expect(readContactSurface(other, { requireLayout: false }).surface).toBe("unproven");
    const doubled = page(`${drawer(`<span>${cues.openedSurface.heading}</span>`)}${drawer(`<span>${cues.openedSurface.heading}</span>`)}`);
    expect(readContactSurface(doubled, { requireLayout: false }).surface).toBe("unproven");
    expect(readContactSurface(page(drawer("<span>Contact info</span>")), { requireLayout: false }).surface).toBe("direct-contact");
    expect(readContactSurface(page(drawer("<span>Group info</span>")), { requireLayout: false }).surface).toBe("group");
    expect(readContactSurface(page(drawer("<h1>Contact info</h1><span>Group info</span>")), { requireLayout: false }).surface).toBe("unproven");
  });

  it("keeps a session handle on the element and drops it when that element changes", async () => {
    const doc = page(`
      <div role="grid">
        <div role="row" data-testid="list-item-0"><span>list-item-0</span></div>
        <div role="row" data-testid="list-item-0"><span>list-item-0</span></div>
      </div>
    `);
    const [first, second] = [...doc.querySelectorAll("[role='row']")];
    let serial = 0;
    const mint = () => `h-${(++serial).toString(16).padStart(16, "0")}`;
    const handle = holdCandidate(first, mint);
    const other = holdCandidate(second, mint);
    expect(handle).toBe("h-0000000000000001");
    expect(other).not.toBe(handle);
    expect(candidateLive(first, handle!)).toBe(true);
    expect(allowAttentionRead("direct-contact", first, handle!)).toBe("READ_ATTENTION");
    expect(allowAttentionRead("unproven", first, handle!)).toBe("UNPROVEN");
    first.textContent = "changed";
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(candidateLive(first, handle!)).toBe(false);
    expect(allowAttentionRead("direct-contact", first, handle!)).toBe("STALE_CANDIDATE");
    expect(candidateLive(second, other!)).toBe(true);
    first.setAttribute("data-testid", "list-item-4");
    const again = holdCandidate(first, mint);
    expect(again).not.toBe(handle);
    first.remove();
    expect(candidateLive(first, again!)).toBe(false);
    const clicks: string[] = [];
    first.addEventListener?.("click", () => clicks.push("clicked"));
    expect(openResolvedRow(doc, { "list-item-0": "ref-0000000000000001" }, "ref-0000000000000001", { requireLayout: false }).disposition).not.toBe("OPENED");
    expect(clicks).toEqual([]);
    expect(JSON.stringify({ handle, other })).not.toContain("list-item");
  });
});
