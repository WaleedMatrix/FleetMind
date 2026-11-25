/* Measure the production UI in headless Edge against disposable telemetry fixtures. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";
import { setTimeout as pause } from "node:timers/promises";

const [variant, frontendDirectory, reportPath, widthText] = process.argv.slice(2);
const width = Number(widthText ?? 1440);
const database = new URL(process.env.DATABASE_URL);
assert.match(database.pathname, /^\/fleetmind_m11b_browser[a-z0-9_]*_test$/);
assert.ok(variant && frontendDirectory && reportPath);
assert.ok(width === 1440 || width === 320);
const backend = "http://127.0.0.1:19986";
const frontend = "http://127.0.0.1:19987";
const debugging = "http://127.0.0.1:19988";
const scratch = await mkdtemp(join(tmpdir(), "fleetmind-m11b-edge-"));
const tempPassword = randomBytes(25).toString("base64url");
const topic = "m11b-ui-" + Date.now().toString(36);
const kafka = ["--bootstrap", process.env.FLEETMIND_TELEMETRY_TEST_BOOTSTRAP ?? "127.0.0.1:19097",
  "--topic", topic, "--dead-letter-topic", topic + ".dlq", "--group", topic];
const env = { ...process.env, FLEETMIND_AUTH_INSECURE_LOCAL_HTTP: "1", FLEETMIND_AUTH_ORIGINS: frontend,
  FLEETMIND_API_URL: backend, FLEETMIND_COPILOT_PROVIDER: "mock", FLEETMIND_COPILOT_PREWARM: "0",
  FLEETMIND_BROWSER_FIXTURE_PASSWORD: tempPassword, OMP_NUM_THREADS: "2" };
const children = [];
let log = "";
let socket;
const python = resolve(".venv/Scripts/python.exe");
const edge = process.env.FLEETMIND_EDGE_PATH
  ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
function start(file, args, cwd) {
  const child = spawn(file, args, { cwd, env, windowsHide: true, stdio: "pipe" });
  children.push(child);
  for (const stream of [child.stdout, child.stderr]) stream.on("data", bytes => { log = (log + bytes).slice(-24_000); });
  child.on("error", failure => { log += String(failure); });
  return child;
}
function run(file, args) {
  return new Promise((done, fail) => {
    const child = start(file, args);
    child.once("exit", code => code === 0 ? done() : fail(new Error("Command ended with " + code + " for " + args[1])));
    child.once("error", fail);
  });
}
async function until(check, reason, timeout = 35_000) {
  const deadline = Date.now() + timeout;
  do {
    try { const value = await check(); if (value) return value; } catch {}
    await pause(120);
  } while (Date.now() < deadline);
  throw Error(reason);
}
let next = 0;
const handlers = new Map();
function cdp(method, params = {}) {
  const id = ++next;
  return new Promise((resolve, reject) => {
    handlers.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
    setTimeout(() => { if (handlers.delete(id)) reject(Error("CDP timeout " + method)); }, 9000).unref();
  });
}
async function ev(expression) {
  const result = await cdp("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw Error("Browser expression failed.");
  return result.result.value;
}
async function page(path) {
  await cdp("Page.navigate", { url: frontend + path });
  await cdp("Page.bringToFront");
  await cdp("Emulation.setFocusEmulationEnabled", { enabled: true });
}
async function click(selector) {
  const target = "document.querySelector(" + JSON.stringify(selector) + ")";
  await until(() => ev("Boolean(" + target + ")"), "Missing " + selector);
  await ev(target + ".click()");
}
async function text(fragment) {
  await until(() => ev("document.body?.innerText.includes(" + JSON.stringify(fragment) + ")"), "Missing " + fragment);
}
async function field(name, value) {
  await ev("(()=>{const input=document.querySelector('[name=" + name + "]');"
    + "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,"
    + JSON.stringify(value) + ");input.dispatchEvent(new Event('input',{bubbles:true}));})()");
}
async function auth(route, options) {
  const response = await fetch(backend + "/api/v1/" + route, options);
  assert.ok(response.ok, route + " HTTP " + response.status);
  return response;
}
async function produce(count, rate) {
  return run(python, ["-m", "scripts.produce_telemetry", ...kafka,
    "--asset", "browser-press", "--count", String(count), "--rate", String(rate)]);
}
async function stats() {
  return Object.fromEntries((await cdp("Performance.getMetrics")).metrics.map(m => [m.name, m.value]));
}
async function startMeasurement() {
  await ev("window.fleetmindLongTasks=[];window.fleetmindObserver=new PerformanceObserver(list=>window.fleetmindLongTasks.push(...list.getEntries().map(task=>task.duration)));window.fleetmindObserver.observe({type:'longtask'});true");
  return { ranAt: performance.now(), cpu: (await stats()).TaskDuration };
}
async function stopMeasurement(start) {
  const long = await ev("window.fleetmindObserver.disconnect();window.fleetmindLongTasks");
  const current = await stats();
  return {
    seconds: (performance.now() - start.ranAt) / 1000,
    renderer_task_ms: (current.TaskDuration - start.cpu) * 1000,
    js_heap_mib: current.JSHeapUsedSize / 1024 ** 2,
    long_tasks_ms: long, long_task_count: long.length,
  };
}

try {
  await run(python, ["-m", "alembic", "upgrade", "head"]);
  await run(python, ["-m", "scripts.seed_monitoring_browser"]);
  await run(python, ["-m", "scripts.telemetry_worker", ...kafka, "--create-topics"]);
  start(python, ["-m", "scripts.telemetry_worker", ...kafka]);
  start(python, ["-m", "uvicorn", "fleetmind.api.main:app", "--port", "19986", "--no-access-log"]);
  start(process.execPath, [resolve(frontendDirectory, "node_modules/next/dist/bin/next"),
    "start", "-H", "127.0.0.1", "-p", "19987"], resolve(frontendDirectory));
  await until(async () => (await fetch(backend + "/health")).ok, "API not ready");
  await until(async () => (await fetch(frontend + "/login")).ok, "Frontend not ready");

  const key = await auth("auth/login", { method:"POST",
    headers:{ Origin: frontend, "Content-Type": "application/json" },
    body:JSON.stringify({ username:"browser-bench", password:tempPassword }) });
  const cookie = key.headers.getSetCookie().map(entry=>entry.split(";")[0]).join("; ");
  async function durable() {
    return (await (await auth("telemetry/metrics", { headers: { Cookie: cookie } })).json()).durable_assessments;
  }
  const initial = await durable();
  await produce(60, 30);
  await until(async () => await durable() >= initial + 60, "Baseline telemetry did not commit");

  start(edge, ["--headless=new", "--no-first-run", "--disable-gpu", "--remote-debugging-port=19988",
    "--user-data-dir=" + scratch, "about:blank"]);
  const browser = await until(async () => (await (await fetch(debugging + "/json/list")).json()).find(tab=>tab.type==="page"), "Edge debugger not ready");
  socket = new WebSocket(browser.webSocketDebuggerUrl);
  socket.addEventListener("message", event=>{
    const result = JSON.parse(event.data);
    const pending = handlers.get(result.id);
    if (pending) {
      handlers.delete(result.id);
      if (result.error) pending.reject(Error(result.error.message));
      else pending.resolve(result.result);
    }
  });
  await new Promise((ready, fail)=>{ socket.addEventListener("open", ready, {once:true}); socket.addEventListener("error", fail, {once:true}); });
  await cdp("Page.enable");
  await cdp("Performance.enable");
  await cdp("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
  await page("/telemetry");
  await text("Sign in");
  await field("username", "browser-bench");
  await field("password", tempPassword);
  await click("form button");
  await text("Live assessments");
  await until(() => ev("document.querySelectorAll('.telemetry-feed-table tbody tr').length >= 50"), "Existing feed did not render");
  await pause(700);
  const firstCursor = await ev("document.querySelector('.telemetry-feed-table tbody tr').dataset.cursor");
  const telemetry = await startMeasurement();
  const workload = 240;
  await produce(workload, 50);
  const finalCursor = (BigInt(firstCursor) + BigInt(workload)).toString();
  await until(() => ev("document.querySelector('.telemetry-feed-table tbody tr')?.dataset.cursor === " + JSON.stringify(finalCursor)), "Feed cursor did not reach the last durable commit");
  await pause(1200);
  const stream = await stopMeasurement(telemetry);
  stream.received_assessments = workload;
  stream.visible_rows = await ev("document.querySelectorAll('.telemetry-feed-table tbody tr').length");
  assert.ok(stream.visible_rows <= 60);
  await click(".telemetry-record");
  await text("Prediction investigation");
  await cdp("Input.dispatchKeyEvent", {type:"keyDown", key:"Escape", code:"Escape", windowsVirtualKeyCode:27});
  await cdp("Input.dispatchKeyEvent", {type:"keyUp", key:"Escape", code:"Escape", windowsVirtualKeyCode:27});
  await until(() => ev("!document.querySelector('dialog[open]')"), "Escape did not close the investigation");
  await page("/");
  await until(() => ev("Boolean(document.querySelector('.connection-pill.connected'))"), "Dashboard API did not connect");
  const refresh = await startMeasurement();
  await click('[aria-label="Refresh dashboard"]');
  await until(() => ev("!document.querySelector('[aria-label=\"Refresh dashboard\"]').disabled"), "Dashboard refresh did not finish");
  await pause(450);
  const dashboard = await stopMeasurement(refresh);

  if (variant !== "baseline") {
    await page("/model-intelligence");
    await text("Model health");
    await text("Drift indicators require");
    await ev("(()=>{const select=document.querySelector('.model-health select');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(select,'simulated');select.dispatchEvent(new Event('change',{bubbles:true}));return true;})()");
    await until(() => ev("Boolean(document.querySelector('.model-health-signal'))"), "Simulated comparisons did not render");
    assert.ok(await ev("document.documentElement.scrollWidth <= innerWidth + 1"), "Model Health has horizontal overflow");
  }
  const report = { variant, viewport_px: width, worker_count: 1, preloaded_assessments: 60,
    producer_target_rate_per_second: 50, telemetry:stream, dashboard_refresh:dashboard,
    investigation_keyboard_check:true, model_health_check:variant !== "baseline" };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", {flag:"wx"});
  console.log(JSON.stringify(report));
} catch (failure) {
  console.error(failure.message);
  console.error(log.slice(-4000));
  process.exitCode = 1;
} finally {
  socket?.close();
  for (const child of children.reverse()) child.kill();
}
