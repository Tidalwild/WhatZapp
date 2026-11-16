import { assembleContext, emptyContext, normalizeContext, CONTEXT_TTL_MS, type ContextFact } from "./contextPolicy.js";
import { hmacHex } from "./crypto.js";
import { align, fingerprint } from "./dedup.js";
import { FilteringLog } from "./log.js";
import {
  canonicalDraft,
  HANDLER,
  LIMITS,
  RETENTION_DEFAULT,
  SEND_POLICY,
  type Binding,
  type ProbeSnapshot,
  type PublicView,
  type Slot,
  type StandingGrant,
  type State,
  type StoredMessage
} from "./model.js";
import { normalizeScope, contactInScope, DEFAULT_SCOPE, type ContactScope } from "./contactScope.js";
import { decideReply, emptyGrant, type ReplyDecision } from "./replyGate.js";
import { commitDelivery, recordStore, unwiredActuator, type DeliveryResult } from "./replyDelivery.js";
import {
  APPROVAL_TTL_MS,
  decideAuthority,
  digestText,
  emptyApproval,
  normalizeApproval
} from "./sendAuthority.js";
import { decideIdentity, emptyIdentity, normalizeIdentity, remoteIdentityReady, type IdentityClaim } from "./identityEnrollment.js";
import { acceptSurface, closedSurface, visibleSetIsOutgoing, type SendSurface } from "./sendSurface.js";

export type ObserveResult = {
  disposition: string;
  captured: number;
  duplicates: number;
};

export type AttemptResult = {
  kind: "DENIED" | "NOT_SENT_SENDING_DISABLED";
  reason: string;
};

type MessageRow = { sender: string; text: string; timeText: string; fp: string; direction: "in" | "out" };

type EngineOptions = {
  now?: () => number;
  ids?: () => string;
  secretHex?: string;
  limits?: { messages: number; fingerprints: number };
  log?: FilteringLog;
  state?: State;
};

export class Engine {
  readonly log: FilteringLog;
  private readonly now: () => number;
  private readonly ids: () => string;
  private readonly limits: { messages: number; fingerprints: number };
  private state: State;

  constructor(options: EngineOptions = {}) {
    this.log = options.log ?? new FilteringLog();
    this.now = options.now ?? (() => Date.now());
    this.ids = options.ids ?? (() => crypto.randomUUID());
    this.limits = options.limits ?? { messages: LIMITS.messages, fingerprints: LIMITS.fingerprints };
    this.state = normalizeReplyGrant(options.state ? cloneState(options.state) : freshState(this.ids, options.secretHex));
  }

  dump(): State {
    return cloneState(this.state);
  }

  view(): PublicView {
    const state = this.state;
    return {
      settings: { ...state.settings },
      binding: state.binding ? { ...state.binding, verifiedRemoteRecipient: false } : null,
      replyGrant: { ...state.replyGrant },
      scope: state.scope,
      identityStatus: state.identity.status,
      deliveryEnabled: false,
      contextEnabled: state.context.enabled === true && state.context.revoked !== true,
      approvalPhase: state.approval.phase,
      baselineEstablished: state.baselineEstablished,
      messages: state.messages.map((message) => ({
        eventId: message.eventId,
        scopeId: message.scopeId,
        sender: message.purged ? "" : message.sender,
        text: message.purged ? "" : message.text,
        timeText: message.purged ? "" : message.timeText,
        capturedAtMillis: message.capturedAtMillis,
        purged: message.purged
      })),
      gaps: state.gaps.map((gap) => ({ ...gap })),
      drafts: state.drafts.map((draft) => ({
        handler: draft.handler,
        commandId: draft.commandId,
        inReplyToEventId: draft.inReplyToEventId,
        scopeId: draft.scopeId,
        body: draft.body,
        expiresAtMillis: draft.expiresAtMillis
      })),
      historyComplete: false,
      verifiedRemoteRecipient: remoteIdentityReady(state.identity, state.binding, state.scope),
      lastDisposition: state.lastDisposition,
      counters: { ...state.counters }
    };
  }

  acceptOnboarding(accepted: boolean): void {
    this.state.settings.onboardingAccepted = accepted;
    if (!accepted) this.stop();
    this.log.event("settings", { disposition: accepted ? "onboarding-on" : "onboarding-off" });
  }

  bind(header: string, selfLabel: string): { ok: true; binding: Binding } | { ok: false; reason: string } {
    if (!this.state.settings.onboardingAccepted) return { ok: false, reason: "ONBOARDING_REQUIRED" };
    const visibleHeader = header.trim();
    const self = selfLabel.trim();
    if (visibleHeader === "" || visibleHeader.length > 80) return { ok: false, reason: "HEADER_UNUSABLE" };
    if (self === "" || self.length > 80) return { ok: false, reason: "SELF_LABEL_UNUSABLE" };
    if (self === visibleHeader) return { ok: false, reason: "DIRECTION_UNUSABLE" };
    return { ok: true, binding: this.installBinding(visibleHeader, self, "messages") };
  }

  bindMetadata(header: string): { ok: true; binding: Binding } | { ok: false; reason: string } {
    if (!this.state.settings.onboardingAccepted) return { ok: false, reason: "ONBOARDING_REQUIRED" };
    const visibleHeader = header.trim();
    if (!/^[A-Za-z0-9._-]{1,40}$/.test(visibleHeader)) return { ok: false, reason: "HEADER_UNUSABLE" };
    return { ok: true, binding: this.installBinding(visibleHeader, "", "metadata") };
  }

  setCollection(enabled: boolean): string {
    if (enabled && !this.state.settings.onboardingAccepted) return "ONBOARDING_REQUIRED";
    if (enabled && !this.state.binding) return "NOT_BOUND";
    this.state.settings.collectionEnabled = enabled;
    if (!enabled) this.state.settings.exportEnabled = false;
    if (enabled) this.dropStaleLayoutGap();
    this.log.event("settings", { disposition: enabled ? "collection-on" : "collection-off" });
    return enabled ? "collection-on" : "collection-off";
  }

  setExport(enabled: boolean): string {
    if (enabled && !this.state.settings.collectionEnabled) return "COLLECTION_OFF";
    if (enabled && this.state.binding?.mode === "metadata") return "DIRECTION_UNPROVEN";
    this.state.settings.exportEnabled = enabled;
    this.log.event("settings", { disposition: enabled ? "export-on" : "export-off" });
    return enabled ? "export-on" : "export-off";
  }

  stop(): void {
    this.state.settings.collectionEnabled = false;
    this.state.settings.exportEnabled = false;
    this.state.replyGrant = emptyGrant();
    this.state.identity = emptyIdentity();
    this.log.event("settings", { disposition: "stopped" });
  }

  setScope(scope: Partial<ContactScope>): ContactScope {
    this.state.scope = normalizeScope(scope);
    const grant = this.state.replyGrant;
    if (grant.enabled && !contactInScope(this.state.scope, { label: grant.token, kind: "direct" })) {
      this.state.replyGrant = emptyGrant();
    }
    this.log.event("settings", { disposition: `scope-${this.state.scope.mode}` });
    return this.state.scope;
  }

  setReplyGrant(enabled: boolean): string {
    if (!enabled) {
      this.state.replyGrant = emptyGrant();
      this.log.event("settings", { disposition: "reply-grant-off" });
      return "grant-off";
    }
    const binding = this.state.binding;
    if (!binding || binding.localScopeId === "") return "NOT_BOUND";
    if (!contactInScope(this.state.scope, { label: binding.visibleHeader, kind: "direct" })) {
      return this.state.scope.mode === "off" ? "SCOPE_OFF" : "SCOPE_EXCLUDED";
    }
    this.state.replyGrant = {
      enabled: true,
      token: binding.visibleHeader,
      localScopeId: binding.localScopeId,
      grantedAtMillis: this.now(),
      expiresAtMillis: this.now() + 4 * 60 * 60 * 1000
    };
    this.log.event("settings", { disposition: "reply-grant-on" });
    return "grant-on";
  }

  enrollIdentity(claim: IdentityClaim): string {
    const decision = decideIdentity(claim, this.state.binding, this.now(), this.state.scope);
    if (decision.reason === "IDENTITY_ENROLLED" || decision.reason === "SELF_CHAT") {
      this.state.identity = decision.enrollment;
    }
    this.log.event("settings", { disposition: decision.reason });
    return decision.reason;
  }

  assessAutomaticReply(read: { disposition?: string; header?: string; exclusion?: { excluded: number; quoteStructure?: number; unproven: number } } | null): ReplyDecision {
    this.expireGrant();
    const binding = this.state.binding;
    const disposition = read?.disposition ?? "";
    const header = (read?.header ?? "").trim();
    const agreed =
      (disposition === "READ" || disposition === "VISIBLE") &&
      header !== "" &&
      header === binding?.visibleHeader;
    const quote = (read?.exclusion?.quoteStructure ?? 0) > 0;
    const outgoing =
      read?.exclusion !== undefined &&
      visibleSetIsOutgoing({
        excluded: read.exclusion.excluded,
        quoteStructure: read.exclusion.quoteStructure ?? 0,
        unproven: read.exclusion.unproven
      });
    return decideReply({
      grant: this.state.replyGrant,
      bind: {
        token: binding?.visibleHeader ?? "",
        localScopeId: binding?.localScopeId ?? "",
        headerAgrees: agreed,
        composerAgrees: agreed,
        paneCount: disposition === "PANE_UNPROVEN" ? 2 : agreed ? 1 : 0,
        verifiedRemoteRecipient: remoteIdentityReady(this.state.identity, binding, this.state.scope),
        mode: binding?.mode ?? ""
      },
      inbound: {
        source: "reader-0.2.14",
        stableId: "",
        direction: "unknown",
        directionProof: quote ? "quote-structure" : outgoing ? "outgoing-status" : "unproven",
        senderIsSelf: false,
        echoesHeldReply: false
      },
      untrustedText: "",
      action: "reply",
      replyText: "",
      ledger: { consumed: [] },
      allowFixtureProof: false,
      scope: this.state.scope,
      kind: "direct"
    });
  }

  setContextOptIn(enabled: boolean): string {
    const binding = this.state.binding;
    if (!binding || binding.localScopeId === "") return "NOT_BOUND";
    if (!enabled) {
      const scopeId = this.state.context.scopeId || binding.localScopeId;
      this.state.context = { ...emptyContext(), revoked: true, scopeId };
      this.log.event("settings", { disposition: "context-off" });
      return "CONTEXT_REVOKED";
    }
    this.state.context = {
      enabled: true,
      scopeId: binding.localScopeId,
      source: "operator",
      enabledAtMillis: this.now(),
      expiresAtMillis: this.now() + CONTEXT_TTL_MS,
      revoked: false
    };
    this.log.event("settings", { disposition: "context-on" });
    return "CONTEXT_ON";
  }

  previewContext(facts: readonly ContextFact[]) {
    const chat = this.state.binding?.localScopeId ?? "";
    return assembleContext(this.state.context, facts, this.now(), chat);
  }

  async approveExact(text: string, event: string): Promise<string> {
    if (SEND_POLICY.invocationArmed || SEND_POLICY.backgroundAutoSend) return "POLICY";
    const binding = this.state.binding;
    if (!binding || binding.localScopeId === "") return "NOT_BOUND";
    if (text.length > 1000) return "TOO_LONG";
    if (text.trim() === "") return "EMPTY";
    if (!/^evt-[0-9a-f]{32}$/.test(event)) return "EVENT_UNUSABLE";
    if (this.state.approval.phase === "ambiguous") return "AMBIGUOUS_HOLD";
    const digest = await digestText(text);
    this.state.approval = {
      phase: "approved",
      digest,
      scopeId: binding.localScopeId,
      event,
      approvedAtMillis: this.now(),
      expiresAtMillis: this.now() + APPROVAL_TTL_MS,
      paused: false
    };
    this.log.event("approval", { disposition: "APPROVED_NOT_SENT" });
    return "APPROVED_NOT_SENT";
  }

  pauseApproval(): string {
    if (this.state.approval.phase === "none") return "NONE";
    this.state.approval = { ...this.state.approval, paused: true };
    this.log.event("approval", { disposition: "PAUSED" });
    return "PAUSED";
  }

  revokeApproval(): string {
    this.state.approval = emptyApproval();
    this.log.event("approval", { disposition: "REVOKED" });
    return "REVOKED";
  }

  holdAmbiguous(): string {
    if (this.state.approval.phase === "none") return "NONE";
    this.state.approval = { ...this.state.approval, phase: "ambiguous", paused: true };
    this.log.event("approval", { disposition: "AMBIGUOUS_HOLD" });
    return "AMBIGUOUS_HOLD";
  }

  async attemptLiveDelivery(replyText: string, surface?: SendSurface): Promise<DeliveryResult> {
    this.expireGrant();
    const authorityReason = await this.authorityFor(replyText);
    const binding = this.state.binding;
    const grant = this.state.replyGrant;
    const observed = acceptSurface(surface ?? closedSurface());
    const frameAgreed = observed.composer !== "unmeasured";
    const enrolled = remoteIdentityReady(this.state.identity, binding, this.state.scope);
    const selfChat = this.state.identity.status === "self-chat";
    const identityFinding = enrolled
      ? undefined
      : selfChat
        ? "self-chat"
        : observed.identity === "phone-label-absent"
          ? "phone-label-absent"
          : observed.identity === "phone-label-present"
            ? "phone-uncompared"
            : "drawer-closed";
    const result = commitDelivery({
      action: "reply",
      replyText,
      attemptId: "live-unmeasured",
      proof: {
        origin: "live",
        evidenceId: "",
        contactDetailsOpen: observed.identity !== "drawer-closed",
        identityCompared: enrolled,
        identityMatchesEnrolled: enrolled,
        incoming: false,
        outgoingCompared: false,
        outgoingStatus: visibleSetIsOutgoing(observed.exclusion),
        identityFinding,
        senderLabel: "",
        stableId: "",
        localScopeId: ""
      },
      send: {
        grantEnabled: grant.enabled,
        grantToken: grant.token,
        grantScopeId: grant.localScopeId,
        chatToken: binding?.visibleHeader ?? "",
        chatScopeId: binding?.localScopeId ?? "",
        headerAgrees: frameAgreed,
        composerAgrees: frameAgreed,
        paneCount: frameAgreed ? 1 : 0,
        composer: observed.composer
      },
      store: recordStore(this.state.deliveryRecords),
      actuator: unwiredActuator(),
      allowFixture: false,
      untrustedText: replyText,
      scope: this.state.scope,
      authorityReason
    });
    this.log.event("delivery", { disposition: result.reason });
    return result;
  }

  purgeBodies(): number {
    let count = 0;
    for (const message of this.state.messages) {
      if (message.purged) continue;
      clearBody(message);
      count += 1;
    }
    if (count > 0) this.gap("RETENTION", "bodies cleared");
    this.log.event("purge", { disposition: "RETENTION", count: String(count) });
    return count;
  }

  restart(): void {
    for (const item of this.state.outbox) {
      if (item.state === "IN_FLIGHT") item.state = "RETRYABLE";
    }
    this.state.historyComplete = false;
    this.dropStaleLayoutGap();
    this.log.event("process", { disposition: "restart", outbox: "retryable" });
  }

  async observe(snapshot: ProbeSnapshot): Promise<ObserveResult> {
    this.purgeExpired();
    if (!this.state.settings.onboardingAccepted) return this.finish("ONBOARDING_REQUIRED", 0, 0);
    if (!this.state.settings.collectionEnabled) return this.finish("COLLECTION_OFF", 0, 0);
    if (this.state.binding?.mode === "metadata") return this.finish("METADATA_ONLY", 0, 0);
    if (snapshot.layout !== "probe-contract") {
      this.gap("UNRECOGNIZED_LAYOUT", "visible region did not match the probe");
      return this.finish("UNRECOGNIZED_LAYOUT", 0, 0);
    }
    const binding = this.state.binding;
    if (!binding) return this.finish("NOT_BOUND", 0, 0);
    if (snapshot.header.trim() !== binding.visibleHeader) {
      this.gap("CHAT_SWITCH", "open chat label does not match the bound label");
      return this.finish("CHAT_SWITCH", 0, 0);
    }
    if (snapshot.phase === "loading" || snapshot.phase === "empty") {
      const reason = this.state.baselineEstablished ? "RELOAD_EMPTY" : "LOAD_EMPTY";
      this.gap(reason, snapshot.phase === "loading" ? "loading" : "empty");
      return this.finish(reason, 0, 0);
    }
    const parsed = await parseSlots(snapshot.slots);
    if (!parsed.ok) {
      if (parsed.reason === "AMBIGUOUS_REPEAT") this.state.counters.ambiguous += 1;
      this.gap(parsed.reason, "snapshot rejected");
      return this.finish(parsed.reason, 0, 0);
    }
    const directed = direct(parsed.rows, binding);
    if (!directed.ok) {
      this.state.counters.ambiguous += 1;
      this.gap(directed.reason, "snapshot rejected");
      return this.finish(directed.reason, 0, 0);
    }
    const fps = directed.rows.map((row) => row.fp);
    if (!this.state.baselineEstablished) {
      this.state.baselineEstablished = true;
      this.remember(fps);
      this.gap("BASELINE", "first visible snapshot is not new traffic");
      if (parsed.skipped > 0) this.gap("SKIPPED_ROWS", "separator or header row ignored");
      return this.finish("BASELINE", 0, 0);
    }
    const aligned = align(this.state.fingerprints, fps);
    if (aligned.continuityGap) {
      this.gap("NO_OVERLAP", "visible rows did not continue the previous window");
      return this.finish("NO_OVERLAP", 0, aligned.duplicateCount);
    }
    if (aligned.fresh.length === 0) {
      this.state.counters.duplicates += aligned.duplicateCount;
      if (parsed.skipped > 0) this.gap("SKIPPED_ROWS", "separator or header row ignored");
      return this.finish("DUPLICATE", 0, aligned.duplicateCount);
    }
    this.remember([...this.state.fingerprints, ...aligned.fresh]);
    const freshRows = directed.rows.slice(directed.rows.length - aligned.fresh.length);
    const inbound = freshRows.filter((row) => row.direction === "in");
    if (parsed.skipped > 0) this.gap("SKIPPED_ROWS", "separator or header row ignored");
    this.state.counters.duplicates += aligned.duplicateCount;
    if (inbound.length === 0) return this.finish("CONTEXT_ONLY", 0, aligned.duplicateCount);
    const label = binding.visibleHeader;
    if (!contactInScope(this.state.scope, { label, kind: "direct" })) {
      const reason = this.state.scope.mode === "off" ? "SCOPE_OFF" : "SCOPE_EXCLUDED";
      this.gap(reason, "scope is required before a body is stored");
      return this.finish(reason, 0, aligned.duplicateCount);
    }
    if (!remoteIdentityReady(this.state.identity, binding, this.state.scope)) {
      this.gap("IDENTITY_UNPROVEN", "identity is required before a body is stored");
      return this.finish("IDENTITY_UNPROVEN", 0, aligned.duplicateCount);
    }
    // A sender label, a clock, an unread mark, and quoted text are not incoming.
    this.gap("DIRECTION_UNPROVEN", "a sender label is not incoming");
    return this.finish("DIRECTION_UNPROVEN", 0, aligned.duplicateCount);
  }

  async confirmDraft(commandId: string, exactBody: string): Promise<AttemptResult> {
    if (SEND_POLICY.invocationArmed || SEND_POLICY.backgroundAutoSend) {
      return { kind: "DENIED", reason: "policy" };
    }
    const draft = this.state.drafts.find((item) => item.commandId === commandId);
    if (!draft) return { kind: "DENIED", reason: "missing-draft" };
    if (this.state.consumedCommandIds.includes(draft.commandId)) {
      return { kind: "DENIED", reason: "REPLAY" };
    }
    if (draft.handler !== HANDLER) return { kind: "DENIED", reason: "WRONG_HANDLER" };
    const expected = await hmacHex(this.state.keyMaterial, canonicalDraft(draft));
    if (expected !== draft.signature) return { kind: "DENIED", reason: "BAD_SIGNATURE" };
    if (draft.deviceId !== this.state.settings.deviceId || draft.keyId !== this.state.settings.keyId) {
      return { kind: "DENIED", reason: "WRONG_DEVICE" };
    }
    if (draft.expiresAtMillis < this.now()) return { kind: "DENIED", reason: "EXPIRED" };
    if (draft.correlationId !== draft.inReplyToEventId) return { kind: "DENIED", reason: "EVENT_MISMATCH" };
    const message = this.state.messages.find((item) => item.eventId === draft.inReplyToEventId);
    if (!message) return { kind: "DENIED", reason: "EVENT_MISMATCH" };
    if (message.purged) return { kind: "DENIED", reason: "EVENT_UNAVAILABLE" };
    if (exactBody !== draft.body) return { kind: "DENIED", reason: "CONFIRMATION_MISMATCH" };
    if (!this.state.binding || draft.scopeId !== this.state.binding.localScopeId || message.scopeId !== draft.scopeId) {
      return { kind: "DENIED", reason: "WRONG_RECIPIENT" };
    }
    this.state.consumedCommandIds.push(draft.commandId);
    if (this.state.consumedCommandIds.length > LIMITS.consumed) {
      this.state.consumedCommandIds.splice(0, this.state.consumedCommandIds.length - LIMITS.consumed);
    }
    this.log.event("draft", { disposition: "not-sent", kind: "NOT_SENT_SENDING_DISABLED", handler: HANDLER });
    return { kind: "NOT_SENT_SENDING_DISABLED", reason: "sending-disabled" };
  }

  private async authorityFor(replyText: string): Promise<string> {
    const binding = this.state.binding;
    const digest = await digestText(replyText);
    return decideAuthority(
      this.state.approval,
      this.now(),
      digest,
      binding?.localScopeId ?? "",
      this.state.approval.event
    );
  }

  private expireGrant(): void {
    const grant = this.state.replyGrant;
    if (grant.enabled && grant.expiresAtMillis <= this.now()) this.state.replyGrant = emptyGrant();
  }

  private dropStaleLayoutGap(): void {
    if (this.state.binding?.mode !== "metadata") return;
    this.state.gaps = this.state.gaps.filter((gap) => gap.reason !== "UNRECOGNIZED_LAYOUT");
    if (this.state.lastDisposition === "UNRECOGNIZED_LAYOUT") this.state.lastDisposition = "";
  }

  private installBinding(visibleHeader: string, selfLabel: string, mode: Binding["mode"]): Binding {
    const binding: Binding = {
      localScopeId: this.ids(),
      visibleHeader,
      selfLabel,
      mode,
      boundAtMillis: this.now(),
      confidence: "local-pilot-display-label",
      verifiedRemoteRecipient: false
    };
    this.state.binding = binding;
    this.state.baselineEstablished = false;
    this.state.fingerprints = [];
    this.state.settings.collectionEnabled = false;
    this.state.settings.exportEnabled = false;
    this.state.replyGrant = emptyGrant();
    this.state.identity = emptyIdentity();
    if (mode === "metadata") this.dropStaleLayoutGap();
    this.log.event("bind", { disposition: mode === "metadata" ? "metadata-scope" : "local-scope" });
    return binding;
  }

  private remember(fps: string[]): void {
    if (fps.length <= this.limits.fingerprints) {
      this.state.fingerprints = fps;
      return;
    }
    this.state.fingerprints = fps.slice(-this.limits.fingerprints);
    this.gap("FINGERPRINT_WINDOW", "oldest fingerprints dropped");
  }

  private purgeExpired(): void {
    const cutoff = this.now() - this.state.settings.retentionMillis;
    let count = 0;
    for (const message of this.state.messages) {
      if (!message.purged && message.capturedAtMillis < cutoff) {
        clearBody(message);
        count += 1;
      }
    }
    if (count > 0) {
      this.gap("RETENTION", "expired body cleared");
      this.log.event("purge", { disposition: "RETENTION", count: String(count) });
    }
  }

  private gap(reason: string, detail: string): void {
    this.state.gaps.push({
      id: this.ids(),
      reason,
      detail,
      incomplete: true,
      atMillis: this.now()
    });
    if (this.state.gaps.length > LIMITS.gaps) {
      this.state.gaps.splice(0, this.state.gaps.length - LIMITS.gaps);
    }
    this.state.counters.gaps += 1;
    this.state.historyComplete = false;
    this.log.event("gap", { disposition: reason, incomplete: "true" });
  }

  private finish(disposition: string, captured: number, duplicates: number): ObserveResult {
    this.state.lastDisposition = disposition;
    this.state.historyComplete = false;
    this.log.event("observe", {
      disposition,
      count: String(captured),
      duplicate: String(duplicates),
      incomplete: "true"
    });
    return { disposition, captured, duplicates };
  }
}

export function freshState(ids: () => string, secretHex?: string): State {
  return {
    settings: {
      onboardingAccepted: false,
      collectionEnabled: false,
      exportEnabled: false,
      retentionMillis: RETENTION_DEFAULT,
      deviceId: ids(),
      keyId: "local-mock-1"
    },
    binding: null,
    baselineEstablished: false,
    fingerprints: [],
    messages: [],
    gaps: [],
    outbox: [],
    drafts: [],
    consumedCommandIds: [],
    replyGrant: emptyGrant(),
    scope: DEFAULT_SCOPE,
    identity: emptyIdentity(),
    deliveryRecords: [],
    context: emptyContext(),
    approval: emptyApproval(),
    historyComplete: false,
    keyMaterial: secretHex ?? randomSecretFallback(),
    counters: { captured: 0, duplicates: 0, ambiguous: 0, gaps: 0 },
    lastDisposition: ""
  };
}

function randomSecretFallback(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function cloneState(state: State): State {
  if (state.historyComplete !== false) throw new Error("history");
  return structuredClone(state);
}

function normalizeReplyGrant(state: State): State {
  state.scope = normalizeScope(state.scope);
  const grant = state.replyGrant;
  const binding = state.binding;
  const usable =
    grant != null &&
    grant.enabled === true &&
    typeof grant.token === "string" &&
    grant.token !== "" &&
    grant.localScopeId !== "" &&
    typeof grant.expiresAtMillis === "number" &&
    grant.expiresAtMillis > 0 &&
    binding != null &&
    binding.visibleHeader === grant.token &&
    binding.localScopeId === grant.localScopeId &&
    contactInScope(state.scope, { label: grant.token, kind: "direct" });
  const next: StandingGrant = usable
    ? {
        enabled: true,
        token: grant.token,
        localScopeId: grant.localScopeId,
        grantedAtMillis: grant.grantedAtMillis,
        expiresAtMillis: grant.expiresAtMillis
      }
    : emptyGrant();
  state.replyGrant = next;
  state.identity = normalizeIdentity(state.identity, state.binding);
  state.context = normalizeContext(state.context);
  state.approval = normalizeApproval(state.approval);
  if (!Array.isArray(state.deliveryRecords)) state.deliveryRecords = [];
  state.deliveryRecords = state.deliveryRecords
    .filter(
      (row) =>
        row != null &&
        typeof row.key === "string" &&
        row.key.length > 0 &&
        row.key.length <= 200 &&
        (row.phase === "persisted" || row.phase === "uncertain" || row.phase === "receipt" || row.phase === "declined") &&
        typeof row.receiptKey === "string"
    )
    .slice(-200);
  state.historyComplete = false;
  return state;
}

async function parseSlots(slots: Slot[]): Promise<
  | { ok: true; rows: Array<{ sender: string; text: string; timeText: string; fp: string }>; skipped: number }
  | { ok: false; reason: "TIME_AMBIGUOUS" | "EMPTY_BODY" | "AMBIGUOUS_REPEAT" | "AMBIGUOUS_CLOCK" | "UNPARSEABLE" }
> {
  const rows: Array<{ sender: string; text: string; timeText: string; fp: string }> = [];
  let skipped = 0;
  const seen = new Set<string>();
  const clocks = new Set<string>();
  for (const slot of slots) {
    if (slot.kind === "separator" || slot.kind === "header-echo") {
      skipped += 1;
      continue;
    }
    if (slot.kind === "bad-time") return { ok: false, reason: "TIME_AMBIGUOUS" };
    if (slot.kind === "empty-body") return { ok: false, reason: "EMPTY_BODY" };
    const fp = await fingerprint(slot);
    if (seen.has(fp)) return { ok: false, reason: "AMBIGUOUS_REPEAT" };
    const clockKey = `${slot.sender}\n${slot.timeText}`;
    if (clocks.has(clockKey)) return { ok: false, reason: "AMBIGUOUS_CLOCK" };
    seen.add(fp);
    clocks.add(clockKey);
    rows.push({ sender: slot.sender, text: slot.text, timeText: slot.timeText, fp });
  }
  if (rows.length === 0) return { ok: false, reason: "UNPARSEABLE" };
  return { ok: true, rows, skipped };
}

function direct(
  rows: Array<{ sender: string; text: string; timeText: string; fp: string }>,
  binding: Binding
): { ok: true; rows: MessageRow[] } | { ok: false; reason: "AMBIGUOUS_DIRECTION" | "DIRECTION_UNPROVEN" } {
  if (binding.mode === "metadata" || binding.selfLabel.trim() === "") {
    return { ok: false, reason: "DIRECTION_UNPROVEN" };
  }
  // Label equality only classifies the row. It is not incoming proof.
  const directed: MessageRow[] = [];
  for (const row of rows) {
    let direction: "in" | "out";
    if (row.sender === binding.selfLabel) direction = "out";
    else if (row.sender === binding.visibleHeader) direction = "in";
    else return { ok: false, reason: "AMBIGUOUS_DIRECTION" };
    directed.push({ ...row, direction });
  }
  return { ok: true, rows: directed };
}

function clearBody(message: StoredMessage): void {
  message.purged = true;
  message.text = "";
  message.sender = "";
  message.timeText = "";
}
