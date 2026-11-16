// English is the default. Traditional Chinese is a display label.
// Machine reasons stay English in both languages so logs do not change.

export type Language = "en" | "zh-Hant";

const PHRASES = {
  en: {
    sendingOff: "Sending is off. Approval is not delivery.",
    contextOff: "Context is off until you enable it for this chat.",
    contextOn: "Context is on for this chat only. Other chats stay out.",
    authorship: "An occupied text box does not show who typed it.",
    absence: "No recorded draft here does not mean your routine cannot draft.",
    ambiguous: "The last send result is ambiguous. It will not be retried.",
    approved: "This exact text is approved and was not sent."
  },
  "zh-Hant": {
    sendingOff: "傳送保持關閉。批准不是送出。",
    contextOff: "在你為這個對話啟用之前，上下文保持關閉。",
    contextOn: "上下文只用於這個對話。其他對話不會帶入。",
    authorship: "文字方塊有字並不能說明是誰輸入的。",
    absence: "這裡沒有記下草稿，並不表示你的例程不能起草。",
    ambiguous: "上一次送出結果不明。不會再試一次。",
    approved: "這段文字已批准，而且沒有送出。"
  }
} as const;

export type Phrase = keyof (typeof PHRASES)["en"];

export function phrase(language: Language, key: Phrase): string {
  const table = language === "zh-Hant" ? PHRASES["zh-Hant"] : PHRASES.en;
  return table[key];
}

export function approvalPreview(text: string): string {
  return text;
}
