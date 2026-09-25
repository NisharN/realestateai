import { afterEach, describe, expect, it, vi } from "vitest";

let resolveSession: (v: unknown) => void = () => {};
vi.mock("./supabase/client", () => ({
  createClient: () => ({
    auth: { getSession: () => new Promise((resolve) => (resolveSession = resolve)) },
  }),
}));

import { VoiceWebSocket } from "./api";

describe("VoiceWebSocket.connect", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("does not open a socket when disconnect() happens during the auth lookup", async () => {
    const WebSocketMock = vi.fn();
    vi.stubGlobal("WebSocket", WebSocketMock);
    vi.stubGlobal("localStorage", { getItem: () => null });

    const ws = new VoiceWebSocket("lead-1", vi.fn(), vi.fn());
    const pending = ws.connect();
    ws.disconnect();
    resolveSession({ data: { session: { access_token: "tok" } } });
    await pending;

    expect(WebSocketMock).not.toHaveBeenCalled();
  });
});
