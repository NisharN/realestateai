interface InvitationAcceptanceOptions {
  apiBase: string;
  accessToken: string;
  workspaceId: string;
  request?: typeof fetch;
}

export async function acceptWorkspaceInvitation({
  apiBase,
  accessToken,
  workspaceId,
  request = fetch,
}: InvitationAcceptanceOptions): Promise<void> {
  const response = await request(`${apiBase}/api/v1/members/invitations/accept`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
  if (!response.ok) throw new Error("Invitation acceptance failed");
}
