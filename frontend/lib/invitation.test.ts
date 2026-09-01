import { describe, expect, it, vi } from "vitest";

import { acceptWorkspaceInvitation } from "./invitation";

describe("acceptWorkspaceInvitation", () => {
  it("sends the verified token and scoped workspace to the acceptance endpoint", async () => {
    const request = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));

    await acceptWorkspaceInvitation({
      apiBase: "https://api.example.com",
      accessToken: "verified-token",
      workspaceId: "workspace-a",
      request,
    });

    expect(request).toHaveBeenCalledWith(
      "https://api.example.com/api/v1/members/invitations/accept",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer verified-token" }),
        body: JSON.stringify({ workspace_id: "workspace-a" }),
      }),
    );
  });
});
