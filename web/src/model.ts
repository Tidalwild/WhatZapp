import type { ContactScope } from "./contactScope.js";
import { DEFAULT_SCOPE } from "./contactScope.js";
import type { DeliveryRecord } from "./replyDelivery.js";
import type { IdentityEnrollment } from "./identityEnrollment.js";

export const HANDLER = "local-mock-handler";
export const HISTORY_COMPLETE = false;
export const RETENTION_DEFAULT = 24 * 60 * 60 * 1000;
export const DRAFT_TTL = 15 * 60 * 1000;
export const SEND_POLICY = {
  invocationArmed: false,
  backgroundAutoSend: false
} as const;

export const LIMITS = {
  messages: 30,
  fingerprints: 40,
  gaps: 30,
  drafts: 20,
  consumed: 200
};

const CLOCK = /^(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?[AP]M)?$/i;

export type Slot =
  | { kind: "separator" }
  | { kind: "header-echo" }
  | { kind: "bad-time" }
  | { kind: "empty-body" }
  | { kind: "message"; sender: string; text: string; timeText: string };

export type ProbeSnapshot = {
  layout: "probe-contract" | "unrecognized";
  header: string;
  phase: "ready" | "loading" | "empty";
  slots: Slot[];
};

export type Settings = {
  onboardingAccepted: boolean;
  collectionEnabled: boolean;
  exportEnabled: boolean;
  retentionMillis: number;
  deviceId: string;
  keyId: string;
};

export type Binding = {
  localScopeId: string;
  visibleHeader: string;
  selfLabel: string;
  mode: "messages" | "metadata";
  boundAtMillis: number;
  confidence: "local-pilot-display-label";
  verifiedRemoteRecipient: false;
};

export type Gap = {
  id: string;
  reason: string;
  detail: string;
  incomplete: true;
  atMillis: number;
};

export type StoredMessage = {
  eventId: string;
  scopeId: string;
  sender: string;
  text: string;
  timeText: string;
  contentHash: string;
  capturedAtMillis: number;
  purged: boolean;
};

export type OutboxState = "PENDING" | "IN_FLIGHT" | "RETRYABLE" | "ACKED" | "REJECTED";

export type OutboxItem = {
  eventId: string;
  idempotencyKey: string;
  state: OutboxState;
  attempts: number;
};

export type Draft = {
  handler: string;
  commandId: string;
  inReplyToEventId: string;
  scopeId: string;
  body: string;
  expiresAtMillis: number;
  correlationId: string;
  deviceId: string;
  keyId: string;
  signature: string;
};

export type Counters = {
  captured: number;
  duplicates: number;
  ambiguous: number;
  gaps: number;
};

export type State = {
  settings: Settings;
  binding: Binding | null;
  baselineEstablished: boolean;
  fingerprints: string[];
  messages: StoredMessage[];
  gaps: Gap[];
  outbox: OutboxItem[];
  drafts: Draft[];
  consumedCommandIds: string[];
  replyGrant: StandingGrant;
  scope: ContactScope;
  identity: IdentityEnrollment;
  deliveryRecords: DeliveryRecord[];
  historyComplete: false;
  keyMaterial: string;
  counters: Counters;
  lastDisposition: string;
};

export type StandingGrant = {
  enabled: boolean;
  token: string;
  localScopeId: string;
  grantedAtMillis: number;
  expiresAtMillis: number;
};

export { DEFAULT_SCOPE };

export type PublicView = {
  settings: Settings;
  binding: Binding | null;
  replyGrant: StandingGrant;
  scope: ContactScope;
  identityStatus: "unenrolled" | "self-chat" | "enrolled";
  deliveryEnabled: false;
  baselineEstablished: boolean;
  messages: Array<Pick<StoredMessage, "eventId" | "scopeId" | "sender" | "text" | "timeText" | "capturedAtMillis" | "purged">>;
  gaps: Gap[];
  drafts: Array<Pick<Draft, "handler" | "commandId" | "inReplyToEventId" | "scopeId" | "body" | "expiresAtMillis">>;
  historyComplete: false;
  verifiedRemoteRecipient: boolean;
  lastDisposition: string;
  counters: Counters;
};

export function clockText(value: string): boolean {
  return CLOCK.test(value.trim());
}

export function placeholder(eventId: string): string {
  return `LOCAL MOCK. No model was called. This is not a WhatsApp reply. Event ${eventId}.`;
}

export function canonicalDraft(draft: Draft): string {
  return [
    draft.handler,
    draft.commandId,
    draft.inReplyToEventId,
    draft.scopeId,
    draft.body,
    String(draft.expiresAtMillis),
    draft.correlationId,
    draft.deviceId,
    draft.keyId
  ].join("\n");
}
