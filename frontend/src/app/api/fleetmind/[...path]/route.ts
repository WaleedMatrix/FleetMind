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
]);

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const subpath = path.join("/");
  const assetDetail = /^assets\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;
  const assetMonitoring = /^assets\/[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\/(predictions|summary)$/;
  const allowed = METHODS.get(subpath)
    ?? (assetDetail.test(subpath) ? ["GET", "PATCH"] : undefined)
    ?? (assetMonitoring.test(subpath) ? ["GET"] : undefined)
    ?? (/^predictions\/[1-9][0-9]{0,9}\/explanation$/.test(subpath) ? ["GET"] : undefined);
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
    const timeout = AbortSignal.timeout(15_000);
    const response = await fetch(target, {
      method: request.method,
      headers: reads ? undefined : { "Content-Type": "application/json" },
      body,
      cache: "no-store",
      signal: reads ? AbortSignal.any([request.signal, timeout]) : timeout,
    });
    const result = await response.text();
    return new NextResponse(result, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json",
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
