/**
 * Server-side bridge from the Next.js dashboard to the local FastAPI service.
 * This avoids browser CORS issues and keeps the API host out of client code.
 * Only explicitly supported FleetMind paths are forwarded.
 */
import { PORTFOLIO } from "@/lib/profile";
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
  ["model/health", ["GET"]],
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

async function boundedBody(request: NextRequest, signal: AbortSignal, limit = MAX_BODY) {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^[0-9]{1,10}$/.test(length) || Number(length) > limit)) return null;
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
      if (total > limit) {
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

async function portfolioInference(request: NextRequest) {
  const respond = (detail: string, status: number, headers: Record<string, string> = {}) =>
    NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store", ...headers } });
  if (request.method !== "POST") return respond("Method not allowed", 405, { Allow: "POST" });
  if (request.headers.get("content-type")?.split(";", 1)[0].toLowerCase() !== "application/json") {
    return respond("Use a JSON sensor reading.", 415);
  }
  const unavailable = () => respond("Live inference is asleep or unavailable. Try again shortly.", 503);
  try {
    const origin = new URL(process.env.FLEETMIND_PORTFOLIO_API_URL ?? "");
    const render = origin.protocol === "https:" && /^[a-z0-9-]+\.onrender\.com$/.test(origin.hostname) && !origin.port;
    const loopback = origin.protocol === "http:" && origin.hostname === "127.0.0.1";
    if ((!render && !loopback) || origin.username || origin.password || origin.search || origin.hash || origin.pathname !== "/") {
      return unavailable();
    }
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]);
    const body = await boundedBody(request, signal, 2048);
    if (body === null) return respond("The reading exceeds 2 KiB.", 413);
    const response = await fetch(new URL("/infer", origin), {
      method: "POST", body, headers: { "Content-Type": "application/json" },
      redirect: "manual", cache: "no-store", signal,
    });
    if (!response.ok) {
      await response.body?.cancel();
      if (response.status === 429) {
        const retry = response.headers.get("retry-after");
        return respond("The shared demo is busy or rate-limited. Try again shortly.", 429,
          retry && /^[0-9]{1,3}$/.test(retry) ? { "Retry-After": retry } : {});
      }
      if ([408, 413, 415, 422].includes(response.status)) return respond("The demo reading was rejected.", response.status);
      return unavailable();
    }
    const { failure_score, predicted_failure, alert_level, model_version } = await response.json();
    if (typeof failure_score !== "number" || !(failure_score >= 0 && failure_score <= 1)
      || typeof predicted_failure !== "boolean" || !["high_priority", "review", "no_alert"].includes(alert_level)
      || typeof model_version !== "string" || !/^[\w.-]{1,40}$/.test(model_version)) return unavailable();
    return NextResponse.json({ failure_score, predicted_failure, alert_level, model_version }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return unavailable();
  }
}

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  if (path.some((part) => !/^[A-Za-z0-9_-]+$/.test(part))) {
    return NextResponse.json({ detail: "Unknown endpoint" }, { status: 404 });
  }
  const subpath = path.join("/");
  if (PORTFOLIO) return subpath === "demo/infer"
    ? portfolioInference(request) : NextResponse.json({ detail: "Unknown endpoint" }, { status: 404 });
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
    const requestId = request.headers.get("x-request-id");
    const forwardedId = requestId && /^[0-9a-f]{32}$/.test(requestId)
      ? requestId : crypto.randomUUID().replaceAll("-", "");
    headers.set("X-Request-ID", forwardedId);
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
    const correlation = response.headers.get("x-request-id");
    const responseId = correlation && /^[0-9a-f]{32}$/.test(correlation) ? correlation : forwardedId;
    if (streaming && response.ok && contentType.startsWith("text/event-stream")) {
      return new NextResponse(response.body, {
        headers: { "Content-Type": contentType, "Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no",
          "X-Request-ID": responseId },
      });
    }
    const result = response.status === 204 ? null : await response.text();
    const outgoing = new Headers({ "Content-Type": contentType, "Cache-Control": "no-store" });
    outgoing.set("X-Request-ID", responseId);
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
