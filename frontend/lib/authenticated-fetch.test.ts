import { afterEach, describe, expect, it, vi } from "vitest";

import { createAuthenticatedFetch } from "./authenticated-fetch";


describe("createAuthenticatedFetch", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the bearer token and active workspace on every request", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const authenticatedFetch = createAuthenticatedFetch({
      baseUrl: "https://api.example.test",
      getAccessToken: async () => "access-token",
      getWorkspaceId: () => "workspace-a",
    });

    await authenticatedFetch("/api/v1/auth/me");

    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/api/v1/auth/me",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
          "X-Workspace-ID": "workspace-a",
        }),
      }),
    );
  });

  it("allows the backend to resolve a user's only workspace", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    const authenticatedFetch = createAuthenticatedFetch({
      baseUrl: "https://api.example.test",
      getAccessToken: async () => "access-token",
      getWorkspaceId: () => null,
    });

    await authenticatedFetch("/api/v1/auth/me");

    const init = fetchMock.mock.calls[0][1];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.has("X-Workspace-ID")).toBe(false);
  });
});
