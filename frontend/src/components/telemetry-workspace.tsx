"use client";

import { useEngineering } from "@/components/auth-shell";

import Link from "next/link";
import { memo, startTransition, useCallback, useEffect, useRef, useState } from "react";
import { Activity, ArrowLeft, ArrowUpRight, Factory, Pause, Play, Radio, RefreshCw, ShieldAlert, Zap } from "lucide-react";
import type { Asset } from "@/lib/assets";
import {
  FEED_LIMIT, followTelemetry, mergeAssessments, telemetryQuery, type AssessmentEvent,
  type Connection, type DeadLetters, type Snapshot,
} from "@/lib/telemetry";
import { ALERT_INFO, predictionLabel, READING_SOURCES, scoreText, timestampLabel, type AlertFilter } from "@/lib/predictions";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";
import { AlertBadge } from "./alert-badge";
import { AssetPicker } from "./asset-picker";
import { PredictionInvestigation } from "./prediction-investigation";
import { TelemetryMetrics, unavailableText } from "./telemetry-metrics";

const CONNECTION: Record<Connection, string> = {
  connecting: "Connecting", live: "Live assessments", reconnecting: "Reconnecting",
  paused: "Feed paused", unavailable: "Live feed unavailable",
};

const CATEGORIES = {
  invalid_payload: "Invalid payload", unsupported_version: "Unsupported version",
  partition_key_mismatch: "Partition key mismatch", missing_asset: "Missing asset",
  machine_type_mismatch: "Machine type mismatch", event_id_conflict: "Event ID conflict",
};

type Selection = { record: AssessmentEvent["prediction"]; trigger: HTMLButtonElement; telemetry: AssessmentEvent };

const AssessmentRow = memo(function AssessmentRow({ item, onSelect }: {
  item: AssessmentEvent; onSelect: (selection: Selection) => void;
}) {
  const record = item.prediction;
  return <tr data-event-id={item.event_id} data-cursor={item.cursor}>
    <td><button type="button" className="telemetry-record" onClick={(event) => onSelect({
      record, trigger: event.currentTarget, telemetry: item,
    })}><span>{predictionLabel(record.prediction_id)} <ArrowUpRight size={13} aria-hidden="true" /></span>
      <small>{record.asset_id || "Unassigned"}</small></button></td>
    <td>{READING_SOURCES[record.source ?? "unknown"]}</td>
    <td className="telemetry-score">{scoreText(record.failure_score)}</td>
    <td><AlertBadge level={record.alert_level} /></td>
    <td><time dateTime={item.assessed_at}>{timestampLabel(item.assessed_at)}</time></td>
  </tr>;
});

function AssessmentFeed({ query, snapshot, paused, reconnect, onConnection, onReset, onSelect }: {
  query: string; snapshot: Snapshot; paused: boolean; reconnect: number;
  onConnection: (state: Connection, detail?: string) => void; onReset: () => void;
  onSelect: (selection: Selection) => void;
}) {
  const [items, setItems] = useState(snapshot.items);
  const applied = useRef(snapshot.cursor ?? "0");

  useEffect(() => {
    if (paused) return;
    return followTelemetry({
      cursor: applied.current, query, onStatus: onConnection, onReset,
      onBatch(batch, cursor) {
        applied.current = cursor;
        if (batch.length) startTransition(() => setItems((current) => mergeAssessments(current, batch)));
      },
    });
  }, [query, paused, reconnect, onConnection, onReset]);

  if (!items.length) return <p className="telemetry-feed-empty">No committed assessments match these filters yet.</p>;
  return <div className="telemetry-feed-scroll">
    <table className="telemetry-feed-table" aria-label="Committed telemetry assessments">
      <thead><tr><th scope="col">Assessment / asset</th><th scope="col">Source</th>
        <th scope="col">Score</th><th scope="col">Alert level</th><th scope="col">Assessed at</th></tr></thead>
      <tbody>{items.map((item) => <AssessmentRow key={item.event_id} item={item} onSelect={onSelect} />)}</tbody>
    </table>
  </div>;
}

function DeadLetterPanel({ revision }: { revision: number }) {
  const { data, error, pending } = useFleetMindQuery<DeadLetters>("telemetry/dead-letters?limit=20", { pollMs: 10_000, revision });
  return <section className="panel telemetry-dead" aria-labelledby="telemetry-dead-title">
    <div className="telemetry-panel-heading"><div><ShieldAlert size={19} /><h2 id="telemetry-dead-title">Dead-letter reports</h2></div><small>Last 24 hours</small></div>
    {error && <p className="telemetry-message" role="status">{error}</p>}
    {pending && !data && <p className="telemetry-message" role="status">Loading rejection reports…</p>}
    {data && data.state !== "ready" ? <p className="telemetry-message">{unavailableText(data.state)}</p>
      : data?.items.length ? <ul className="telemetry-dead-list">{data.items.map((item) =>
        <li key={`${item.original_topic}:${item.original_partition}:${item.original_offset}`}>
          <strong>{CATEGORIES[item.category]}</strong><time dateTime={item.rejected_at}>{timestampLabel(item.rejected_at, true)}</time>
          <code>{item.original_topic} · partition {item.original_partition} · offset {item.original_offset}</code>
          <span>{item.event_id ? `Event ${item.event_id}` : "Event ID unavailable"}</span>
        </li>
      )}</ul> : data && <p className="telemetry-message">{data.last_report_at
        ? "No recent dead letters have been reported." : "Awaiting the first worker report."}</p>}
  </section>;
}

export function TelemetryWorkspace() {
  const canEngineer = useEngineering();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [severity, setSeverity] = useState<AlertFilter>("all");
  const [paused, setPaused] = useState(false);
  const [revision, setRevision] = useState(0);
  const [reconnect, setReconnect] = useState(0);
  const [connection, setConnection] = useState<{ state: Connection; detail?: string }>({ state: "connecting" });
  const [selected, setSelected] = useState<Selection | null>(null);
  const focusFallback = useRef<HTMLButtonElement>(null);
  const query = telemetryQuery(asset?.asset_id ?? "", severity);
  const snapshot = useFleetMindQuery<Snapshot>(`telemetry/assessments?limit=50&revision=${revision}&${query}`);
  const reset = useCallback(() => setRevision((count) => count + 1), []);
  const setStatus = useCallback((state: Connection, detail?: string) => setConnection({ state, detail }), []);
  const readySnapshot = snapshot.data?.state === "ready" ? snapshot.data : null;
  const available = readySnapshot !== null;
  const state = paused ? "paused" : snapshot.error || (snapshot.data && !available)
    ? "unavailable" : available ? connection.state : "connecting";

  function retry() {
    setReconnect((count) => count + 1);
    if (!available) reset();
  }

  return <main className="telemetry-shell">
    <header className="topbar telemetry-topbar">
      <Link className="brand" href="/" aria-label="FleetMind dashboard">
        <span className="brand-symbol"><Zap size={20} aria-hidden="true" /></span><strong>FleetMind<span className="brand-dot">.</span></strong>
      </Link>
      <nav aria-label="FleetMind">
        <Link href="/"><ArrowLeft size={16} aria-hidden="true" /> Dashboard</Link>
        <Link href="/assets"><Factory size={16} aria-hidden="true" /> Assets</Link>
        {canEngineer && <Link href="/copilot">Copilot</Link>}
      </nav>
    </header>
    <div className="telemetry-container">
      <header className="telemetry-heading">
        <div>
          <h1>Telemetry <span>Command Center</span></h1>
          <p>Committed assessments and the infrastructure that processes them.</p>
        </div>
        <div className="telemetry-actions">
          <span className="telemetry-connection" role="status" data-state={state}>
            <Radio size={16} aria-hidden="true" />{CONNECTION[state]}
          </span>
          <button type="button" className="telemetry-button" onClick={() => setPaused(!paused)}>
            {paused ? <Play size={16} aria-hidden="true" /> : <Pause size={16} aria-hidden="true" />}
            {paused ? "Resume feed" : "Pause feed"}
          </button>
          <button type="button" className="telemetry-button" ref={focusFallback} onClick={retry} disabled={paused}>
            <RefreshCw size={16} aria-hidden="true" /> Reconnect
          </button>
        </div>
      </header>
      {connection.detail && !paused && available && <p className="telemetry-message" role="status">{connection.detail}</p>}
      <TelemetryMetrics revision={reconnect} />
      <div className="telemetry-bottom">
        <section className="panel telemetry-feed" aria-labelledby="telemetry-feed-title">
          <div className="telemetry-panel-heading"><div><Activity size={19} /><h2 id="telemetry-feed-title">Assessment feed</h2></div>
            <small>Up to {FEED_LIMIT} shown</small></div>
          <div className="telemetry-controls">
            <details><summary>{asset?.display_name ?? "All assets"}</summary>
              <AssetPicker value={asset} onChange={(value) => { setAsset(value); setStatus("connecting"); }} />
            </details>
            <label>Severity
              <select value={severity} onChange={(event) => { setSeverity(event.target.value as AlertFilter); setStatus("connecting"); }}>
                <option value="all">All alerts</option>
                {Object.entries(ALERT_INFO).map(([key, info]) => <option value={key} key={key}>{info.label}</option>)}
              </select>
            </label>
          </div>
          {snapshot.error && <p className="telemetry-message" role="alert">{snapshot.error}</p>}
          {snapshot.data && snapshot.data.state !== "ready" && <p className="telemetry-message">{unavailableText(snapshot.data.state)}</p>}
          {snapshot.pending && !snapshot.data && <p className="telemetry-message" role="status">Loading committed assessments…</p>}
          {readySnapshot && <AssessmentFeed key={`${query}:${revision}`} query={query} snapshot={readySnapshot} paused={paused}
            reconnect={reconnect} onConnection={setStatus} onReset={reset} onSelect={setSelected} />}
        </section>
        {canEngineer && <DeadLetterPanel revision={reconnect} />}
      </div>
    </div>
    <PredictionInvestigation selection={selected} focusFallback={focusFallback} />
  </main>;
}
