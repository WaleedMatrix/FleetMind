import { PORTFOLIO } from "@/lib/profile";
import { NextRequest, NextResponse } from "next/server";
import { sessionCookies, upstreamUrl } from "@/lib/server-upstream";

function localRedirect(request: NextRequest, path: string) {
  const response = NextResponse.redirect(new URL(path, request.nextUrl.origin));
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (PORTFOLIO) {
    return /^\/(?:login|account|admin|access-denied)(?:\/|$)/.test(path)
      ? localRedirect(request, "/") : NextResponse.next();
  }
  const cookies = sessionCookies(request.headers.get("cookie"));
  if (path === "/login" && !cookies) return NextResponse.next();
  const login = () => localRedirect(request, "/login?next=" + encodeURIComponent(path + request.nextUrl.search));
  if (!cookies) return login();

  try {
    const response = await fetch(upstreamUrl("/api/v1/auth/me"), {
      headers: { Cookie: cookies }, cache: "no-store", redirect: "manual",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(4500)]),
    });
    if (response.status === 401) return path === "/login" ? NextResponse.next() : login();
    if (!response.ok) throw new Error("Security service unavailable");
    const { role } = await response.json() as { role?: string };
    if (path === "/login") return localRedirect(request, "/");
    if ((path.startsWith("/admin") && role !== "administrator")
      || (path === "/copilot" && role === "viewer")) return localRedirect(request, "/access-denied");
    const next = NextResponse.next();
    next.headers.set("Cache-Control", "no-store");
    return next;
  } catch {
    return path === "/login" ? NextResponse.next() : localRedirect(request, "/login?unavailable=1");
  }
}

export const config = {
  matcher: ["/", "/login", "/account", "/admin/:path*", "/access-denied",
    "/assets/:path*", "/model-intelligence", "/copilot", "/telemetry"],
};
