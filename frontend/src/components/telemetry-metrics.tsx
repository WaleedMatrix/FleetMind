"use client";

import { Activity, Clock3, Database, Gauge, RadioTower, Server, Workflow } from "lucide-react";
import { memo, useDeferredValue, type ReactNode } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { timestampLabel } from "@/lib/predictions";
import type { Availability, MetricPoint, Metrics, StorageState } from "@/lib/telemetry";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";

const HEALTH: Record<Availability, string> = {
  available: "Available", unavailable: "Unavailable", stale: "Stale",
  unknown: "Unknown", stopped: "Stopped",
};
const COUNTERS = [
  ["received", "Received"], ["processed", "Assessments saved"], ["committed", "Offsets acknowledged"],
  ["duplicates", "Duplicate deliveries"], ["invalid", "Invalid events"], ["retried_events", "Events retried"],
  ["retry_attempts", "Retry attempts"], ["dead_lettered", "DLQ acknowledgements"],
] as const;

const TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit",
});

export function unavailableText(state: StorageState) {
  return state === "migration_required" ? "Apply the live telemetry migration to enable this view."
    : "Telemetry storage is unavailable.";
}

function valueText(value: number | null | undefined, digits = 0) {
  return value == null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

type Series = { key: Exclude<keyof MetricPoint, "started_at">; name: string; color: string };

const THROUGHPUT: Series[] = [
  { key: "received_per_s", name: "Received", color: "#59cfec" },
  { key: "committed_per_s", name: "Offsets acknowledged", color: "#72e7c9" },
];
const BACKLOG: Series[] = [{ key: "max_worker_lag", name: "Highest reported lag", color: "#f4bc73" }];
const LATENCY: Series[] = [
  { key: "inference_ms", name: "Inference", color: "#72e7c9" },
  { key: "database_ms", name: "Persistence", color: "#59cfec" },
  { key: "observation_to_commit_ms", name: "Observation to commit", color: "#b8a8ff" },
];

const NO_POINTS: MetricPoint[] = [];
const Trend = memo(function Trend({ title, unit, Icon, data, series }: {
  title: string; unit: string; Icon: typeof Activity; data: MetricPoint[]; series: Series[];
}) {
  const hasData = data.some((point) => series.some(({ key }) => point[key] !== null));
  return <section className="panel telemetry-trend" aria-label={title}>
    <div className="telemetry-panel-heading"><div><Icon size={17} /><h2>{title}</h2></div><small>{unit}</small></div>
    {hasData ? <div className="telemetry-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: 0, right: 10, top: 12, bottom: 0 }} accessibilityLayer>
          <CartesianGrid vertical={false} strokeDasharray="4 4" stroke="#284052" />
          <XAxis dataKey="started_at" minTickGap={30} tickFormatter={(v: string) => TIME.format(new Date(v))}
            tick={{ fill: "#a0b7cb", fontSize: 10 }} tickLine={false} axisLine={false} />
          <YAxis width={44} tick={{ fill: "#a0b7cb", fontSize: 10 }} tickLine={false} axisLine={false} />
          <Tooltip labelFormatter={(v) => TIME.format(new Date(String(v)))} contentStyle={{ background: "#142333", border: "1px solid #345066", borderRadius: 8 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map(({ key, name, color }) => <Line key={key} dataKey={key} name={name} stroke={color}
            strokeWidth={2.4} dot={false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div> : <p className="telemetry-chart-empty">No samples for this window.</p>}
  </section>;
});

function KPI({ title, value, caption, icon }: { title: string; value: string; caption: string; icon: ReactNode }) {
  return <div className="panel telemetry-kpi">
    <div>{icon}<span>{title}</span></div><strong>{value}</strong><small>{caption}</small>
  </div>;
}

function Health({ icon, title, state, time }: { icon: ReactNode; title: string; state: Availability; time: string | null }) {
  return <div className="telemetry-health-item">
    <span>{icon}{title}</span><strong data-state={state}><i aria-hidden="true" />{HEALTH[state]}</strong>
    <small>{time ? timestampLabel(time) : "Awaiting first report"}</small>
  </div>;
}

export function TelemetryMetrics({ revision }: { revision: number }) {
  const { data, error, pending } = useFleetMindQuery<Metrics>("telemetry/metrics", { pollMs: 10_000, revision });
  const usable = data?.state === "ready" ? data : null;
  const points = useDeferredValue(usable?.points ?? NO_POINTS);
  const stale = Boolean(error && usable);
  const latestMean = usable?.points.filter((point) => point.inference_ms !== null).at(-1)?.inference_ms;
  const totals = usable?.reported_totals;
  return <>
    {pending && !data && <p className="telemetry-message" role="status">Loading operational metrics…</p>}
    {error && <p className="telemetry-message" role="status">{stale ? "Showing the last received metrics. " : ""}{error}</p>}
    {data && data.state !== "ready" && <p className="telemetry-message" role="status">{unavailableText(data.state)}</p>}
    {usable?.truncated && <p className="telemetry-message">This window reached the diagnostics query limit.</p>}
    <div className="telemetry-kpis" aria-label="Telemetry key metrics">
      <KPI title="Durable assessments" value={valueText(usable?.durable_assessments)} icon={<Database size={17} />}
        caption={usable?.last_assessed_at ? `Last assessment ${timestampLabel(usable.last_assessed_at)}` : "Committed to PostgreSQL"} />
      <KPI title="Offsets acknowledged" value={valueText(totals?.committed)} icon={<Workflow size={17} />}
        caption="Cumulative worker reports" />
      <KPI title="Highest active worker lag" value={valueText(stale ? null : usable?.max_worker_lag)} icon={<Gauge size={17} />}
        caption="Offsets pending in assigned partitions" />
      <KPI title="Mean inference" value={latestMean == null ? "—" : `${valueText(latestMean, 1)} ms`} icon={<Clock3 size={17} />}
        caption="Latest sampled bucket" />
    </div>
    <div className="panel telemetry-health" aria-label="Infrastructure health">
      <Health icon={<Server size={17} />} title="Inference worker" state={stale ? "stale" : usable?.worker ?? "unknown"}
        time={usable?.last_report_at ?? null} />
      <Health icon={<RadioTower size={17} />} title="Event broker" state={stale ? "stale" : usable?.broker ?? "unknown"}
        time={usable?.last_broker_probe_at ?? null} />
      <div className="telemetry-health-item"><span><Database size={17} />Assessment storage</span>
        <strong data-state={error ? "stale" : usable ? "available" : "unknown"}><i aria-hidden="true" />
          {error ? "Unknown" : usable ? "Available" : data ? "Unavailable" : "Checking"}</strong>
        <small>PostgreSQL receipt feed</small></div>
    </div>
    <div className="telemetry-section-heading"><h2>Processing activity</h2><span>Last 5 minutes · 10-second buckets · UTC</span></div>
    <div className="telemetry-charts">
      <Trend title="Event throughput" unit="Events / s" Icon={Activity} data={points} series={THROUGHPUT} />
      <Trend title="Consumer backlog" unit="Offsets" Icon={Gauge} data={points} series={BACKLOG} />
      <Trend title="Processing latency" unit="Mean ms" Icon={Clock3} data={points} series={LATENCY} />
    </div>
    <details className="panel telemetry-counts">
      <summary>Reported delivery totals</summary>
      <p>Aggregated worker checkpoints. Acknowledgements include replayed and rejected deliveries.</p>
      <dl>{COUNTERS.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{valueText(totals?.[key])}</dd></div>)}</dl>
    </details>
  </>;
}
