/**
 * Server-side bridge from the Next.js dashboard to the local FastAPI service.
 * This avoids browser CORS issues and keeps the API host out of client code.
 * Only explicitly supported FleetMind paths are forwarded.
 */
import { NextRequest, NextResponse } from "next/server";

type RouteContext = { params: Promise<{ path: string[] }> };
const ALLOWED = new Set([
  "health",
  "dashboard/summary",
  "dashboard/trends",
  "predictions",
  "predict",
]);

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const subpath = path.join("/");
  if (!ALLOWED.has(subpath)) {
    return NextResponse.json({ detail: "Unknown endpoint" }, { status: 404 });
  }
  if (request.method === "POST" && subpath !== "predict") {
    return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
  }
  if (request.method === "GET" && subpath === "predict") {
    return NextResponse.json({ detail: "Method not allowed" }, { status: 405 });
  }

  const apiBase = process.env.FLEETMIND_API_URL || "http://127.0.0.1:8000";
  const upstreamPath = subpath === "health" ? "/health" : `/api/v1/${subpath}`;
  const target = new URL(upstreamPath, apiBase);
  target.search = request.nextUrl.search;

  try {
    const response = await fetch(target, {
      method: request.method,
      headers: request.method === "POST" ? { "Content-Type": "application/json" } : undefined,
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
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
