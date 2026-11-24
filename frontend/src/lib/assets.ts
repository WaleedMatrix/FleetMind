import type { SensorReading } from "./predictions";

export type MachineType = SensorReading["machine_type"];

export type Asset = {
  asset_id: string;
  display_name: string;
  machine_type: MachineType;
  location: string | null;
  description: string | null;
  created_at: string;
};

export type AssetSummary = {
  total_predictions: number;
  high_priority_alerts: number;
  review_alerts: number;
  no_alert_predictions: number;
  average_failure_score: number | null;
  last_prediction_at: string | null;
};

export function assetPath(assetId: string) {
  return `assets/${encodeURIComponent(assetId)}`;
}

export function assetSearchPath(query: string, type: MachineType | "", offset: number, limit: number) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (query.trim()) params.set("q", query.trim());
  if (type) params.set("machine_type", type);
  return `assets?${params}`;
}
