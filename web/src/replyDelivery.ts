// Delivery adapter. A grant is not a send.
// Incoming proof is an enrolled visible-UI evidence id. A sender label, an
// occurrence id, localScopeId, left alignment, tail-in, and a missing status
// icon do not enroll it. A quote of an outgoing row is structure only. It is
// not an evidence id. A phone label that is absent, or present but not
// compared, does not enroll identity.
// This module does not read the page and does not call WhatsApp.
// Persist the attempt before the actuator runs. A persisted row with no
// verified receipt is uncertain and is never retried.

import { contactInScope, type ContactScope } from "./contactScope.js";

export const FIXTURE_EVIDENCE_ID = "fixture-visible-incoming";

// No live evidence id is enrolled. A quote of an outgoing row is not one.
export const LIVE_EVIDENCE_IDS: readonly string[] = [];
export const LIVE_SEND_ARMED = false;

export type DeliveryPhase = "persisted" | "uncertain" | "receipt" | "declined";

export type DeliveryRecord = {
  key: string;
  phase: DeliveryPhase;
  receiptKey: string;
};

export type DeliveryStore = {
  get(key: string): DeliveryRecord | null;
  put(record: DeliveryRecord): void;
};

export type ActResult =
  | { acted: false }
  | { acted: true; receiptKey: string; composerEmptyAfter: boolean };

export type Actuator = {
  wired: boolean;
  act(input: { key: string; text: string }): ActResult;
};

export type ComposerObservation = "empty" | "occupied" | "unmeasured";

export type VisibleProof = {
  origin: "fixture" | "live";
  evidenceId: string;
  contactDetailsOpen: boolean;
  identityCompared: boolean;
  identityMatchesEnrolled: boolean;
  incoming: boolean;
  outgoingCompared?: boolean;
  outgoingStatus?: boolean;
  identityFinding?: "drawer-closed" | "phone-label-absent" | "phone-uncompared" | "self-chat";
  senderLabel?: string;
  stableId?: string;
  localScopeId?: string;
};

export type SendObservation = {
  grantEnabled: boolean;
  grantToken: string;
  grantScopeId: string;
  chatToken: string;
  chatScopeId: string;
  headerAgrees: boolean;
  composerAgrees: boolean;
  paneCount: number;
  composer: ComposerObservation;
};

export type DeliveryRequest = {
  action: string;
  replyText: string;
  attemptId: string;
  proof: VisibleProof;
  send: SendObservation;
  store: DeliveryStore;
  actuator: Actuator;
  allowFixture: boolean;
  untrustedText: string;
  scope: ContactScope;
};

export type DeliveryResult = {
  outcome: "refused" | "receipt" | "uncertain" | "declined";
  reason: string;
  blocked: string[];
  delivered: false;
  receiptVerified: boolean;
  live: false;
  acted: boolean;
  persisted: boolean;
  key: string;
};

export function commitDelivery(request: DeliveryRequest): DeliveryResult {
  const ignored = request.untrustedText;
  void ignored;
  const ignoredLabel = request.proof.senderLabel;
  const ignoredStable = request.proof.stableId;
  const ignoredScope = request.proof.localScopeId;
  void ignoredLabel;
  void ignoredStable;
  void ignoredScope;

  const blocked: string[] = [];
  const block = (reason: string) => {
    if (!blocked.includes(reason)) blocked.push(reason);
  };
  if (request.action !== "reply") block("ACTION_FORBIDDEN");
  const text = request.replyText.trim();
  if (request.action === "reply" && text === "") block("EMPTY_REPLY");
  if (request.replyText.length > 1000) block("REPLY_TOO_LONG");
  if (!proofEnrolled(request.proof, request.allowFixture)) block("EVIDENCE_NOT_MEASURED");
  if (!request.proof.identityCompared || !request.proof.identityMatchesEnrolled) {
    block("IDENTITY_UNPROVEN");
  }
  if (request.proof.identityFinding === "phone-label-absent") block("PHONE_LABEL_ABSENT");
  if (request.proof.identityFinding === "phone-uncompared") block("PHONE_UNCOMPARED");
  if (request.proof.identityFinding === "drawer-closed") block("DRAWER_CLOSED");
  if (request.proof.identityFinding === "self-chat") block("SELF_CHAT");
  if (!request.proof.incoming) block("DIRECTION_UNPROVEN");
  if (request.proof.outgoingStatus) block("OUTGOING_EXCLUDED");
  if (request.proof.outgoingCompared === false) block("OUTGOING_UNCOMPARED");
  if (request.proof.origin === "live" && !LIVE_SEND_ARMED) block("LIVE_SEND_CLOSED");

  const send = request.send;
  if (!send.grantEnabled) block("GRANT_OFF");
  else if (send.grantScopeId === "" || send.chatScopeId === "" || send.grantScopeId !== send.chatScopeId) block("BINDING_MISMATCH");
  if (send.grantToken === "" || send.chatToken === "" || send.grantToken !== send.chatToken) block("WRONG_CHAT");
  if (!contactInScope(request.scope, { label: send.chatToken, kind: "direct" })) {
    block(request.scope.mode === "off" ? "SCOPE_OFF" : "SCOPE_EXCLUDED");
  }
  if (request.scope.maxReplies <= 0) block("CAP_REACHED");
  if (!send.headerAgrees || !send.composerAgrees || send.paneCount !== 1) block("WRONG_CHAT");
  if (send.composer === "occupied") block("COMPOSER_NOT_EMPTY");
  if (send.composer === "unmeasured") block("COMPOSER_UNMEASURED");
  if (!request.actuator.wired) block("ACTUATOR_NOT_WIRED");
  if (!/^[A-Za-z0-9._:-]{1,80}$/.test(request.attemptId)) block("ATTEMPT_ID_UNUSABLE");

  const key = blocked.length === 0 ? `${send.grantScopeId}/${request.attemptId}` : "";
  if (blocked.length > 0) return refused(blocked);

  const existing = request.store.get(key);
  if (existing?.phase === "receipt") {
    return held("receipt", "RECEIPT_ALREADY", true, false, key);
  }
  if (existing?.phase === "uncertain") {
    return held("uncertain", "UNCERTAIN", false, false, key);
  }
  if (existing?.phase === "persisted") {
    request.store.put({ key, phase: "uncertain", receiptKey: "" });
    return held("uncertain", "UNCERTAIN", false, false, key);
  }

  try {
    request.store.put({ key, phase: "persisted", receiptKey: "" });
  } catch {
    return { outcome: "refused", reason: "PERSIST_FAILED", blocked: ["PERSIST_FAILED"], delivered: false, receiptVerified: false, live: false, acted: false, persisted: false, key: "" };
  }

  let result: ActResult;
  try {
    result = request.actuator.act({ key, text });
  } catch {
    request.store.put({ key, phase: "uncertain", receiptKey: "" });
    return held("uncertain", "UNCERTAIN", false, true, key);
  }
  if (!result.acted) {
    request.store.put({ key, phase: "declined", receiptKey: "" });
    return held("declined", "ACT_DECLINED", false, true, key);
  }
  if (result.receiptKey !== key || result.composerEmptyAfter !== true) {
    request.store.put({ key, phase: "uncertain", receiptKey: "" });
    return held("uncertain", "RECEIPT_UNVERIFIED", false, true, key);
  }
  request.store.put({ key, phase: "receipt", receiptKey: result.receiptKey });
  return held("receipt", "RECEIPT_VERIFIED", true, true, key);
}

function proofEnrolled(proof: VisibleProof, allowFixture: boolean): boolean {
  if (proof.origin === "fixture") {
    return allowFixture && proof.evidenceId === FIXTURE_EVIDENCE_ID && proof.incoming;
  }
  return proof.origin === "live" && proof.incoming && LIVE_EVIDENCE_IDS.includes(proof.evidenceId);
}

function refused(blocked: string[]): DeliveryResult {
  return {
    outcome: "refused",
    reason: blocked[0] ?? "REFUSED",
    blocked,
    delivered: false,
    receiptVerified: false,
    live: false,
    acted: false,
    persisted: false,
    key: ""
  };
}

function held(
  outcome: DeliveryResult["outcome"],
  reason: string,
  receiptVerified: boolean,
  acted: boolean,
  key: string
): DeliveryResult {
  return { outcome, reason, blocked: [], delivered: false, receiptVerified, live: false, acted, persisted: true, key };
}

export function unwiredActuator(): Actuator {
  return {
    wired: false,
    act() {
      return { acted: false };
    }
  };
}

export function recordStore(records: DeliveryRecord[]): DeliveryStore {
  return {
    get(key) {
      return records.find((row) => row.key === key) ?? null;
    },
    put(record) {
      const index = records.findIndex((row) => row.key === record.key);
      if (index >= 0) records[index] = record;
      else records.push(record);
      if (records.length > 200) records.splice(0, records.length - 200);
    }
  };
}
