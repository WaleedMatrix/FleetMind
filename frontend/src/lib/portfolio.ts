import data from "@/data/portfolio.json";
import type { Asset } from "./assets";
import type { Prediction } from "./predictions";
import type { AssessmentEvent } from "./telemetry";

export const portfolio = data;
export const predictions = data.predictions as Prediction[];
const assets = data.assets as Asset[];
const initialCursor = predictions.length - 16;

function matches(row: Prediction, params: URLSearchParams) {
  return (!params.has("asset_id") || row.asset_id === params.get("asset_id"))
    && (!params.has("alert_level") || row.alert_level === params.get("alert_level"))
    && (!params.has("source") || row.source === params.get("source"))
    && (params.get("alerts_only") !== "true" || row.alert_level !== "no_alert");
}

function slice<T>(rows: T[], params: URLSearchParams) {
  const offset = Number(params.get("offset") ?? 0);
  const limit = Number(params.get("limit") ?? 20);
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) {
    return undefined;
  }
  return rows.slice(offset, offset + limit);
}

function telemetryItem(row: Prediction): AssessmentEvent {
  return {
    cursor: String(row.prediction_id), event_id: data.telemetryIds[row.prediction_id - 1],
    observed_at: row.created_at, ingested_at: row.created_at, assessed_at: row.created_at, prediction: row,
  };
}

export function replayBatch(query: string, cursor: number) {
  const filter = new URLSearchParams(query);
  const next = Math.min(cursor + 1, predictions.length);
  const row = predictions[next - 1];
  return {
    cursor: String(next),
    items: row && next > cursor && matches(row, filter) ? [telemetryItem(row)] : [],
    done: next === predictions.length,
  };
}

export function readPortfolio(requestedPath: string): unknown {
  const [path, search] = requestedPath.split("?", 2);
  const params = new URLSearchParams(search);
  if (path === "health") return { status: "ok", model_loaded: true, model_version: data.intelligence.metadata.model_version };
  if (path === "dashboard/summary") return data.summary;
  if (path === "dashboard/trends") {
    return params.get("interval") === "day" ? data.trends.day : data.trends.hour;
  }
  if (path === "predictions") {
    return slice(predictions.filter(row => matches(row, params)).reverse(), params);
  }
  if (path === "model/intelligence") return data.intelligence;
  if (path === "model/health") {
    const key = (params.get("source") ?? "simulated") + ":" + (params.get("hours") ?? "168");
    return Object.hasOwn(data.modelHealth, key) ? data.modelHealth[key as keyof typeof data.modelHealth] : undefined;
  }
  if (path === "telemetry/assessments") {
    const rows = slice(predictions.slice(0, initialCursor).filter(row => matches(row, params)).reverse(), params);
    return rows ? { state: "ready", cursor: String(initialCursor), items: rows.map(telemetryItem) } : undefined;
  }
  if (path === "assets") {
    const query = (params.get("q") ?? "").trim().toLowerCase();
    const kind = params.get("machine_type");
    return slice(assets.filter(item => (!kind || item.machine_type === kind)
      && [item.asset_id, item.display_name, item.location].some(value => value?.toLowerCase().includes(query))), params);
  }
  const assetPath = /^assets\/([A-Za-z0-9_-]+)(?:\/(predictions|summary))?$/.exec(path);
  if (assetPath) {
    const [, id, view] = assetPath;
    const asset = assets.find(item => item.asset_id === id);
    if (!asset || !view) return asset;
    const rows = predictions.filter(row => row.asset_id === id).reverse();
    if (view === "predictions") return slice(rows.filter(row => matches(row, params)), params);
    const summary = data.summaries[id as keyof typeof data.summaries];
    return { ...summary, last_prediction_at: rows[0]?.created_at ?? null };
  }
  const predictionPath = /^predictions\/([1-9][0-9]{0,5})(?:\/(explanation))?$/.exec(path);
  if (predictionPath) {
    const [, id, explanation] = predictionPath;
    return explanation
      ? data.explanations[id as keyof typeof data.explanations]
      : predictions[Number(id) - 1];
  }
}
