export type AlertLevel = "high_priority" | "review" | "no_alert";
export type AlertFilter = "all" | AlertLevel;
export const READING_SOURCES = {
  unknown: "Unknown origin",
  manual: "Manual entry",
  simulated: "Simulated",
  telemetry: "Telemetry (declared)",
} as const;
export type ReadingSource = keyof typeof READING_SOURCES;

export const PREDICTIONS_PER_PAGE = 8;

export const ALERT_INFO = {
  high_priority: { label: "High priority", tone: "critical", color: "#ff7788" },
  review: { label: "Needs review", tone: "warning", color: "#f3b766" },
  no_alert: { label: "No alert", tone: "healthy", color: "#3ee0b1" },
} satisfies Record<AlertLevel, { label: string; tone: string; color: string }>;

export type SensorReading = {
  machine_type: "L" | "M" | "H";
  air_temperature_k: number;
  process_temperature_k: number;
  rotational_speed_rpm: number;
  torque_nm: number;
  tool_wear_min: number;
};

export type InferenceResult = {
  prediction_id: number;
  model_version: string;
  failure_score: number;
  predicted_failure: boolean;
  alert_level: AlertLevel;
  asset_id?: string | null;
  source?: ReadingSource;
};

export type Prediction = SensorReading & InferenceResult & { created_at: string };

export type PredictionPage = {
  filter: AlertFilter;
  offset: number;
  records: Prediction[];
  hasNext: boolean;
};

export function predictionLabel(id: number) {
  return `#${String(id).padStart(5, "0")}`;
}

const compactTimestamp = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
});
const fullTimestamp = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium", timeStyle: "medium", timeZone: "UTC",
});

export function timestampLabel(timestamp: string, full = false) {
  // Prediction timestamps are stored in UTC, including records serialized without an offset.
  const zone = /(?:Z|[+-]\d{2}:\d{2})$/i;
  const date = new Date(zone.test(timestamp) ? timestamp : `${timestamp}Z`);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return `${(full ? fullTimestamp : compactTimestamp).format(date)} UTC`;
}

export function scoreText(value: number) {
  return Number.isFinite(value) ? value.toFixed(3) : "—";
}
