import { NextResponse, type NextRequest } from "next/server";

import { refreshSession } from "@/lib/supabase/middleware";

const protectedPaths = ["/", "/dashboard", "/configure", "/docs", "/members", "/properties"];

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export async function middleware(request: NextRequest) {
  if (DEMO_MODE) {
    return NextResponse.next({ request });
  }
  const { response, user } = await refreshSession(request);
  const pathname = request.nextUrl.pathname;
  const isProtected = protectedPaths.some(
    (path) => pathname === path || (path !== "/" && pathname.startsWith(`${path}/`)),
  );

  if (isProtected && !user) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }
  if (pathname === "/login" && user) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
