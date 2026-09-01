import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";
import { acceptWorkspaceInvitation } from "@/lib/invitation";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = url.searchParams.get("next") || "/dashboard";
  const workspaceId = url.searchParams.get("workspace_id");
  if (code) {
    const supabase = createClient();
    const { data, error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error && data.session) {
      if (workspaceId) {
        try {
          await acceptWorkspaceInvitation({
            apiBase: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
            accessToken: data.session.access_token,
            workspaceId,
          });
        } catch {
          return NextResponse.redirect(
            new URL("/login?error=invitation_acceptance_failed", url.origin),
          );
        }
      }
      return NextResponse.redirect(new URL(next, url.origin));
    }
  }
  return NextResponse.redirect(new URL("/login?error=invalid_invitation", url.origin));
}
