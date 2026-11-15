type View = {
  settings: {
    onboardingAccepted: boolean;
    collectionEnabled: boolean;
    exportEnabled: boolean;
  };
  binding: {
    visibleHeader: string;
    selfLabel: string;
    localScopeId: string;
    mode?: "messages" | "metadata";
    verifiedRemoteRecipient: false;
  } | null;
  baselineEstablished: boolean;
  messages: Array<{ eventId: string; text: string; sender: string; timeText: string; purged: boolean }>;
  gaps: Array<{ reason: string; detail: string }>;
  drafts: Array<{ commandId: string; handler: string; body: string; inReplyToEventId: string }>;
  historyComplete: false;
  verifiedRemoteRecipient: boolean;
  identityStatus?: "unenrolled" | "self-chat" | "enrolled";
  lastDisposition: string;
  replyGrant?: { enabled: boolean; token: string; localScopeId: string };
  scope?: { mode: string };
  deliveryEnabled: false;
};

type ReplyGate = {
  ok: boolean;
  delivered: false;
  reason: string;
  blocked: string[];
  transport: "none";
};

type Reply = {
  view?: View;
  error?: string;
  header?: string;
  disposition?: string;
  surface?: string;
  attention?: string;
  identity?: string;
  messagesCollected?: false;
  result?: { disposition: string };
  bridge?: {
    state: string;
    hello: string;
    scope: string;
    list: string;
    recent?: string;
    forward?: string;
    event?: string;
    posted: boolean;
    count?: number | null;
    prior?: number | null;
    stored?: number | null;
    change?: string;
    at?: string;
    lastForward?: string;
    lastEvent?: string;
    lastAt?: string;
    cause: string;
    detail: string;
  };
  bridgeForward?: string;
  replyGate?: ReplyGate;
  read?: {
    disposition: string;
    header: string;
    rows: Array<{ timeText: string; text: string; direction: string; senderLabel?: string }>;
    coverage: {
      historyComplete: false;
      phoneHistoryBoundary?: boolean;
      occurrenceJoin?: string;
      uiTopReached: boolean;
      continuityGap: boolean;
      orderProven: boolean;
      renderGap?: boolean;
      samples: number;
      scrolls: number;
      capped: boolean;
      keyed?: number;
      unkeyed?: number;
      unique: number;
      duplicates: number;
      withoutText: number;
      unparsed: number;
      stopped: string;
    };
  };
};

const app = document.querySelector("#app");
if (!app) throw new Error("popup");

const statusLine = el("p");
statusLine.id = "status";
const headerLine = el("p");
headerLine.id = "header-line";
const bindingLine = el("p");
bindingLine.id = "binding-line";
const claimLine = el("p");
claimLine.id = "claim-line";
const bridgeLine = el("p");
bridgeLine.id = "bridge-line";
const selfInput = document.createElement("input");
const capInput = document.createElement("input");
capInput.id = "reply-cap";
capInput.placeholder = "0";
let boundHeader = "";
selfInput.id = "self-label";
selfInput.autocomplete = "off";
selfInput.maxLength = 80;
const onboarding = document.createElement("input");
onboarding.id = "onboarding";
onboarding.type = "checkbox";
const messageList = el("ul");
messageList.id = "messages";
const draftList = el("ul");
draftList.id = "drafts";
const gapList = el("ul");
gapList.id = "gaps";
const wakeLine = el("p");
wakeLine.id = "wake-open";
wakeLine.textContent = "Wake open: not requested. It does not send.";
const contactLine = el("p");
contactLine.id = "contact-surface";
contactLine.textContent = "Contact surface: not checked. It does not open a chat and it does not send.";
const attemptLine = el("p");
attemptLine.id = "attempt";
const readLine = el("p");
readLine.id = "read-line";
readLine.textContent = "Bound chat read: not run. It does not post a wake and it does not export text.";
const readList = el("ul");
readList.id = "read-messages";
let lastRead: Reply["read"] | null = null;

app.append(
  titled("Draft Bridge Web"),
  note("Capture and draft only. Sending is disabled. This is not a WhatsApp client and it has not been validated on live WhatsApp Web."),
  note("These screens are English. Open-chat matching accepts the Traditional Chinese names from one observed build, and English names taken from public browser-automation sources. Those English names are fixture-tested here. They are not a live observation from this project. Any other wording fails closed."),
  note("Replies stay off until you set a contact scope and turn the grant on for the open chat. The default scope is nobody. Stop revokes the grant. It remembers that binding id. A different chat does not inherit it. Turning the grant on does not send. Delivery stays closed until incoming direction and contact identity are proven. A sender label is not that proof. Message text cannot change the scope."),
  note("Intended page: web.whatsapp.com. Bind one visible header. After that, the chat-list signal for that label does not need the chat to stay open. The label is not a verified recipient."),
  note("The self field is only for strict message binding: the exact sender text on your own messages. The business profile name is not that text. If your own messages show no sender name, leave the field blank. Strict bind stays closed. Bind metadata scope uses only the open-chat token for the local chat-list signal. It does not invent a sender name, store message text, or enable sending. Direction stays unproven."),
  row(onboarding, text("I understand collection stays off until I enable it for the chat I bind.")),
  labeled("Exact sender text on your own messages", selfInput),
  labeled("Reply cap for a new scope", capInput),
  buttons(),
  headerLine,
  bindingLine,
  claimLine,
  bridgeLine,
  statusLine,
  heading("Gaps"),
  gapList,
  heading("Bound chat read"),
  note("Reads only the open chat whose header and composer names match the bound token. It scrolls that transcript upward and can mark the chat read. It does not send, does not post the wake, and does not export the text. A visible name leaf is a sender label, not incoming or outgoing. Direction stays unknown. Identical text at the same time stays if it was rendered twice. Complete history stays false. The phone-history control is not the start of the chat."),
  readLine,
  readList,
  heading("Local messages"),
  messageList,
  heading("Draft preview"),
  draftList,
  attemptLine,
  wakeLine,
  contactLine
);

wire();
chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === "local") void refresh();
});
void refresh();

function buttons(): HTMLElement {
  const box = el("div");
  box.append(
    action("Read open chat", "peek", () => send({ type: "peek" })),
    action("Read bound chat", "read-chat", async () => {
      const reply = await send({ type: "read-chat" });
      if (reply.read) lastRead = reply.read;
      paintRead(reply.read, reply.error);
      if (reply.replyGate) {
        attemptLine.textContent = `Reply gate: ${reply.replyGate.reason}. Blocked: ${reply.replyGate.blocked.join(",")}. Delivered: no.`;
      }
      return reply;
    }),
    action("Bind this chat", "bind", () => send({ type: "bind", selfLabel: selfInput.value })),
    action("Bind metadata scope", "bind-metadata", () => send({ type: "bind-metadata" })),
    action("Turn collection on", "collection-on", () => send({ type: "set-collection", enabled: true })),
    action("Turn export on", "export-on", () => send({ type: "set-export", enabled: true })),
    action("Stop", "stop", () => send({ type: "stop" })),
    action("Scope off", "scope-off", async () => {
      const reply = await send({ type: "set-scope", scope: { mode: "off", allow: [], deny: [], groups: "exclude", maxReplies: 0 } });
      if (reply.disposition) statusLine.textContent = reply.disposition;
      return reply;
    }),
    action("Allow only this chat", "scope-allow", async () => {
      const header = lastHeader();
      const reply = await send({
        type: "set-scope",
        scope: { mode: "allowlist", allow: header ? [header] : [], deny: [], groups: "exclude", maxReplies: capValue() }
      });
      if (reply.disposition) statusLine.textContent = reply.disposition;
      return reply;
    }),
    action("Allow direct chats", "scope-direct", async () => {
      const reply = await send({
        type: "set-scope",
        scope: { mode: "direct", allow: [], deny: [], groups: "exclude", maxReplies: capValue() }
      });
      if (reply.disposition) statusLine.textContent = reply.disposition;
      return reply;
    }),
    action("Grant replies for this chat", "reply-grant-on", async () => {
      const reply = await send({ type: "set-reply-grant", enabled: true });
      if (reply.disposition) statusLine.textContent = reply.disposition;
      return reply;
    }),
    action("Revoke replies", "reply-grant-off", async () => {
      const reply = await send({ type: "set-reply-grant", enabled: false });
      if (reply.disposition) statusLine.textContent = reply.disposition;
      return reply;
    }),
    action("Reload queue", "reload", () => send({ type: "reload-queue" })),
    action("Inspect one unread", "inspect-unread", async () => {
      const reply = await send({ type: "inspect-unread" });
      const disposition = typeof reply.disposition === "string" && /^[A-Z_]{1,40}$/.test(reply.disposition) ? reply.disposition : "UNPROVEN";
      const identity = reply.identity === "AMBIGUOUS" ? "ambiguous" : "unproven";
      contactLine.textContent = `List inspect: ${disposition}. Identity: ${identity}. Messages collected: no. It does not send.`;
      return reply;
    }),
    action("Check contact info", "contact-surface", async () => {
      const reply = await send({ type: "contact-surface" });
      const surface = reply.surface === "direct-contact" ? "DIRECT_CONTACT" : "UNPROVEN";
      const attention = reply.attention === "VISIBLE_CONTEXT" ? "visible context" : "closed";
      contactLine.textContent = `Contact surface: ${surface}. Attention: ${attention}. It does not send.`;
      return reply;
    }),
    action("Open wake target", "open-wake", async () => {
      const reply = await send({ type: "open-wake" });
      const disposition = typeof reply.disposition === "string" && /^[A-Z_]{1,40}$/.test(reply.disposition) ? reply.disposition : "UNREADABLE";
      wakeLine.textContent = `Wake open: ${disposition}. It does not send.`;
      return reply;
    }),
    action("Purge texts", "purge", () => send({ type: "purge" }))
  );
  return box;
}

function wire(): void {
  onboarding.addEventListener("change", () => {
    void send({ type: "set-onboarding", accepted: onboarding.checked });
  });
}

async function refresh(): Promise<void> {
  const reply = await send({ type: "get-view" });
  paint(reply);
}

function lastHeader(): string {
  return boundHeader;
}

function capValue(): number {
  const parsed = Number(capInput.value);
  return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000 ? parsed : 0;
}

async function send(message: Record<string, unknown>): Promise<Reply> {
  const reply = (await chrome.runtime.sendMessage(message)) as Reply;
  if (reply?.view) paint(reply);
  if (reply?.error) statusLine.textContent = reply.error;
  if (typeof reply?.header === "string") {
    if (reply.header) headerLine.textContent = `Open chat label: ${reply.header}`;
    else if (reply.error === "content-script-missing") {
      headerLine.textContent = "Open chat label: (none). Reload the WhatsApp tab, then read it again.";
    } else if (reply.error) headerLine.textContent = "Open chat label: (none).";
    else headerLine.textContent = "Open chat label: (none). The reported header and composer names were not both visible.";
  }
  return reply;
}

function countClause(bridge: {
  count?: number | null;
  prior?: number | null;
  stored?: number | null;
  change?: string;
}): string {
  if (bridge.change === "held") {
    const observed = typeof bridge.count === "number" ? ` Observed count: ${bridge.count}.` : "";
    const stored = typeof bridge.stored === "number" ? ` Stored count: ${bridge.stored}.` : "";
    return ` Count: held.${observed}${stored}`;
  }
  if (typeof bridge.count !== "number") return "";
  if (bridge.change === "up" && typeof bridge.prior === "number") {
    return ` Count: ${bridge.count}. Change: up from ${bridge.prior} to ${bridge.count}.`;
  }
  if (bridge.change === "down" && typeof bridge.prior === "number") {
    return ` Count: ${bridge.count}. Change: down from ${bridge.prior} to ${bridge.count}.`;
  }
  if (bridge.change === "clear") return ` Count: 0. Change: cleared.`;
  if (bridge.change === "baseline") return ` Count: ${bridge.count}. Change: baseline.`;
  if (bridge.change === "same") return ` Count: ${bridge.count}. Change: same.`;
  return ` Count: ${bridge.count}.`;
}

function forwardClause(bridge: { forward?: string; event?: string }): string {
  if (bridge.forward !== "attempted" && bridge.forward !== "accepted" && bridge.forward !== "error") return "";
  const event = bridge.event ? ` Event: ${bridge.event}.` : "";
  if (bridge.forward === "accepted") return ` Forward: accepted.${event} HTTP ack is not a chat receipt.`;
  if (bridge.forward === "attempted") return ` Forward: attempted.${event} Not accepted yet.`;
  return ` Forward: error.${event} Not accepted.`;
}

function lastClause(bridge: { forward?: string; lastForward?: string; lastEvent?: string; lastAt?: string }): string {
  if (bridge.forward === "attempted" || bridge.forward === "accepted" || bridge.forward === "error") return "";
  if (!bridge.lastEvent) return "";
  const when = bridge.lastAt ? ` at ${bridge.lastAt}` : "";
  return ` Last forward: ${bridge.lastForward || "none"}. Last event: ${bridge.lastEvent}${when}. That HTTP ack is not this sample and is not a chat receipt.`;
}

function paint(reply: Reply | undefined): void {
  const view = reply?.view;
  if (!view) return;
  onboarding.checked = view.settings.onboardingAccepted;
  paintRead(lastRead, undefined);
  boundHeader = view.binding?.visibleHeader ?? "";
  if (view.binding && view.binding.mode !== "metadata" && selfInput.value === "") selfInput.value = view.binding.selfLabel;
  const direction = !view.binding ? "none" : view.binding.mode === "metadata" ? "unproven" : "proven";
  bindingLine.textContent = !view.binding
    ? "No chat is bound."
    : view.binding.mode === "metadata"
      ? `Metadata scope ${view.binding.localScopeId} for “${view.binding.visibleHeader}”. Message direction: unproven.`
      : `Message scope ${view.binding.localScopeId} for “${view.binding.visibleHeader}”. Message direction: proven.`;
  const grant = view.replyGrant?.enabled ? "on" : "off";
  const identity = view.identityStatus ?? "unenrolled";
  const scopeMode = view.scope?.mode ?? "off";
  claimLine.textContent = `Onboarding: ${view.settings.onboardingAccepted ? "yes" : "no"}. Verified remote recipient: ${String(view.verifiedRemoteRecipient)}. Identity: ${identity}. Complete history: ${String(view.historyComplete)}. Direction: ${direction}. Collection: ${view.settings.collectionEnabled ? "on" : "off"}. Export: ${view.settings.exportEnabled ? "on" : "off"}. Contact scope: ${scopeMode}. Reply grant: ${grant}. Delivery: ${view.deliveryEnabled ? "on" : "closed"}. Live send: off. Last: ${view.lastDisposition || "none"}.`;
  const bridge = reply?.bridge;
  bridgeLine.textContent = bridge
    ? `Page bridge: ${bridge.state}. Hello: ${bridge.hello}. Scope: ${bridge.scope}. List: ${bridge.list}.${bridge.recent ? ` Recent: ${bridge.recent}.` : ""}${countClause(bridge)} This sample posted: ${bridge.posted ? "yes" : "no"}.${bridge.at ? ` Seen: ${bridge.at}.` : ""}${forwardClause(bridge)}${lastClause(bridge)}${bridge.cause ? ` Cause: ${bridge.cause}.` : ""}${bridge.detail ? ` Detail: ${bridge.detail}.` : ""}`
    : "Page bridge: off.";
  fill(gapList, view.gaps.map((gap) => `${gap.reason}: ${gap.detail}`));
  fill(
    messageList,
    view.messages.filter((message) => !message.purged).map((message) => `${message.timeText} ${message.sender}: ${message.text}`)
  );
  draftList.replaceChildren();
  for (const draft of view.drafts) {
    const item = el("li");
    const copy = el("p");
    copy.textContent = `${draft.handler}: ${draft.body}`;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Keep draft here";
    button.addEventListener("click", () => {
      void confirmDraft(draft.commandId, draft.body);
    });
    item.append(copy, button);
    draftList.append(item);
  }
}

async function confirmDraft(commandId: string, body: string): Promise<void> {
  const view = (await chrome.runtime.sendMessage({ type: "get-view" })) as Reply;
  const engineReply = await chrome.runtime.sendMessage({
    type: "confirm-draft",
    commandId,
    exactBody: body
  });
  attemptLine.textContent = engineReply?.attempt
    ? `${engineReply.attempt.kind} ${engineReply.attempt.reason}`
    : "unavailable";
  if (view.view) paint(view);
  const again = (await chrome.runtime.sendMessage({ type: "get-view" })) as Reply;
  if (again.view) paint(again);
}

function paintRead(read: Reply["read"] | null | undefined, error: string | undefined): void {
  if (!read) {
    if (error) readLine.textContent = `Bound chat read: ${error}. Nothing was scrolled.`;
    return;
  }
  const coverage = read.coverage;
  readLine.textContent = [
    `Bound chat read: ${read.disposition}.`,
    `Header: ${read.header || "(none)"}.`,
    `Samples: ${coverage.samples}.`,
    `Keyed: ${coverage.keyed ?? coverage.unique}.`,
    `Unkeyed: ${coverage.unkeyed ?? 0}.`,
    `Occurrences: ${coverage.unique}.`,
    `Replayed: ${coverage.duplicates}.`,
    `Join: ${coverage.occurrenceJoin || "none"}.`,
    `Scrolls: ${coverage.scrolls}.`,
    `Stopped: ${coverage.stopped}.`,
    `Pane top: ${coverage.uiTopReached ? "yes" : "no"}.`,
    `Render gap: ${coverage.renderGap ? "yes" : "no"}.`,
    `Order proven: ${coverage.orderProven ? "yes" : "no"}.`,
    `Phone history: ${coverage.phoneHistoryBoundary ? "yes" : "no"}.`,
    `Complete history: ${String(coverage.historyComplete)}.`
  ].join(" ");
  fill(
    readList,
    read.rows.map((row) => {
      const label = row.senderLabel ? ` sender-label ${row.senderLabel}` : "";
      return `${row.timeText} ${row.direction}${label}: ${row.text}`;
    })
  );
}

function fill(list: HTMLElement, rows: string[]): void {
  list.replaceChildren();
  for (const row of rows) {
    const item = el("li");
    item.textContent = row;
    list.append(item);
  }
}

function titled(value: string): HTMLElement {
  const node = el("h1");
  node.textContent = value;
  return node;
}

function heading(value: string): HTMLElement {
  const node = el("h2");
  node.textContent = value;
  return node;
}

function note(value: string): HTMLElement {
  const node = el("p");
  node.textContent = value;
  return node;
}

function text(value: string): HTMLElement {
  const node = el("span");
  node.textContent = value;
  return node;
}

function row(...nodes: Node[]): HTMLElement {
  const node = el("label");
  node.append(...nodes);
  return node;
}

function labeled(value: string, field: HTMLElement): HTMLElement {
  const node = el("label");
  node.append(text(value), field);
  return node;
}

function action(label: string, id: string, run: () => Promise<Reply>): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.id = id;
  button.textContent = label;
  button.addEventListener("click", () => {
    void run();
  });
  return button;
}

function el(tag: string): HTMLElement {
  return document.createElement(tag);
}
