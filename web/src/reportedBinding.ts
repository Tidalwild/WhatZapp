import {
  ENGLISH_HEADER_TITLE,
  OBSERVED_CHAT_LOCALES,
  composerTokenFrom,
  englishDirectToken,
  englishGroupComposer,
  englishHeaderToken,
  headerTokenFrom,
} from "./observedLocales.js";
import type { ProbeOptions } from "./probe.js";

const NAME_LIMIT = 80;

// Exact accessible names from the open chat. The button's rendered
// text is not the header name. The composer name is the textbox name.
// A visible word, including one outside the chat grid, is neither.
// Traditional Chinese names come from OBSERVED_CHAT_LOCALES. English uses
// the public composer prefixes and a header span[dir=auto]. A group composer,
// a nameless "Type a message", or both locales at once fail closed.
const AUTHOR_ATTRS = ["aria-label", "aria-placeholder", "placeholder", "title"] as const;
const CONFLICT = "\u0000";

export type ReportedFrame = {
  token: string;
  header: Element;
  composer: Element;
};

type LocaleHit = { token: string; node: Element; button: boolean };

export function locateReportedFrame(doc: Document, options: ProbeOptions): ReportedFrame | null {
  const seen = collectReported(doc, options);
  if (seen === null || seen.duplicate) return null;
  const pair = agree(seen, true);
  if (pair === null || pair.header === null || pair.composer === null) return null;
  return { token: pair.token, header: pair.header, composer: pair.composer };
}

export function readReportedHeader(doc: Document, options: ProbeOptions): string {
  const seen = collectReported(doc, options);
  if (seen === null) return "";
  return agree(seen, false)?.token ?? "";
}

export function visibleEnglishGroupComposer(doc: Document, options: ProbeOptions): boolean {
  const seen = collectReported(doc, options);
  return seen?.group === true;
}

export function classifyPeekTransport(message: string): "content-script-missing" | "unavailable" {
  if (message.includes("Receiving end does not exist") || message.includes("Could not establish connection")) {
    return "content-script-missing";
  }
  return "unavailable";
}

function namesOf(node: Element): string[] {
  const found: string[] = [];
  const push = (name: string | null) => {
    if (name !== null && !found.includes(name)) found.push(name);
  };
  push(authoredName(node));
  push(contentsName(node));
  if (isButton(node)) push(buttonName(node));
  if (isTextbox(node)) push(textboxName(node));
  return found;
}

type Collected = {
  zhHeader: LocaleHit | null;
  zhComposer: LocaleHit | null;
  enHeader: LocaleHit | null;
  enComposer: LocaleHit | null;
  group: boolean;
  duplicate: boolean;
};

function collectReported(doc: Document, options: ProbeOptions): Collected | null {
  const seen: Collected = { zhHeader: null, zhComposer: null, enHeader: null, enComposer: null, group: false, duplicate: false };
  for (const node of eachElement(doc, options)) {
    if (!rendered(node, options)) continue;
    for (const name of namesOf(node)) {
      if (name === CONFLICT) return null;
      if (englishGroupComposer(name) && isTextbox(node)) seen.group = true;
      const zhHeader = headerTokenFrom(name, OBSERVED_CHAT_LOCALES);
      if (zhHeader !== null) {
        if (!keep(seen, "zhHeader", zhHeader, node, isButton(node))) return null;
        continue;
      }
      const zhComposer = composerTokenFrom(name, OBSERVED_CHAT_LOCALES);
      if (zhComposer !== null) {
        if (!keep(seen, "zhComposer", zhComposer, node, isTextbox(node))) return null;
        continue;
      }
      if (englishHeaderToken(name) !== null && englishTitleSpan(node)) {
        if (!keep(seen, "enHeader", name, node, true)) return null;
        continue;
      }
      const enComposer = isTextbox(node) ? englishDirectToken(name) : null;
      if (enComposer !== null && !keep(seen, "enComposer", enComposer, node, true)) return null;
    }
  }
  return seen;
}

function keep(
  seen: Collected,
  key: "zhHeader" | "zhComposer" | "enHeader" | "enComposer",
  token: string,
  node: Element,
  structural: boolean
): boolean {
  const current = seen[key];
  if (current !== null && current.token !== token) return false;
  if (current !== null && current.node !== node && structural && current.button) seen.duplicate = true;
  if (current === null || (structural && !current.button)) seen[key] = { token, node, button: structural };
  return true;
}

function agree(seen: Collected, frame: boolean): { token: string; header: Element | null; composer: Element | null } | null {
  const zh = seen.zhHeader !== null || seen.zhComposer !== null;
  if (seen.group || (zh && seen.enComposer !== null)) return null;
  if (zh && seen.enHeader !== null) {
    const zhToken = seen.zhHeader?.token ?? seen.zhComposer?.token ?? "";
    if (zhToken !== "" && seen.enHeader.token !== zhToken) return null;
  }
  if (zh && seen.zhHeader !== null && seen.zhComposer !== null && seen.zhHeader.token === seen.zhComposer.token) {
    if (frame && (!seen.zhHeader.button || !seen.zhComposer.button)) return null;
    return { token: seen.zhHeader.token, header: seen.zhHeader.node, composer: seen.zhComposer.node };
  }
  if (!zh && seen.enHeader !== null && seen.enComposer !== null && seen.enHeader.token === seen.enComposer.token) {
    return { token: seen.enHeader.token, header: seen.enHeader.node, composer: seen.enComposer.node };
  }
  return null;
}

function englishTitleSpan(node: Element): boolean {
  if (isTextbox(node)) return false;
  if (!node.matches(ENGLISH_HEADER_TITLE)) return false;
  return node.closest("header") !== null;
}

function headerToken(name: string): string | null {
  return headerTokenFrom(name, OBSERVED_CHAT_LOCALES);
}

function composerToken(name: string): string | null {
  return composerTokenFrom(name, OBSERVED_CHAT_LOCALES);
}

function authoredName(node: Element): string | null {
  if (node.hasAttribute("aria-labelledby")) return labelledBy(node);
  for (const attr of AUTHOR_ATTRS) {
    if (!node.hasAttribute(attr)) continue;
    return bounded(node.getAttribute(attr) ?? "");
  }
  return null;
}

function labelledBy(node: Element): string | null {
  if (!node.hasAttribute("aria-labelledby")) return null;
  const ids = (node.getAttribute("aria-labelledby") ?? "").trim().split(/\s+/).filter(Boolean);
  if (ids.length === 0) return null;
  const parts: string[] = [];
  for (const id of ids) {
    const target = node.ownerDocument.getElementById(id);
    if (!target) return null;
    const name = target.getAttribute("aria-label") || target.getAttribute("alt") || target.textContent || "";
    const text = bounded(name);
    if (text === null) return null;
    parts.push(text);
  }
  return bounded(parts.join(" "));
}

function contentsName(node: Element): string | null {
  if (isTextbox(node)) return null;
  const text = bounded(node.textContent ?? "");
  if (text === null) return null;
  if (node.childElementCount === 0) return text;
  const role = node.getAttribute("role");
  const tag = node.tagName;
  if (role === "button" || role === "link" || role === "heading" || tag === "BUTTON" || tag === "A" || /^H[1-6]$/.test(tag)) {
    return text;
  }
  return null;
}

function buttonName(node: Element): string | null {
  let found: string | null = null;
  for (const child of descendants(node)) {
    if (ariaHidden(child)) continue;
    const authored = child.getAttribute("aria-label") || (child.tagName === "IMG" ? child.getAttribute("alt") : null);
    const exact = exactPattern(authored ?? "");
    if (exact === null) continue;
    if (found !== null && found !== exact) return CONFLICT;
    found = exact;
  }
  if (found !== null) return found;
  const composed = bounded(
    `${cssContent(node, "::before")}${node.textContent ?? ""}${cssContent(node, "::after")}`
  );
  return exactPattern(composed ?? "");
}

function textboxName(node: Element): string | null {
  const placeholder = node.getAttribute("aria-placeholder") || node.getAttribute("placeholder");
  const fromPlaceholder = exactPattern(placeholder ?? "");
  if (fromPlaceholder !== null) return fromPlaceholder;
  const fromLabel = exactPattern(htmlLabel(node) ?? "");
  if (fromLabel !== null) return fromLabel;
  return exactPattern(inputValue(node)) ?? exactPattern(node.textContent ?? "");
}

function inputValue(node: Element): string {
  if (!("value" in node)) return "";
  const value = (node as HTMLInputElement).value;
  return typeof value === "string" ? value : "";
}

function exactPattern(raw: string): string | null {
  const text = normalize(raw);
  if (text.length === 0 || text.length > NAME_LIMIT) return null;
  if (headerToken(text) !== null || composerToken(text) !== null) return text;
  return null;
}

function htmlLabel(node: Element): string | null {
  const id = node.getAttribute("id");
  if (id && /^[A-Za-z0-9_.:-]+$/.test(id)) {
    const label = node.ownerDocument.querySelector(`label[for="${id}"]`);
    if (label) return label.textContent;
  }
  const wrapping = node.closest("label");
  if (!wrapping) return null;
  const clone = wrapping.cloneNode(true) as Element;
  for (const child of clone.querySelectorAll("input, textarea, select, button")) child.remove();
  return clone.textContent;
}

function cssContent(node: Element, pseudo: "::before" | "::after"): string {
  let raw = "";
  try {
    raw = node.ownerDocument.defaultView?.getComputedStyle(node, pseudo).content ?? "";
  } catch {
    return "";
  }
  if (raw === "" || raw === "none" || raw === "normal") return "";
  const parts: string[] = [];
  const pattern = /"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(raw))) parts.push((match[1] ?? match[2] ?? "").replace(/\\(.)/g, "$1"));
  const text = parts.join("");
  return text.length > NAME_LIMIT ? "" : text;
}

function isButton(node: Element): boolean {
  if (node.tagName === "BUTTON" || node.getAttribute("role") === "button") return true;
  if (node.tagName !== "INPUT") return false;
  const type = (node.getAttribute("type") ?? "").toLowerCase();
  return type === "button" || type === "submit" || type === "reset";
}

function isTextbox(node: Element): boolean {
  const role = node.getAttribute("role");
  if (role === "textbox" || role === "searchbox") return true;
  if (node.tagName === "TEXTAREA") return true;
  const editable = node.getAttribute("contenteditable");
  if (editable === "" || editable === "true") return true;
  if (node.tagName !== "INPUT") return false;
  const type = (node.getAttribute("type") ?? "text").toLowerCase();
  return !["button", "submit", "reset", "checkbox", "radio", "file", "image", "hidden", "range", "color"].includes(type);
}

function rendered(node: Element, options: ProbeOptions): boolean {
  let current: Element | null = node;
  while (current) {
    if (current.getAttribute("hidden") !== null || current.getAttribute("aria-hidden") === "true") return false;
    const root: Node = current.getRootNode();
    if (root.nodeType === 11 && "host" in root) {
      const host: Element = (root as ShadowRoot).host;
      current = host;
      continue;
    }
    current = current.parentElement;
  }
  const style = node.ownerDocument.defaultView?.getComputedStyle(node);
  if (style && (style.display === "none" || style.visibility === "hidden")) return false;
  if (!options.requireLayout) return true;
  for (const box of [node, node.parentElement]) {
    if (!box) continue;
    const rect = box.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return true;
  }
  return false;
}

function ariaHidden(node: Element): boolean {
  let current: Element | null = node;
  while (current) {
    if (current.getAttribute("hidden") !== null || current.getAttribute("aria-hidden") === "true") return true;
    current = current.parentElement;
  }
  return false;
}

function descendants(node: Element): Element[] {
  const found: Element[] = [];
  const walk = (root: ParentNode) => {
    for (const child of root.querySelectorAll("*")) {
      found.push(child);
      if (child.shadowRoot) walk(child.shadowRoot);
    }
  };
  walk(node);
  return found;
}

function eachElement(doc: Document, options: ProbeOptions): Element[] {
  const found: Element[] = [];
  const seen = new Set<ParentNode>();
  const walk = (root: ParentNode) => {
    if (seen.has(root)) return;
    seen.add(root);
    const scope = root.nodeType === 9 ? (root as Document).body : root;
    if (!scope || !("querySelectorAll" in scope)) return;
    for (const node of scope.querySelectorAll("*")) {
      found.push(node);
      if (node.shadowRoot) walk(node.shadowRoot);
      if (node.tagName !== "IFRAME" && node.tagName !== "FRAME") continue;
      if (!rendered(node, options)) continue;
      try {
        const inner = (node as HTMLIFrameElement).contentDocument;
        if (inner) walk(inner);
      } catch {
        // A cross-origin frame is not this document.
      }
    }
  };
  walk(doc);
  return found;
}

function bounded(value: string): string | null {
  if (value.length > NAME_LIMIT) return null;
  const text = normalize(value);
  if (text.length === 0 || text.length > NAME_LIMIT) return null;
  return text;
}

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}
