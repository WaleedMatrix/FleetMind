import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import vm from "node:vm";
import ts from "typescript";

class BridgeResponse extends Response {
  static json(...args) { return Response.json(...args); }
}

function load(relative, symbols = {}) {
  const source = fs.readFileSync(path.resolve(import.meta.dirname, "../src", relative), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const exports = {};
  vm.runInNewContext(outputText, {
    AbortSignal, Buffer, Headers, URL, crypto, exports, process: { env: { FLEETMIND_API_URL: "http://backend.invalid:8000" } },
    require(id) {
      if (id === "next/server") return { NextResponse: BridgeResponse };
      if (id === "@/lib/profile") return { PORTFOLIO: symbols.process?.env.NEXT_PUBLIC_FLEETMIND_MODE === "portfolio" };
      if (id === "@/lib/server-upstream") return load("lib/server-upstream.ts");
      throw new Error("Unexpected import " + id);
    },
    ...symbols,
  });
  return exports;
}

function request(method, inputHeaders = {}, body) {
  const url = new URL("https://fleetmind.invalid/api/fleetmind/?limit=5");
  return Object.assign(new Request(url, { method, headers: inputHeaders, body }), { nextUrl: url });
}

const route = fetch => load("app/api/fleetmind/[...path]/route.ts", { fetch });
const call = (method, path, options) => [request(method, options?.headers, options?.body), { params: Promise.resolve({ path }) }];

test("bridge refuses unknown paths, separators, and disallowed methods before fetch", async () => {
  const upstream = route(() => assert.fail("An unsupported request reached the backend"));
  for (const path of [["..", "users"], ["assets/../auth", "me"], ["%2fassets"], ["http:", "another.host"], ["settings"]]) {
    assert.equal((await upstream.GET(...call("GET", path))).status, 404);
  }
  assert.equal((await upstream.POST(...call("POST", ["auth", "me"]))).status, 405);
});

test("bridge uses fixed upstream and forwards only permitted headers and cookies", async () => {
  const session = "a".repeat(43);
  const expectedCsrf = "b".repeat(64);
  const upstream = route(async (url, init) => {
    assert.equal(url.href, "http://backend.invalid:8000/api/v1/auth/password?limit=5");
    assert.equal(init.headers.get("cookie"), "fleetmind_session=" + session);
    assert.equal(init.headers.get("origin"), "https://fleetmind.invalid");
    assert.equal(init.headers.get("x-fleetmind-csrf"), expectedCsrf);
    assert.equal(init.headers.get("authorization"), null);
    assert.equal(init.headers.get("x-forwarded-host"), null);
    assert.equal(init.headers.get("host"), null);
    assert.equal(init.redirect, "manual");
    assert.equal(init.cache, "no-store");
    assert.deepEqual(JSON.parse(init.body), { field: "body" });
    return new Response("{}", {
      status: 429, headers: [
        ["retry-after", "60"],
        ["set-cookie", "fleetmind_session=expired; HttpOnly"],
        ["set-cookie", "fleetmind_csrf=expired"],
        ["set-cookie", "foreign=credential"],
        ["x-internal-api-key", "private"],
      ],
    });
  });
  const result = await upstream.POST(...call("POST", ["auth", "password"], {
    headers: {
      Cookie: "unrelated=private; fleetmind_session=" + session,
      Origin: "https://fleetmind.invalid", "X-FleetMind-CSRF": expectedCsrf,
      Authorization: "Bearer arbitrary", Host: "untrusted.invalid", "X-Forwarded-Host": "untrusted.invalid",
    },
    body: JSON.stringify({ field: "body" }),
  }));
  assert.equal(result.status, 429);
  assert.equal(result.headers.get("retry-after"), "60");
  assert.deepEqual(result.headers.getSetCookie(), ["fleetmind_session=expired; HttpOnly", "fleetmind_csrf=expired"]);
  assert.equal(result.headers.get("x-internal-api-key"), null);
  assert.equal(result.headers.get("cache-control"), "no-store");
});

test("bridge rejects backend redirects and oversized bodies", async () => {
  const redirect = route(async () => new Response(null, { status: 302, headers: { Location: "https://untrusted.invalid" } }));
  assert.equal((await redirect.GET(...call("GET", ["auth", "me"]))).status, 502);
  const never = route(() => assert.fail("Oversize body reached FastAPI"));
  assert.equal((await never.POST(...call("POST", ["predict"], { body: "x".repeat(65537) }))).status, 413);
});

test("telemetry preserves cursor and streams the backend response", async () => {
  const upstream = route(async (url, init) => {
    assert.equal(url.pathname, "/api/v1/telemetry/stream");
    assert.equal(init.headers.get("last-event-id"), "515");
    assert.equal(init.headers.get("x-request-id"), "a".repeat(32));
    return new Response("event: ready\n\n", { headers: { "content-type": "text/event-stream" } });
  });
  const result = await upstream.GET(...call("GET", ["telemetry", "stream"], {
    headers: { "Last-Event-ID": "515", "X-Request-ID": "a".repeat(32) },
  }));
  assert.equal(await result.text(), "event: ready\n\n");
  assert.equal(result.headers.get("x-accel-buffering"), "no");
  assert.equal(result.headers.get("x-request-id"), "a".repeat(32));
});

const portfolioRoute = (fetch, origin = "https://demo.onrender.com") =>
  load("app/api/fleetmind/[...path]/route.ts", {
    fetch, process: { env: { NEXT_PUBLIC_FLEETMIND_MODE: "portfolio", FLEETMIND_PORTFOLIO_API_URL: origin } },
  });
const demoCall = (body = "{}") => call("POST", ["demo", "infer"], {
  body, headers: { "Content-Type": "application/json", Cookie: "fleetmind_session=private", Authorization: "Bearer private" },
});

test("portfolio blocks secured API paths and all operations except demo inference", async () => {
  const bridge = portfolioRoute(() => assert.fail("A private path reached the upstream"));
  for (const path of [["auth", "me"], ["copilot", "conversations"], ["predictions"], ["telemetry", "stream"]]) {
    assert.equal((await bridge.GET(...call("GET", path))).status, 404);
  }
  assert.equal((await bridge.POST(...call("POST", ["predict"]))).status, 404);
  assert.equal((await bridge.GET(...call("GET", ["demo", "infer"]))).status, 405);
});

test("portfolio sends only JSON to the exact inference origin and sanitizes its response", async () => {
  const bridge = portfolioRoute((target, options) => {
    assert.equal(target.href, "https://demo.onrender.com/infer");
    assert.equal(options.redirect, "manual");
    assert.equal(options.cache, "no-store");
    assert.equal(options.headers.Cookie, undefined);
    assert.equal(options.headers.Authorization, undefined);
    return Response.json({ failure_score: 0.65, predicted_failure: true, alert_level: "high_priority",
      model_version: "xgboost_v1", internal_field: "private" }, { headers: { "Set-Cookie": "session=private" } });
  });
  const result = await bridge.POST(...demoCall());
  assert.equal(result.status, 200);
  assert.equal((await result.json()).internal_field, undefined);
  assert.equal(result.headers.get("set-cookie"), null);
  assert.equal(result.headers.get("cache-control"), "no-store");
});

test("portfolio retains bounded unavailable and rate limit responses", async () => {
  const noFetch = () => assert.fail("Unconfigured or oversized request reached upstream");
  assert.equal((await portfolioRoute(noFetch, "https://demo.onrender.com.invalid").POST(...demoCall())).status, 503);
  assert.equal((await portfolioRoute(noFetch).POST(...demoCall("x".repeat(2049)))).status, 413);
  const redirect = () => new Response(null, { status: 302, headers: { Location: "https://other.invalid" } });
  assert.equal((await portfolioRoute(redirect).POST(...demoCall())).status, 503);
  const busy = () => Response.json({ detail: "internal" }, { status: 429, headers: { "Retry-After": "22" } });
  const response = await portfolioRoute(busy).POST(...demoCall());
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "22");
  assert.doesNotMatch((await response.json()).detail, /internal/);
});
