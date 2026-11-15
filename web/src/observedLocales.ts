// Traditional Chinese names below were observed on one live WhatsApp Web build.
// English names are public browser-automation selectors, not a live observation
// by this project. A fixture that uses them is not an end-to-end proof.
//
// English composer prefixes, checked group-first:
// https://github.com/markbus-ai/whatsplay/blob/af5d3306b5f0a3fb399cba5083e5ba90626231f1/src/whatsplay/constants/locator.py
// Header title element: `#main header span[dir="auto"]` in that same file.
// Their tests name the strings "Type a message to Mika Bici" and
// "Type a message to group Tres Chiflados" (tests/test_active_chat.py).
// Drawer heading "Contact info": nico-i/whatsapp-icloud-contact-image-sync
// commit 208fda52 (2024-12-09), an h1. Menu titles "Contact info" and
// "Group info" are the exact title text in public gist 2e6e332fde26def01bb24451cdf57838.
// Info button title "Profile details": the whatsplay locator above.
// Quote aria-label "Quoted message": that same locator.
// Unread: that repo matches an aria-label containing "unread". This tree
// accepts only the exact dot label "unread" with the same structure as 未讀.
// A numbered English badge is not an exact pattern in those sources, so it
// stays fail-closed. "Type a message" with no chat title is not a binding.

export type ChatLabelPattern = {
  id: string;
  headerPrefix: string;
  composerPrefix: string;
  composerSuffix: string;
};

export const OBSERVED_CHAT_LOCALES: readonly ChatLabelPattern[] = [
  {
    id: "zh-Hant",
    headerPrefix: "聯絡資料 ",
    composerPrefix: "輸入要傳送去「",
    composerSuffix: " 」嘅訊息",
  },
];

const TOKEN = /^[A-Za-z0-9._-]{1,40}$/;

export const ENGLISH_DIRECT_COMPOSER_PREFIX = "Type a message to ";
export const ENGLISH_GROUP_COMPOSER_PREFIX = "Type a message to group ";
export const ENGLISH_HEADER_TITLE = "span[dir='auto']";
export const ENGLISH_CONTACT_HEADING = "Contact info";
export const ENGLISH_GROUP_HEADING = "Group info";
export const ENGLISH_PROFILE_BUTTON = "Profile details";
export const ENGLISH_QUOTE_LABEL = "Quoted message";
export const ENGLISH_UNREAD_DOT = "unread";

export function headerTokenFrom(name: string, locales: readonly ChatLabelPattern[]): string | null {
  for (const locale of locales) {
    if (locale.headerPrefix.length === 0 || !name.startsWith(locale.headerPrefix)) continue;
    const label = name.slice(locale.headerPrefix.length);
    if (TOKEN.test(label)) return label;
  }
  return null;
}

export function composerTokenFrom(name: string, locales: readonly ChatLabelPattern[]): string | null {
  for (const locale of locales) {
    if (locale.composerPrefix.length === 0 || locale.composerSuffix.length === 0) continue;
    if (!name.startsWith(locale.composerPrefix) || !name.endsWith(locale.composerSuffix)) continue;
    const label = name.slice(locale.composerPrefix.length, name.length - locale.composerSuffix.length);
    if (TOKEN.test(label)) return label;
  }
  return null;
}

export function englishGroupComposer(name: string): boolean {
  if (!name.startsWith(ENGLISH_GROUP_COMPOSER_PREFIX)) return false;
  return name.slice(ENGLISH_GROUP_COMPOSER_PREFIX.length).trim().length > 0;
}

export function englishDirectToken(name: string): string | null {
  if (name.startsWith(ENGLISH_GROUP_COMPOSER_PREFIX)) return null;
  if (!name.startsWith(ENGLISH_DIRECT_COMPOSER_PREFIX)) return null;
  const title = name.slice(ENGLISH_DIRECT_COMPOSER_PREFIX.length).trim();
  return TOKEN.test(title) ? title : null;
}

export function englishHeaderToken(name: string): string | null {
  return TOKEN.test(name) ? name : null;
}

export const CONTACT_INFO_BUTTON_PREFIX = "聯絡資料 ";
export const GROUP_INFO_BUTTON_PREFIX = "群組資料";
export const CONTACT_DRAWER_HEADING = "聯絡人資料";
export const GROUP_DRAWER_HEADING = "群組資料";
export const CONTACT_DRAWER_HEADINGS = [CONTACT_DRAWER_HEADING, ENGLISH_CONTACT_HEADING] as const;
export const GROUP_DRAWER_HEADINGS = [GROUP_DRAWER_HEADING, ENGLISH_GROUP_HEADING] as const;
export const UNREAD_DOT_LABEL = "未讀";
export const UNREAD_DOT_LABELS = [UNREAD_DOT_LABEL, ENGLISH_UNREAD_DOT] as const;
export const UNREAD_COUNT_SUFFIX = "個未讀訊息";
export const UNREAD_COUNT_LABEL = new RegExp(`^([1-9][0-9]{0,3})${UNREAD_COUNT_SUFFIX}$`);
export const PHONE_FIELD_LABELS = new Set(["手機", "電話", "電話號碼"]);
export const READ_RECEIPT_LABEL = "已讀";
export const QUOTE_MARK = "引用";
export const QUOTE_LABEL_LENGTH = 4;
export const PHONE_HISTORY_CONTROL = "點擊此處從手機取得較舊的訊息。";
export const CLOCK_PERIOD_PREFIXES = ["凌晨", "清晨", "上午", "中午", "下午", "晚上"] as const;
