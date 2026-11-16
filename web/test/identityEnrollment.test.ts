import { createHash } from "node:crypto";
import { Window } from "happy-dom";
import { describe, expect, it } from "vitest";
import { Engine } from "../src/engine.js";
import { allowFixture } from "./scopeFixture.js";
import { decideIdentity, normalizeIdentity } from "../src/identityEnrollment.js";
import { rowStatus } from "../src/sendSurface.js";

const contact = createHash("sha256").update("fixture-e164-not-a-phone").digest("hex");
const profile = createHash("sha256").update("fixture-profile-not-a-phone").digest("hex");

function engine(): Engine {
  let n = 0;
  const created = new Engine({ now: () => 10, ids: () => `id-${n += 1}`, secretHex: "ab".repeat(32) });
  created.acceptOnboarding(true);
  created.bindMetadata("contact-a");
  created.setScope(allowFixture());
  return created;
}

describe("identity enrollment", () => {
  it("rejects a display name, a scope id, and unlabeled drawer text", () => {
    const bound = engine();
    const scopeId = bound.view().binding?.localScopeId ?? "";
    for (const contactDigest of ["contact-a", scopeId, "name", "not-a-phone", "+"]) {
      expect(bound.enrollIdentity({
        contactDigest,
        profileDigest: "",
        openedHeader: "contact-a",
        openedByNumber: true
      })).toBe("DIGEST_UNUSABLE");
    }
    expect(bound.view().verifiedRemoteRecipient).toBe(false);
    expect(bound.view().identityStatus).toBe("unenrolled");
    expect(bound.view().deliveryEnabled).toBe(false);
    expect(JSON.stringify(bound.dump())).not.toContain("not-a-phone");
  });

  it("enrolls only a digest whose number resolution opened the contact-a header", async () => {
    const bound = engine();
    expect(bound.enrollIdentity({
      contactDigest: contact,
      profileDigest: profile,
      openedHeader: "contact-a",
      openedByNumber: false
    })).toBe("SESSION_UNPROVEN");
    expect(bound.enrollIdentity({
      contactDigest: contact,
      profileDigest: profile,
      openedHeader: "Other",
      openedByNumber: true
    })).toBe("WRONG_CHAT");
    expect(bound.view().verifiedRemoteRecipient).toBe(false);
    expect(bound.enrollIdentity({
      contactDigest: contact,
      profileDigest: profile,
      openedHeader: "contact-a",
      openedByNumber: true
    })).toBe("IDENTITY_ENROLLED");
    expect(bound.view().verifiedRemoteRecipient).toBe(true);
    expect(bound.view().identityStatus).toBe("enrolled");
    expect(bound.view().deliveryEnabled).toBe(false);
    expect(JSON.stringify(bound.view())).not.toContain(contact);
    const decision = bound.assessAutomaticReply({ disposition: "READ", header: "contact-a" });
    expect(decision.blocked).not.toContain("IDENTITY_UNPROVEN");
    expect(decision.blocked).toContain("DIRECTION_UNPROVEN");
    expect(decision.delivered).toBe(false);
    const delivery = await bound.attemptLiveDelivery("hello", {
      composer: "empty",
      identity: "phone-label-absent",
      direction: "unproven",
      outgoingCompared: false,
      exclusion: { excluded: 1, quoteStructure: 0, unproven: 0 }
    });
    expect(delivery.blocked).not.toContain("IDENTITY_UNPROVEN");
    expect(delivery.blocked).toContain("OUTGOING_EXCLUDED");
    expect(delivery.blocked).toContain("DIRECTION_UNPROVEN");
    expect(delivery.persisted).toBe(false);
    expect(delivery.acted).toBe(false);
    expect(bound.view().deliveryEnabled).toBe(false);
  });

  it("records a same-account number as self-chat and keeps outgoing exclusion", async () => {
    const bound = engine();
    expect(bound.enrollIdentity({
      contactDigest: contact,
      profileDigest: contact,
      openedHeader: "contact-a",
      openedByNumber: true
    })).toBe("SELF_CHAT");
    expect(bound.view().identityStatus).toBe("self-chat");
    expect(bound.view().verifiedRemoteRecipient).toBe(false);
    expect(bound.view().deliveryEnabled).toBe(false);
    const delivery = await bound.attemptLiveDelivery("hello", {
      composer: "empty",
      identity: "drawer-closed",
      direction: "unproven",
      outgoingCompared: false,
      exclusion: { excluded: 1, quoteStructure: 0, unproven: 0 }
    });
    expect(delivery.blocked).toContain("SELF_CHAT");
    expect(delivery.blocked).toContain("OUTGOING_EXCLUDED");
    expect(delivery.blocked).toContain("IDENTITY_UNPROVEN");
    expect(delivery.persisted).toBe(false);
    const row = documentRow();
    expect(rowStatus(row)).toBe("outgoing-excluded");
  });

  it("clears enrollment on stop and on a new binding", () => {
    const bound = engine();
    bound.enrollIdentity({
      contactDigest: contact,
      profileDigest: profile,
      openedHeader: "contact-a",
      openedByNumber: true
    });
    bound.stop();
    expect(bound.view().identityStatus).toBe("unenrolled");
    expect(bound.view().verifiedRemoteRecipient).toBe(false);
    bound.acceptOnboarding(true);
    bound.bindMetadata("contact-a");
    bound.enrollIdentity({
      contactDigest: contact,
      profileDigest: profile,
      openedHeader: "contact-a",
      openedByNumber: true
    });
    bound.bindMetadata("contact-a");
    expect(bound.view().identityStatus).toBe("unenrolled");
    const stored = bound.dump();
    stored.identity = {
      status: "enrolled",
      contactDigest: contact,
      profileDigest: contact,
      localScopeId: stored.binding?.localScopeId ?? "",
      headerToken: "contact-a",
      openedByNumber: true,
      enrolledAtMillis: 10
    };
    const reloaded = new Engine({ state: stored, now: () => 11 });
    expect(reloaded.view().identityStatus).toBe("self-chat");
    expect(reloaded.view().verifiedRemoteRecipient).toBe(false);
    expect(reloaded.view().deliveryEnabled).toBe(false);
  });

  it("does not treat a missing binding as a session proof", () => {
    const decision = decideIdentity({
      contactDigest: contact,
      profileDigest: "",
      openedHeader: "contact-a",
      openedByNumber: true
    }, null, 10);
    expect(decision.reason).toBe("NOT_BOUND");
    expect(normalizeIdentity(decision.enrollment, null).status).toBe("unenrolled");
  });
});

function documentRow(): Element {
  const window = new Window();
  window.document.body.innerHTML = `<div data-testid="msg-container"><span role="img" aria-label="read"></span><span aria-label="已讀"></span></div>`;
  return window.document.querySelector('[data-testid="msg-container"]') as unknown as Element;
}
