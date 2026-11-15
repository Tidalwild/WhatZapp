import { clockText, type ProbeSnapshot, type Slot } from "./model.js";

export type ProbeOptions = {
  requireLayout: boolean;
};

const LOADING = /loading|could not load|couldn't load|cannot load/i;

export function readProbe(doc: Document, options: ProbeOptions): ProbeSnapshot {
  const mains = [...doc.querySelectorAll('[role="main"]')].filter((node) => visible(node, options));
  if (mains.length !== 1) return unrecognized();
  const main = mains[0];
  const headings = [...main.querySelectorAll("h1")].filter((node) => visible(node, options));
  if (headings.length !== 1) return unrecognized();
  const header = textOf(headings[0]);
  const status = [...main.querySelectorAll('[role="status"]')].find((node) => visible(node, options));
  const statusText = status ? textOf(status) : "";
  if (LOADING.test(statusText)) {
    return { layout: "probe-contract", header, phase: "loading", slots: [] };
  }
  const lists = [...main.querySelectorAll('[role="list"]')].filter((node) => visible(node, options));
  if (lists.length !== 1) {
    return { layout: "probe-contract", header, phase: "empty", slots: [] };
  }
  const items = [...lists[0].children].filter(
    (node) => node.getAttribute("role") === "listitem" && visible(node, options)
  );
  if (items.length === 0) {
    return { layout: "probe-contract", header, phase: "empty", slots: [] };
  }
  const slots: Slot[] = [];
  for (const item of items) {
    if (editable(item)) continue;
    const children = [...item.children].filter((node) => visible(node, options) && !editable(node));
    if (children.length !== 3 || children.some((node) => editable(node))) {
      slots.push({ kind: "separator" });
      continue;
    }
    const sender = textOf(children[0]);
    const body = textOf(children[1]);
    const timeText = renderedTime(children[2]);
    if (body !== "" && body === header) {
      slots.push({ kind: "header-echo" });
      continue;
    }
    if (!clockText(timeText)) {
      slots.push({ kind: "bad-time" });
      continue;
    }
    if (sender === "" || body === "") {
      slots.push({ kind: "empty-body" });
      continue;
    }
    slots.push({ kind: "message", sender, text: body, timeText: timeText.trim() });
  }
  return { layout: "probe-contract", header, phase: "ready", slots };
}

function unrecognized(): ProbeSnapshot {
  return { layout: "unrecognized", header: "", phase: "empty", slots: [] };
}

function renderedTime(node: Element): string {
  return textOf(node);
}

function textOf(node: Element): string {
  return (node.textContent ?? "").replace(/\s+/g, " ").trim();
}

function editable(node: Element): boolean {
  const tag = node.tagName.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  const editableValue = node.getAttribute("contenteditable");
  return editableValue === "" || editableValue === "true";
}

export function visible(node: Element, options: ProbeOptions): boolean {
  if (node.getAttribute("hidden") !== null) return false;
  if (node.getAttribute("aria-hidden") === "true") return false;
  const style = node.ownerDocument.defaultView?.getComputedStyle(node);
  if (style && (style.display === "none" || style.visibility === "hidden")) return false;
  if (options.requireLayout) {
    const rect = node.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
  }
  return true;
}
