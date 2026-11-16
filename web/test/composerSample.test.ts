import { describe, expect, it } from "vitest";
import { composerFrame } from "../src/composerSample.js";

describe("composer sample", () => {
  it("forwards only the textbox state and a well-formed event id", () => {
    expect(composerFrame("occupied", "evt-" + "ab".repeat(16))).toEqual({
      v: 1,
      kind: "composer-sample",
      state: "occupied",
      event: "evt-" + "ab".repeat(16)
    });
    expect(composerFrame("empty", "not-an-event")).toEqual({ v: 1, kind: "composer-sample", state: "empty" });
    expect(composerFrame("unmeasured", "")).toEqual({ v: 1, kind: "composer-sample", state: "unmeasured" });
    for (const state of ["incoming", "proven", "Quoted message", "tail-in"]) {
      expect(composerFrame(state, "evt-" + "ab".repeat(16))).toBeNull();
    }
    const frame = composerFrame("occupied", "evt-" + "cd".repeat(16));
    expect(JSON.stringify(frame)).not.toContain("Quoted");
    expect(JSON.stringify(frame)).not.toContain("unread");
    expect(JSON.stringify(frame)).not.toContain("09:02");
  });
});
