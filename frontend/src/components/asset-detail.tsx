"use client";

import { useEngineering } from "@/components/auth-shell";

import { useState } from "react";
import Link from "next/link";
import { copilotHref } from "@/lib/copilot";
import { ArrowLeft, Factory, MapPin, RefreshCw } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { assetPath, type Asset, type AssetSummary } from "@/lib/assets";
import { READING_SOURCES, predictionLabel, scoreText, timestampLabel, type Prediction, type ReadingSource } from "@/lib/predictions";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";
import { AlertBadge } from "./alert-badge";
import { AssetForm } from "./asset-form";
import { AssetPagination } from "./asset-pagination";

const PAGE_SIZE = 10;
const POLL_MS = 30_000;

function ReadingTime({ record }: { record: Prediction }) {
  return <time dateTime={record.created_at}>{timestampLabel(record.created_at, true)}</time>;
}

function ScoreTrend({ readings, pending, failed }: { readings: Prediction[]; pending: boolean; failed: boolean }) {
  const points = [...readings].reverse();
  const byId = new Map(points.map((point) => [point.prediction_id, point]));

  return (
    <div className="panel asset-panel">
      <h2>Failure-score trend</h2>
      <p className="asset-note">Recorded assessments on this page, shown oldest first. Scores are uncalibrated.</p>
      {points.length ? (
        <div className="asset-chart">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 15, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid stroke="#293b50" strokeDasharray="4 5" vertical={false} />
              <XAxis dataKey="prediction_id" tickFormatter={(id) => predictionLabel(id)} minTickGap={26}
                tick={{ fill: "#a2b6c8", fontSize: 11 }} />
              <YAxis domain={[0, 1]} width={38} tick={{ fill: "#a2b6c8", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "#132233", border: "1px solid #3a5167", borderRadius: 10 }}
                labelFormatter={(label) => {
                  const reading = byId.get(Number(label));
                  return reading ? `${timestampLabel(reading.created_at, true)} · ${READING_SOURCES[reading.source ?? "unknown"]}` : "";
                }} />
              <Line type="linear" dataKey="failure_score" name="Model score" stroke="#61dfca" strokeWidth={2.5}
                dot={{ r: 3, fill: "#61dfca" }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : <p className="asset-empty" role="status">
        {failed ? "Trend data is unavailable." : pending ? "Loading trend…" : "No readings to chart on this page."}
      </p>}
    </div>
  );
}

export function AssetDetail({ assetId }: { assetId: string }) {
  const canEngineer = useEngineering();
  const [offset, setOffset] = useState(0);
  const [source, setSource] = useState<ReadingSource | "">("");
  const [revision, setRevision] = useState(0);
  const [editedAsset, setEditedAsset] = useState<Asset | null>(null);
  const path = assetPath(assetId);
  const options = { pollMs: POLL_MS, revision };
  const assetQuery = useFleetMindQuery<Asset>(path, { revision });
  const summary = useFleetMindQuery<AssetSummary>(`${path}/summary`, options);
  const alerts = useFleetMindQuery<Prediction[]>(`${path}/predictions?alerts_only=true&limit=5`, options);
  const params = new URLSearchParams({ limit: String(PAGE_SIZE + 1), offset: String(offset) });
  if (source) params.set("source", source);
  const history = useFleetMindQuery<Prediction[]>(`${path}/predictions?${params}`, options);
  const asset = editedAsset ?? assetQuery.data;
  const records = history.data?.slice(0, PAGE_SIZE) ?? [];
  const stats = summary.data;
  const refresh = () => { setEditedAsset(null); setRevision((value) => value + 1); };

  if (!asset) {
    return (
      <section className="panel asset-panel">
        <Link className="asset-inline-link" href="/assets"><ArrowLeft size={15} aria-hidden="true" /> Asset registry</Link>
        <h1>Asset details</h1>
        {assetQuery.error ? <div className="asset-query-error" role="alert">
          {assetQuery.error}<button className="refresh-button" onClick={refresh}>Retry</button>
        </div> : <p role="status">Loading asset…</p>}
      </section>
    );
  }

  return (
    <>
      <Link className="asset-inline-link" href="/assets"><ArrowLeft size={15} aria-hidden="true" /> Asset registry</Link>
      <header className="page-heading asset-detail-heading">
        <div>
          <p className="asset-identity"><Factory size={16} aria-hidden="true" /> {asset.asset_id} · Type {asset.machine_type}</p>
          <h1>{asset.display_name}</h1>
          {asset.location && <p className="asset-identity"><MapPin size={16} aria-hidden="true" /> {asset.location}</p>}
          {asset.description && <p className="asset-description">{asset.description}</p>}
        </div>
        <button className="refresh-button" onClick={refresh}><RefreshCw size={15} aria-hidden="true" /> Refresh</button>
        {canEngineer && <Link href={copilotHref(asset.asset_id)} className="copilot-link">Investigate with Copilot</Link>}
      </header>

      <section className="panel asset-panel asset-summary" aria-label="Monitoring summary" aria-busy={summary.pending}>
        <h2>Monitoring summary</h2>
        {summary.error && <p className="asset-error" role="alert">{summary.error}</p>}
        {stats ? (
          <dl className="asset-metrics">
            <div><dt>Recorded assessments</dt><dd>{stats.total_predictions}</dd></div>
            <div><dt>High-priority alerts</dt><dd>{stats.high_priority_alerts}</dd></div>
            <div><dt>Needs review</dt><dd>{stats.review_alerts}</dd></div>
            <div><dt>Mean model score</dt><dd>{stats.average_failure_score === null ? "—" : scoreText(stats.average_failure_score)}</dd></div>
            <div><dt>Latest assessment</dt><dd>{stats.last_prediction_at ? timestampLabel(stats.last_prediction_at) : "Awaiting readings"}</dd></div>
          </dl>
        ) : summary.pending && <p className="asset-note" role="status">Loading monitoring summary…</p>}
      </section>

      <div className="asset-monitoring-grid">
        <ScoreTrend readings={records} pending={history.pending} failed={Boolean(history.error)} />
        <section className="panel asset-panel" aria-busy={alerts.pending}>
          <h2>Recent alerts</h2>
          <p className="asset-note">Model classifications for maintenance review.</p>
          {alerts.error && <p className="asset-error" role="alert">{alerts.error}</p>}
          {alerts.data?.length ? (
            <ul className="asset-alert-list">
              {alerts.data.map((record) => (
                <li key={record.prediction_id}>
                  <div><strong>{predictionLabel(record.prediction_id)}</strong><ReadingTime record={record} /></div>
                  <div><AlertBadge level={record.alert_level} /><small>{READING_SOURCES[record.source ?? "unknown"]} · {scoreText(record.failure_score)}</small></div>
                </li>
              ))}
            </ul>
          ) : !alerts.error && <p className="asset-empty" role="status">{alerts.pending ? "Loading alerts…" : "No high-priority or review alerts recorded."}</p>}
        </section>
      </div>

      <section className="panel asset-panel asset-sensor-history">
        <div className="asset-section-heading">
          <div><h2>Recorded sensor history</h2><p className="asset-note">Readings explicitly assigned to this asset, latest first.</p></div>
          <label>Reading source
            <select value={source} onChange={(event) => { setSource(event.target.value as ReadingSource | ""); setOffset(0); }}>
              <option value="">All sources</option>
              {Object.entries(READING_SOURCES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        {history.error && <p className="asset-error" role="alert">{history.error}</p>}
        <div aria-busy={history.pending}>
          {records.length ? (
            <div className="asset-table-scroll" tabIndex={0} role="region" aria-label="Scrollable sensor history">
              <table className="history-table asset-readings-table" aria-label="Sensor readings">
                <thead><tr>
                  <th scope="col">Recorded</th><th scope="col">Source</th><th scope="col">Alert</th>
                  <th scope="col">Score</th><th scope="col">Air (K)</th><th scope="col">Process (K)</th>
                  <th scope="col">Speed (RPM)</th><th scope="col">Torque (N·m)</th><th scope="col">Wear (min)</th>
                </tr></thead>
                <tbody>{records.map((record) => (
                  <tr key={record.prediction_id}>
                    <th scope="row"><ReadingTime record={record} /></th>
                    <td>{READING_SOURCES[record.source ?? "unknown"]}</td>
                    <td><AlertBadge level={record.alert_level} /></td><td>{scoreText(record.failure_score)}</td>
                    <td>{record.air_temperature_k}</td><td>{record.process_temperature_k}</td>
                    <td>{record.rotational_speed_rpm}</td><td>{record.torque_nm}</td><td>{record.tool_wear_min}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : !history.error && <p className="asset-empty" role="status">{history.pending ? "Loading readings…"
            : source ? "No readings match this source." : "No readings recorded for this asset on this page."}</p>}
        </div>
        <AssetPagination offset={offset} size={PAGE_SIZE}
          hasNext={(history.data?.length ?? 0) > PAGE_SIZE} onChange={setOffset} />
      </section>

      {canEngineer && <details className="panel asset-panel asset-edit">
        <summary>Edit asset details</summary>
        <p className="asset-note">Registered {timestampLabel(asset.created_at, true)}. The asset ID and machine type stay fixed.</p>
        <AssetForm asset={asset} onSave={setEditedAsset} />
      </details>}
    </>
  );
}
