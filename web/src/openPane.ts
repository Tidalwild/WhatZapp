// Open-chat attention. A new tail container while a direct contact is open
// is one targetless hint. It is not incoming proof. The first sample is a
// baseline. A composer going empty does not say which new container is the
// own reply, so that sample still hints once. A rebuilt pane does not hint.
// Nothing here is posted except a later generation number.

import { readContactSurface } from "./contactSurface.js";
import { visible, type ProbeOptions } from "./probe.js";
import { locateReportedFrame, visibleEnglishGroupComposer } from "./reportedBinding.js";

const MESSAGES = "conversation-panel-messages";
const CONTAINER = "msg-container";

export type PaneDisposition = "QUIET" | "CLEAN" | "GROUP" | "UNPROVEN" | "BASELINE" | "SAME" | "STALE" | "HINT";

export type PaneMemory = {
  header: string;
  surface: "" | "direct-contact" | "group";
  tail: Element | null;
  generation: number;
};

export function emptyPaneMemory(): PaneMemory {
  return { header: "", surface: "", tail: null, generation: 0 };
}

export function observeOpenPane(
  doc: Document,
  memory: PaneMemory,
  options: ProbeOptions
): { disposition: PaneDisposition; generation: number } {
  const surface = readContactSurface(doc, options).surface;
  const frame = locateReportedFrame(doc, options);
  if (visibleEnglishGroupComposer(doc, options)) {
    if (frame !== null && surface === "direct-contact") return done(memory, "UNPROVEN");
    memory.surface = "group";
    memory.tail = null;
    return done(memory, "GROUP");
  }
  if (!frame) {
    if (memory.surface === "direct-contact" && memory.tail) {
      const step = advance(doc, memory, options);
      if (step === "HINT") return done(memory, "HINT");
    }
    return close(memory, memory.header !== "" || memory.tail !== null);
  }
  if (frame.token !== memory.header) {
    memory.header = frame.token;
    memory.surface = "";
    memory.tail = null;
  }
  if (surface === "group") {
    memory.surface = "group";
    memory.tail = null;
    return done(memory, "GROUP");
  }
  if (surface === "direct-contact") memory.surface = "direct-contact";
  if (memory.surface !== "direct-contact") return done(memory, "UNPROVEN");
  const step = advance(doc, memory, options);
  if (step === "GONE") return close(memory, true);
  return done(memory, step);
}

function advance(doc: Document, memory: PaneMemory, options: ProbeOptions): PaneDisposition | "GONE" {
  const messages = messageRoot(doc, options);
  if (!messages) return "GONE";
  const tails = containers(messages, options);
  const tail = tails.length > 0 ? tails[tails.length - 1] : null;
  if (memory.tail === null) {
    memory.tail = tail;
    return "BASELINE";
  }
  if (tail === memory.tail) return "SAME";
  if (!memory.tail.isConnected || !tails.includes(memory.tail)) {
    memory.tail = tail;
    return "STALE";
  }
  memory.tail = tail;
  memory.generation += 1;
  return "HINT";
}

function close(memory: PaneMemory, had: boolean): { disposition: PaneDisposition; generation: number } {
  const generation = memory.generation;
  memory.header = "";
  memory.surface = "";
  memory.tail = null;
  return { disposition: had ? "CLEAN" : "QUIET", generation };
}

function done(memory: PaneMemory, disposition: PaneDisposition): { disposition: PaneDisposition; generation: number } {
  return { disposition, generation: memory.generation };
}

function messageRoot(doc: Document, options: ProbeOptions): Element | null {
  const found = [...doc.querySelectorAll(`[data-testid="${MESSAGES}"]`)].filter((node) => {
    return visible(node, options) && node.closest("[role='grid']") === null;
  });
  return found.length === 1 ? found[0] : null;
}

function containers(root: Element, options: ProbeOptions): Element[] {
  return [...root.querySelectorAll(`[data-testid="${CONTAINER}"]`)].filter((node) => {
    return visible(node, options) && node.closest(`[data-testid="${MESSAGES}"]`) === root;
  });
}
