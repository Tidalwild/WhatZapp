// A visible textbox sample for the host. The body is not included.
// Occupied does not name an author. Empty does not show that a routine
// cannot draft. No frame is sent for any other state.

const EVENT_ID = /^evt-[0-9a-f]{32}$/;
const STATES = new Set(["empty", "occupied", "unmeasured"]);

export type ComposerFrame = {
  v: 1;
  kind: "composer-sample";
  state: "empty" | "occupied" | "unmeasured";
  event?: string;
};

export function composerFrame(state: string, event: string): ComposerFrame | null {
  if (!STATES.has(state)) return null;
  const frame: ComposerFrame = { v: 1, kind: "composer-sample", state: state as ComposerFrame["state"] };
  if (EVENT_ID.test(event)) frame.event = event;
  return frame;
}
