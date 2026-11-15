export type HostCause = "" | "DISCONNECTED" | "HOST_EXITED" | "HOST_FORBIDDEN" | "HOST_NOT_FOUND" | "HOST_PROTOCOL" | "HOST_ERROR";

export type BridgeLifecycle = "off" | "connecting" | "open" | "exited";

export function classifyHostExit(message: string): HostCause {
  const text = message.toLowerCase();
  if (text.includes("forbidden")) return "HOST_FORBIDDEN";
  if (text.includes("not found")) return "HOST_NOT_FOUND";
  if (text.includes("communicating")) return "HOST_PROTOCOL";
  if (text.includes("exited")) return "HOST_EXITED";
  if (text.trim() === "") return "DISCONNECTED";
  return "HOST_ERROR";
}

export function bridgeLifecycle(input: { port: boolean; hello: string; cause: HostCause }): BridgeLifecycle {
  if (!input.port && input.cause) return "exited";
  if (input.port && input.hello === "READY") return "open";
  if (input.port) return "connecting";
  return "off";
}

export function safeHostDetail(message: string): string {
  const cleaned = message
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/\/\S+/g, "")
    .replace(/\bbearer\b/gi, "")
    .replace(/[^A-Za-z0-9 _.:-]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.slice(0, 80);
}
