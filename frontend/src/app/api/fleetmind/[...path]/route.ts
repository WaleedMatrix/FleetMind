/**
 * Server-side bridge from the Next.js dashboard to the local FastAPI service.
 * This avoids browser CORS issues and keeps the API host out of client code.
 * Only explicitly supported FleetMind paths are forwarded.
 */
import { NextRequest, NextResponse } from "next/server";

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
]);
const conversation = "copilot/conversations/[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}";
const requestId = "[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}";
const conversationDetail = new RegExp(`^${conversation}$`);
const conversationMessages = new RegExp(`^${conversation}/messages$`);
const conversationStream = new RegExp(`^${conversation}/messages/stream$`);
const conversationCancel = new RegExp(`^${conversation}/requests/${requestId}/cancel$`);

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const subpath = path.join("/");
  const assetDetail = /^assets\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;
  const assetMonitoring = /^assets\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\/(predictions|summary)$/;
  const streaming = conversationStream.test(subpath);
  const allowed = METHODS.get(subpath)
    ?? (assetDetail.test(subpath) ? ["GET", "PATCH"] : undefined)
    ?? (assetMonitoring.test(subpath) ? ["GET"] : undefined)
    ?? (/^predictions\/[1-9][0-9]{0,9}(?:\/explanation)?$/.test(subpath) ? ["GET"] : undefined)
    ?? (conversationDetail.test(subpath) ? ["GET", "PATCH", "DELETE"] : undefined)
    ?? (conversationMessages.test(subpath) ? ["GET"] : undefined)
    ?? (streaming || conversationCancel.test(subpath) ? ["POST"] : undefined)
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

  const apiBase = process.env.FLEETMIND_API_URL || "http://127.0.0.1:8000";
  const upstreamPath = subpath === "health" ? "/health" : `/api/v1/${subpath}`;
  const target = new URL(upstreamPath, apiBase);
  target.search = request.nextUrl.search;

  try {
    const reads = request.method === "GET";
    const body = reads ? undefined : await request.text();
    const timeout = AbortSignal.timeout(streaming ? 135_000 : 15_000);
    const response = await fetch(target, {
      method: request.method,
      headers: reads ? undefined : { "Content-Type": "application/json" },
      body,
      cache: "no-store",
      signal: reads || streaming ? AbortSignal.any([request.signal, timeout]) : timeout,
    });
    const contentType = response.headers.get("content-type") || "application/json";
    if (streaming && response.ok && contentType.startsWith("text/event-stream")) {
      return new NextResponse(response.body, {
        headers: { "Content-Type": contentType, "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" },
      });
    }
    const result = response.status === 204 ? null : await response.text();
    return new NextResponse(result, {
      status: response.status,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "no-store",
      },
    });
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
