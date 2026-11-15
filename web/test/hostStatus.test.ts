import { describe, expect, it } from "vitest";
import { bridgeLifecycle, classifyHostExit, safeHostDetail } from "../src/hostStatus.js";

describe("native host lifecycle", () => {
  it("does not call a created port open until hello is acknowledged", () => {
    expect(bridgeLifecycle({ port: true, hello: "pending", cause: "" })).toBe("connecting");
    expect(bridgeLifecycle({ port: true, hello: "READY", cause: "" })).toBe("open");
    expect(bridgeLifecycle({ port: false, hello: "pending", cause: "HOST_EXITED" })).toBe("exited");
    expect(bridgeLifecycle({ port: false, hello: "READY", cause: "HOST_EXITED" })).toBe("exited");
    expect(bridgeLifecycle({ port: false, hello: "none", cause: "" })).toBe("off");
  });

  it("names a host exit without keeping a path or a credential", () => {
    expect(classifyHostExit("Native host has exited.")).toBe("HOST_EXITED");
    expect(classifyHostExit("Access to the specified native messaging host is forbidden.")).toBe("HOST_FORBIDDEN");
    expect(classifyHostExit("Specified native messaging host not found.")).toBe("HOST_NOT_FOUND");
    expect(classifyHostExit("Error when communicating with the native messaging host.")).toBe("HOST_PROTOCOL");
    expect(classifyHostExit("")).toBe("DISCONNECTED");
    expect(safeHostDetail("Native host has exited. /tmp/box/secret http://127.0.0.1 Bearer")).toBe(
      "Native host has exited."
    );
  });
});
