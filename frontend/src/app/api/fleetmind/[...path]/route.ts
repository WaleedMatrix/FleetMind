/**
 * Server-side bridge from the Next.js dashboard to the local FastAPI service.
 * This avoids browser CORS issues and keeps the API host out of client code.
 * Only explicitly supported FleetMind paths are forwarded.
 */
import { NextRequest, NextResponse } from "next/server";
import { sessionCookies, upstreamUrl } from "@/lib/server-upstream";

type RouteContext = { params: Promise<{ path: string[] }> };
const METHODS = new Map([
  ["health", ["GET"]],
  ["dashboard/summary", ["GET"]],
  ["dashboard/trends", ["GET"]],
  ["predictions", ["GET"]],
  ["predict", ["POST"]],
  ["assets", ["GET", "POST"]],
  ["model/intelligence", ["GET"]],
  ["copilot/status", ["GET"]],
  ["knowledge/status", ["GET"]],
  ["copilot/conversations", ["GET", "POST"]],
  ["telemetry/stream", ["GET"]],
  ["telemetry/assessments", ["GET"]],
  ["telemetry/metrics", ["GET"]],
  ["telemetry/dead-letters", ["GET"]],
  ["telemetry/status", ["GET"]],
  ["auth/login", ["POST"]],
  ["auth/me", ["GET"]],
  ["auth/logout", ["POST"]],
  ["auth/password", ["POST"]],
  ["auth/sessions", ["GET"]],
  ["admin/users", ["GET", "POST"]],
  ["admin/audit", ["GET"]],
  ["admin/service-credentials", ["GET"]],
  ["admin/orphan-conversations", ["GET"]],
]);
const conversation = "copilot/conversations/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}";
const requestId = "[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}";
const conversationDetail = new RegExp(`^${conversation}$`);
const conversationMessages = new RegExp(`^${conversation}/messages$`);
const conversationStream = new RegExp(`^${conversation}/messages/stream$`);
const conversationCancel = new RegExp(`^${conversation}/requests/${requestId}/cancel$`);
const sessionDetail = new RegExp(`^auth/sessions/${requestId}$`);
const adminEdit = new RegExp(`^admin/(users|orphan-conversations)/${requestId}$`);
const serviceDetail = new RegExp(`^admin/service-credentials/${requestId}$`);
const MAX_BODY = 65_536;
const COOKIE_RESPONSE = /^(?:__Host-)?fleetmind_(?:session|csrf)=/;

async function boundedBody(request: NextRequest, signal: AbortSignal) {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^[0-9]{1,10}$/.test(length) || Number(length) > MAX_BODY)) return null;
  if (!request.body) return Buffer.alloc(0);
  const reader = request.body.getReader();
  const cancel = () => { void reader.cancel().catch(() => undefined); };
  signal.addEventListener("abort", cancel, { once: true });
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      signal.throwIfAborted();
      if (done) return Buffer.concat(chunks, total);
      total += value.byteLength;
      if (total > MAX_BODY) {
        cancel();
        return null;
      }
      chunks.push(value);
    }
  } finally {
    signal.removeEventListener("abort", cancel);
    reader.releaseLock();
  }
}

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  if (path.some((part) => !/^[A-Za-z0-9_-]+$/.test(part))) {
    return NextResponse.json({ detail: "Unknown endpoint" }, { status: 404 });
  }
  const subpath = path.join("/");
  const assetDetail = /^assets\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;
  const assetMonitoring = /^assets\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\/(predictions|summary)$/;
  const telemetryStream = subpath === "telemetry/stream";
  const chatStream = conversationStream.test(subpath);
  const streaming = telemetryStream || chatStream;
  const allowed = METHODS.get(subpath)
    ?? (assetDetail.test(subpath) ? ["GET", "PATCH"] : undefined)
    ?? (assetMonitoring.test(subpath) ? ["GET"] : undefined)
    ?? (/^predictions\/[1-9][0-9]{0,9}(?:\/explanation)?$/.test(subpath) ? ["GET"] : undefined)
    ?? (conversationDetail.test(subpath) ? ["GET", "PATCH", "DELETE"] : undefined)
    ?? (conversationMessages.test(subpath) ? ["GET"] : undefined)
    ?? (chatStream || conversationCancel.test(subpath) ? ["POST"] : undefined)
    ?? (sessionDetail.test(subpath) || serviceDetail.test(subpath) ? ["DELETE"] : undefined)
    ?? (adminEdit.test(subpath) ? ["PATCH"] : undefined)
    ?? (/^knowledge\/documents\/[a-z0-9][a-z0-9-]{0,63}\/chunks\/[a-f0-9]{64}$/.test(subpath)
      ? ["GET"] : undefined);
  if (!allowed) {
    return NextResponse.json({ detail: "Unknown endpoint" }, { status: 404 });
  }
  if (!allowed.includes(request.method)) {
    return NextResponse.json({ detail: "Method not allowed" }, {
      status: 405,
      headers: { Allow: allowed.join(", ") },
    });
  }

  try {
    const target = upstreamUrl(subpath === "health" ? "/api/v1/system/status" : `/api/v1/${subpath}`);
    target.search = request.nextUrl.search;
    const reads = request.method === "GET";
    const timeout = AbortSignal.timeout(telemetryStream ? 310_000 : streaming ? 135_000 : 15_000);
    const signal = AbortSignal.any([request.signal, timeout]);
    const body = reads ? undefined : await boundedBody(request, signal);
    if (body === null) return NextResponse.json({ detail: "Request body is too large." }, { status: 413 });
    const headers = new Headers();
    if (body?.byteLength) headers.set("Content-Type", "application/json");
    const cookies = sessionCookies(request.headers.get("cookie"));
    if (cookies) headers.set("Cookie", cookies);
    const origin = request.headers.get("origin");
    if (origin) headers.set("Origin", origin);
    const csrf = request.headers.get("x-fleetmind-csrf");
    if (csrf) headers.set("X-FleetMind-CSRF", csrf);
    const lastEvent = request.headers.get("last-event-id");
    if (telemetryStream && lastEvent) headers.set("Last-Event-ID", lastEvent);
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: body?.byteLength ? body : undefined,
      cache: "no-store",
      redirect: "manual",
      signal,
    });
    if (response.status >= 300 && response.status < 400) {
      await response.body?.cancel();
      return NextResponse.json({ detail: "Unexpected API redirect." }, { status: 502 });
    }
    const contentType = response.headers.get("content-type") || "application/json";
    if (streaming && response.ok && contentType.startsWith("text/event-stream")) {
      return new NextResponse(response.body, {
        headers: { "Content-Type": contentType, "Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no" },
      });
    }
    const result = response.status === 204 ? null : await response.text();
    const outgoing = new Headers({ "Content-Type": contentType, "Cache-Control": "no-store" });
    const retry = response.headers.get("retry-after");
    if (retry) outgoing.set("Retry-After", retry);
    if (["auth/login", "auth/logout", "auth/password"].includes(subpath) || sessionDetail.test(subpath)) {
      for (const cookie of response.headers.getSetCookie()) {
        if (COOKIE_RESPONSE.test(cookie)) outgoing.append("Set-Cookie", cookie);
      }
    }
    return new NextResponse(result, { status: response.status, headers: outgoing });
  } catch {
    return NextResponse.json(
      { detail: "FleetMind backend unavailable. Verify FastAPI is running at the configured address." },
      { status: 502 },
    );
  }
}

export async function GET(request: NextRequest, context: RouteContext) {
  return forward(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return forward(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return forward(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return forward(request, context);
}
