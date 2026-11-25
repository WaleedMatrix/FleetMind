"use client";

import { Activity, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { READING_SOURCES, timestampLabel, type ReadingSource } from "@/lib/predictions";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";

const FEATURES = {
  air_temperature_k: "Air temperature · K",
  process_temperature_k: "Process temperature · K",
  rotational_speed_rpm: "Rotational speed · rpm",
  torque_nm: "Torque · Nm",
  tool_wear_min: "Tool wear · min",
  thermal_gap_k: "Thermal gap · K",
  failure_score: "Uncalibrated failure score",
  machine_type: "Machine type",
  alert_level: "Alert level",
};
type Feature = keyof typeof FEATURES;
type Distribution = {
  key: Feature; edges: number[]; categories: string[]; reference_counts: number[];
  observed_counts: number[]; statistic: "psi" | "js_bits"; value: number | null;
  indicator: "within_threshold" | "notice" | "elevated" | null;
};
type Health = {
  state: "ready" | "insufficient_data" | "unavailable";
  integrity: "verified" | "unverified"; model_version: string; observations: number;
  minimum_observations: number; sample_limit: number; truncated: boolean;
  since: string; as_of: string; comparisons: Distribution[];
  reference: { dataset: string; dataset_sha256: string; sample_size: number; schema_version: number } | null;
};

const sourceLabels: Record<ReadingSource, string> = {
  ...READING_SOURCES, telemetry: "Declared telemetry", unknown: "Unknown provenance",
};
const format = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 5 });
const share = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });
const signals = { within_threshold: "Within screening thresholds", notice: "Review shift", elevated: "Elevated shift" };

function bandLabel(metric: Distribution, index: number) {
  if (metric.categories.length) return metric.categories[index].replaceAll("_", " ");
  const lower = metric.edges[index - 1];
  const upper = metric.edges[index];
  if (lower === undefined && upper === undefined) return "All values";
  if (lower === undefined) return "< " + format.format(upper);
  if (upper === undefined) return "≥ " + format.format(lower);
  return format.format(lower) + " to < " + format.format(upper);
}

function BandShare({ value, actual }: { value: number | null; actual?: boolean }) {
  if (value === null) return <span className="model-health-share">Unavailable</span>;
  return <span className={"model-health-share" + (actual ? " actual" : "")}>
    <span className="model-health-track" aria-hidden="true"><i style={{ width: share.format(value).replaceAll(",", "") }} /></span>
    {share.format(value)}
  </span>;
}

export function ModelHealth() {
  const [source, setSource] = useState<ReadingSource>("telemetry");
  const [hours, setHours] = useState("168");
  const [feature, setFeature] = useState<Feature>("failure_score");
  const [revision, setRevision] = useState(0);
  const { data, error, pending } = useFleetMindQuery<Health>(
    "model/health?source=" + source + "&hours=" + hours, { revision },
  );
  const selected = data?.comparisons.find(metric => metric.key === feature);

  return <section className="panel model-panel model-health" aria-labelledby="model-health-heading">
    <header className="model-health-header">
      <div><h2 id="model-health-heading"><Activity size={19} aria-hidden="true" /> Model health</h2>
        <p>Compare recent assessments with the frozen model&apos;s synthetic AI4I training reference.</p></div>
      <button className="refresh-button" onClick={() => setRevision(n => n + 1)} disabled={pending}>
        <RefreshCw size={15} aria-hidden="true" /> Refresh
      </button>
    </header>
    <div className="model-health-controls">
      <label>Reading source<select value={source} onChange={event => setSource(event.target.value as ReadingSource)}>
        {(Object.keys(sourceLabels) as ReadingSource[]).map(value => <option key={value} value={value}>{sourceLabels[value]}</option>)}
      </select></label>
      <label>Assessment window<select value={hours} onChange={event => setHours(event.target.value)}>
        <option value="24">24 hours</option><option value="168">7 days</option><option value="720">30 days</option>
      </select></label>
      <label>Distribution<select value={feature} onChange={event => setFeature(event.target.value as Feature)}>
        {(Object.entries(FEATURES) as [Feature, string][]).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
    </div>
    {source === "telemetry" && <p>Telemetry origin is declared by the caller.</p>}
    {pending && !data && <p role="status">Loading operational comparisons…</p>}
    {error && <p className="model-message" role="alert">{data ? "Last available comparison. " : ""}{error}</p>}
    {data?.state === "unavailable" && <p className="model-message" role="status">The reference or monitoring storage is unavailable.</p>}
    {data?.reference && <>
      <dl className="model-health-summary">
        <div><dt>Reference</dt><dd>{data.reference.dataset} · {data.reference.sample_size.toLocaleString()} training rows · v{data.reference.schema_version}</dd></div>
        <div><dt>Recent observations</dt><dd>{data.observations.toLocaleString()}{data.truncated ? " sampled · limit reached" : ""}</dd></div>
        <div><dt>Artifact integrity</dt><dd><ShieldCheck size={15} aria-hidden="true" /> {data.integrity === "verified" ? "Frozen artifacts verified" : "Unverified"}</dd></div>
        <div><dt>Updated</dt><dd>{timestampLabel(data.as_of, true)}</dd></div>
      </dl>
      {data.state === "insufficient_data" && <p className="model-message" role="status">
        Drift indicators require {data.minimum_observations} assessments from this source. The distribution shows available counts.
      </p>}
      {selected && <div className="model-health-distribution">
        <div><h3>{FEATURES[feature]}</h3>
          {selected.value !== null && selected.indicator && <p className="model-health-signal" data-indicator={selected.indicator}>
            {signals[selected.indicator]} · {selected.statistic === "psi" ? "PSI" : "JS bits"} {selected.value.toFixed(3)}
          </p>}</div>
        <table>
          <caption className="asset-visually-hidden">Training and operational distribution shares by bin</caption>
          <thead><tr><th scope="col">Bin</th><th scope="col">Training</th><th scope="col">Recent</th></tr></thead>
          <tbody>{selected.reference_counts.map((reference, index) => <tr key={index}>
            <th scope="row">{bandLabel(selected, index)}</th>
            <td><BandShare value={reference / data.reference!.sample_size} /></td>
            <td><BandShare value={data.observations ? selected.observed_counts[index] / data.observations : null} actual /></td>
          </tr>)}</tbody>
        </table>
      </div>}
      <p>Windows use assessment time. The comparison measures distribution changes. Live model quality requires verified failure outcomes.</p>
    </>}
  </section>;
}
