import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { readContactSurface } from "../src/contactSurface.js";
import { isTimestamp } from "../src/chatRead.js";
import { readChatListSignal, emptyMemory } from "../src/listSignal.js";
import {
  CLOCK_PERIOD_PREFIXES,
  CONTACT_DRAWER_HEADING,
  CONTACT_INFO_BUTTON_PREFIX,
  GROUP_DRAWER_HEADING,
  GROUP_INFO_BUTTON_PREFIX,
  OBSERVED_CHAT_LOCALES,
  PHONE_FIELD_LABELS,
  PHONE_HISTORY_CONTROL,
  QUOTE_LABEL_LENGTH,
  QUOTE_MARK,
  READ_RECEIPT_LABEL,
  UNREAD_COUNT_LABEL,
  UNREAD_COUNT_SUFFIX,
  UNREAD_DOT_LABEL,
  composerTokenFrom,
  headerTokenFrom,
  type ChatLabelPattern,
} from "../src/observedLocales.js";
import { locateReportedFrame, readReportedHeader } from "../src/reportedBinding.js";

const zh = OBSERVED_CHAT_LOCALES[0];

function page(body: string): Document {
  const window = new Window();
  window.document.body.innerHTML = body;
  return window.document as unknown as Document;
}

describe("observed WhatsApp locales", () => {
  it("keeps the Traditional Chinese names that were observed live", () => {
    expect(OBSERVED_CHAT_LOCALES.map((locale) => locale.id)).toEqual(["zh-Hant"]);
    expect(zh).toEqual({
      id: "zh-Hant",
      headerPrefix: "聯絡資料 ",
      composerPrefix: "輸入要傳送去「",
      composerSuffix: " 」嘅訊息",
    });
    expect(CONTACT_INFO_BUTTON_PREFIX).toBe(zh.headerPrefix);
    expect(GROUP_INFO_BUTTON_PREFIX).toBe("群組資料");
    expect(CONTACT_DRAWER_HEADING).toBe("聯絡人資料");
    expect(GROUP_DRAWER_HEADING).toBe("群組資料");
    expect(UNREAD_DOT_LABEL).toBe("未讀");
    expect(UNREAD_COUNT_SUFFIX).toBe("個未讀訊息");
    expect(UNREAD_COUNT_LABEL.test("1個未讀訊息")).toBe(true);
    expect([...PHONE_FIELD_LABELS]).toEqual(["手機", "電話", "電話號碼"]);
    expect(READ_RECEIPT_LABEL).toBe("已讀");
    expect(QUOTE_MARK).toBe("引用");
    expect(QUOTE_LABEL_LENGTH).toBe(4);
    expect(PHONE_HISTORY_CONTROL).toBe("點擊此處從手機取得較舊的訊息。");
    expect([...CLOCK_PERIOD_PREFIXES]).toEqual(["凌晨", "清晨", "上午", "中午", "下午", "晚上"]);
  });

  it("reads the observed Traditional Chinese header and composer token", () => {
    const header = `${zh.headerPrefix}contact-a`;
    const composer = `${zh.composerPrefix}contact-a${zh.composerSuffix}`;
    expect(headerTokenFrom(header, OBSERVED_CHAT_LOCALES)).toBe("contact-a");
    expect(composerTokenFrom(composer, OBSERVED_CHAT_LOCALES)).toBe("contact-a");
    expect(
      readReportedHeader(
        page(`<button type="button">${header}</button><div role="textbox">${composer}</div>`),
        { requireLayout: false }
      )
    ).toBe("contact-a");
    const withTitle = page(`
      <header><span dir="auto">contact-a</span></header>
      <button type="button">${header}</button>
      <div role="textbox">${composer}</div>
    `);
    expect(readReportedHeader(withTitle, { requireLayout: false })).toBe("contact-a");
  });

  it("reads the public-source English pair and fail-closes the patterns that source does not support", () => {
    expect(headerTokenFrom("Contact info contact-a", OBSERVED_CHAT_LOCALES)).toBeNull();
    expect(composerTokenFrom("Type a message to contact-a", OBSERVED_CHAT_LOCALES)).toBeNull();
    const english = page(`
      <header><span dir="auto">contact-a</span></header>
      <div role="textbox" contenteditable="true" aria-label="Type a message to contact-a"></div>
    `);
    expect(readReportedHeader(english, { requireLayout: false })).toBe("contact-a");
    expect(locateReportedFrame(english, { requireLayout: false })?.token).toBe("contact-a");
    const loose = page(`<span dir="auto">contact-a</span><div role="textbox" aria-label="Type a message to contact-a"></div>`);
    expect(readReportedHeader(loose, { requireLayout: false })).toBe("");
    const nameless = page(`<header><span dir="auto">contact-a</span></header><div role="textbox" aria-label="Type a message"></div>`);
    expect(readReportedHeader(nameless, { requireLayout: false })).toBe("");
    const spaced = page(`<header><span dir="auto">Mika Bici</span></header><div role="textbox" aria-label="Type a message to Mika Bici"></div>`);
    expect(readReportedHeader(spaced, { requireLayout: false })).toBe("");
    const wrong = page(`<header><span dir="auto">contact-a</span></header><div role="textbox" aria-label="Type a message to contact-b"></div>`);
    expect(readReportedHeader(wrong, { requireLayout: false })).toBe("");
    const group = page(`<header><span dir="auto">contact-a</span></header><div role="textbox" aria-label="Type a message to group contact-a"></div>`);
    expect(readReportedHeader(group, { requireLayout: false })).toBe("");
    const mixed = page(`
      <button type="button">${zh.headerPrefix}contact-a</button>
      <div role="textbox">${zh.composerPrefix}contact-a${zh.composerSuffix}</div>
      <header><span dir="auto">contact-a</span></header>
      <div role="textbox" aria-label="Type a message to contact-a"></div>
    `);
    expect(readReportedHeader(mixed, { requireLayout: false })).toBe("");
    const prefixed = page(`<button type="button">Contact info contact-a</button><div role="textbox" aria-label="Type a message to contact-a"></div>`);
    expect(readReportedHeader(prefixed, { requireLayout: false })).toBe("");
    expect(readContactSurface(page(`<div data-testid="chat-info-drawer"><span>Contact info</span></div>`), { requireLayout: false }).surface).toBe("direct-contact");
    expect(readContactSurface(page(`<div data-testid="chat-info-drawer"><span>Group info</span></div>`), { requireLayout: false }).surface).toBe("group");
    expect(
      readContactSurface(
        page(`<div data-testid="chat-info-drawer"><span>Contact info</span><span>Group info</span></div>`),
        { requireLayout: false }
      ).surface
    ).toBe("unproven");
    const numbered = readChatListSignal(
      page(`<div role="grid" aria-label="Chats"><div role="row"><span>contact-a</span><div role="gridcell"><span data-testid="icon-unread-count" aria-label="1 unread message">1</span></div></div></div>`),
      "contact-a",
      emptyMemory(),
      { requireLayout: false }
    ).signal;
    expect(numbered.mark).toBe("ambiguous");
    const dot = readChatListSignal(
      page(`<div role="grid" aria-label="Chats"><div role="row"><span>contact-a</span><div role="gridcell"><span data-testid="icon-unread-count" aria-label="unread"></span></div></div></div>`),
      "contact-a",
      emptyMemory(),
      { requireLayout: false }
    ).signal;
    expect(dot.mark).toBe("dot");
    expect(isTimestamp("Monday")).toBe(true);
    expect(isTimestamp("10:24 AM")).toBe(true);
  });

  it("accepts a second pattern only when that pattern is passed in, and does not ship it", () => {
    const synthetic: ChatLabelPattern = {
      id: "synthetic-not-observed",
      headerPrefix: "SYNTHETIC HEADER ",
      composerPrefix: "SYNTHETIC COMPOSER ",
      composerSuffix: " END",
    };
    expect(OBSERVED_CHAT_LOCALES.some((locale) => locale.id === synthetic.id)).toBe(false);
    expect(headerTokenFrom("SYNTHETIC HEADER contact-a", [synthetic])).toBe("contact-a");
    expect(composerTokenFrom("SYNTHETIC COMPOSER contact-a END", [synthetic])).toBe("contact-a");
    expect(headerTokenFrom("SYNTHETIC HEADER contact-a", OBSERVED_CHAT_LOCALES)).toBeNull();
    expect(composerTokenFrom("SYNTHETIC COMPOSER contact-a END", OBSERVED_CHAT_LOCALES)).toBeNull();
    expect(isTimestamp("上午10:24")).toBe(true);
    expect(isTimestamp("10:24 AM")).toBe(true);
  });
});
