"use client";

import { useLayoutEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import {
  Activity, AlertTriangle, ArrowRight, ArrowUpRight, BarChart3, Bell, BrainCircuit,
  CheckCircle2, CircleDot, Database, Factory,
  Gauge, LayoutDashboard, Loader2, Radio, RefreshCw, ScanLine,
  ShieldCheck, SlidersHorizontal, Sparkles, Thermometer,
  Zap,
} from "lucide-react";
import {
  Area, AreaChart, CartesianGrid, Cell, Line, LineChart, Pie,
  PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { AlertBadge } from "@/components/alert-badge";
import { AssetPicker } from "@/components/asset-picker";
import { PredictionHistory } from "@/components/prediction-history";
import { fleetMindRequest } from "@/lib/api";
import type { Asset } from "@/lib/assets";
import {
  PREDICTIONS_PER_PAGE, scoreText,
  type AlertFilter, type InferenceResult, type Prediction, type PredictionPage, type SensorReading,
} from "@/lib/predictions";

type Interval = "hour" | "day";

type Summary = {
  total_predictions: number;
  high_priority_alerts: number;
  review_alerts: number;
  no_alert_predictions: number;
  average_failure_score: number;
};

type TrendPoint = {
  timestamp: string;
  total_predictions: number;
  high_priority_alerts: number;
  review_alerts: number;
  no_alert_predictions: number;
  average_failure_score: number;
};

type Trends = { interval: Interval; points: TrendPoint[] };

type Health = { status: string; model_loaded: boolean; model_version: string };

const INITIAL_READING: SensorReading = {
  machine_type: "L",
  air_temperature_k: Number.NaN,
  process_temperature_k: Number.NaN,
  rotational_speed_rpm: Number.NaN,
  torque_nm: Number.NaN,
  tool_wear_min: Number.NaN,
};

async function getJSON<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`/api/fleetmind/${path}`, { cache: "no-store", signal });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as {detail?: string};
    throw new Error(detail.detail ?? `API request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function utcLabel(timestamp: string, interval: Interval) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return interval === "day"
    ? date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
    : date.toLocaleString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
}

function StatCard({ label, value, helper, icon, tone }: {
  label: string; value: string; helper: string; icon: ReactNode; tone: string;
}) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-top"><span>{label}</span><span className="stat-icon">{icon}</span></div>
      <div className="stat-value">{value}</div>
      <div className="stat-foot"><span className="stat-marker" />{helper}</div>
    </div>
  );
}

function EmptyChart({ text }: { text: string }) {
  return (
    <div className="empty-chart">
      <div className="empty-orbit"><BarChart3 size={23} /></div>
      <strong>No chart data yet</strong>
      <span>{text}</span>
    </div>
  );
}

function NumericInput({ label, unit, value, onChange, step = 1, min = 0 }: {
  label: string; unit: string; value: number; onChange: (value: number) => void;
  step?: number | "any"; min?: number;
}) {
  return (
    <label className="sensor-field">
      <span>{label}</span>
      <span className="input-shell">
        <input type="number" required min={min} step={step} value={Number.isFinite(value) ? value : ""}
          onChange={(event) => onChange(event.target.valueAsNumber)} />
        <small>{unit}</small>
      </span>
    </label>
  );
}

const CHART_TOOLTIP_STYLE = {
  background: "#131e2c", border: "1px solid #2a3a4b", borderRadius: 12,
  color: "#e8eff7", fontSize: 12, boxShadow: "0 14px 35px #0007",
};

export default function Home() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [trends, setTrends] = useState<Trends | null>(null);
  const [history, setHistory] = useState<PredictionPage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [interval, setIntervalValue] = useState<Interval>("hour");
  const [filter, setFilter] = useState<AlertFilter>("all");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [reading, setReading] = useState<SensorReading>(INITIAL_READING);
  const [asset, setAsset] = useState<Asset | null>(null);
  const [source, setSource] = useState<"manual" | "simulated">("manual");
  const [submitting, setSubmitting] = useState(false);
  const [prediction, setPrediction] = useState<InferenceResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const refreshDashboard = useRef<((replaceInFlight?: boolean) => Promise<void>) | null>(null);

  // Invalidate the previous query as soon as the new selection commits.
  useLayoutEffect(() => {
    let activeRequest: AbortController | null = null;
    // Fetch one extra record so a full final page cannot advertise another page.
    const params = new URLSearchParams({ limit: String(PREDICTIONS_PER_PAGE + 1), offset: String(offset) });
    if (filter !== "all") params.set("alert_level", filter);

    async function load(replaceInFlight = false) {
      if (activeRequest && !replaceInFlight) return;
      activeRequest?.abort();

      const controller = new AbortController();
      const { signal } = controller;
      activeRequest = controller;
      setRefreshing(true);
      try {
        const [nextSummary, nextTrends, nextHistory, nextHealth] = await Promise.all([
          getJSON<Summary>("dashboard/summary", signal),
          getJSON<Trends>(`dashboard/trends?interval=${interval}`, signal),
          getJSON<Prediction[]>(`predictions?${params.toString()}`, signal),
          getJSON<Health>("health", signal),
        ]);
        if (activeRequest !== controller) return;
        setSummary(nextSummary);
        setTrends(nextTrends);
        setHistory({
          filter,
          offset,
          records: nextHistory.slice(0, PREDICTIONS_PER_PAGE),
          hasNext: nextHistory.length > PREDICTIONS_PER_PAGE,
        });
        setHealth(nextHealth);
        setLastSync(new Date());
        setError(null);
      } catch (exception) {
        if (activeRequest !== controller) return;
        // A failed endpoint makes the rest of this batch unnecessary.
        controller.abort();
        setError(exception instanceof Error ? exception.message : "Unable to connect to FleetMind API.");
        setHealth(null);
      } finally {
        if (activeRequest === controller) {
          activeRequest = null;
          setLoading(false);
          setRefreshing(false);
        }
      }
    }

    refreshDashboard.current = load;
    const initialTimer = window.setTimeout(() => { void load(); }, 0);
    const refreshTimer = window.setInterval(() => { void load(); }, 30_000);

    return () => {
      refreshDashboard.current = null;
      activeRequest?.abort();
      activeRequest = null;
      window.clearTimeout(initialTimer);
      window.clearInterval(refreshTimer);
    };
  }, [interval, filter, offset]);

  const points = useMemo(() => (trends?.points ?? []).map((point) => ({
    ...point,
    bucket: utcLabel(point.timestamp, interval),
    score: Number(point.average_failure_score.toFixed(3)),
  })), [trends, interval]);

  const distribution = useMemo(() => summary ? [
    { name: "High priority", value: summary.high_priority_alerts, color: "#ff7788" },
    { name: "Review", value: summary.review_alerts, color: "#f3b766" },
    { name: "No alert", value: summary.no_alert_predictions, color: "#3ee0b1" },
  ].filter((item) => item.value > 0) : [], [summary]);

  const highShare = summary?.total_predictions
    ? `${((summary.high_priority_alerts / summary.total_predictions) * 100).toFixed(1)}% of assessments`
    : "No assessments recorded";

  function updateReading<K extends keyof SensorReading>(key: K, value: SensorReading[K]) {
    setReading((previous) => ({ ...previous, [key]: value }));
    setPrediction(null);
    setSubmitError(null);
  }

  async function runInference(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setPrediction(null);
    try {
      const result = await fleetMindRequest<InferenceResult>("predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...reading, asset_id: asset?.asset_id ?? null, source }),
      });
      setPrediction(result);
      await refreshDashboard.current?.(true);
    } catch (exception) {
      setSubmitError(exception instanceof Error ? exception.message : "Prediction request failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const connected = Boolean(health?.model_loaded && !error);
  const thermalGap = reading.process_temperature_k - reading.air_temperature_k;
  const historyPage = history?.filter === filter && history.offset === offset ? history : null;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-symbol"><Activity size={21} strokeWidth={2.7}/></div><div><strong>FleetMind<span className="brand-dot">.</span></strong><small>INTELLIGENCE SUITE</small></div></div>
        <div className="workspace-tag"><span className="workspace-dot"/>WORKSPACE <span className="workspace-version">/ 01</span></div>
        <div className="nav-section-label">OPERATIONS</div>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          <a className="nav-link active" href="#overview"><LayoutDashboard size={18}/> Command center <span className="active-dot" /></a>
          <a className="nav-link" href="#trends"><Activity size={18}/> Analytics</a>
          <a className="nav-link" href="#activity"><Database size={18} aria-hidden="true"/> Alert Intelligence</a>
          <Link className="nav-link" href="/assets"><Factory size={18} aria-hidden="true" /> Assets</Link>
          <Link className="nav-link" href="/model-intelligence"><BrainCircuit size={18} aria-hidden="true" /> Model Intelligence</Link>
          <a className="nav-link" href="#evaluate"><SlidersHorizontal size={18}/> Inference lab</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-system">
            <div className="system-header"><span className="system-icon"><Radio size={16}/></span><span>System status</span></div>
            <div className="system-state"><span className={`live-dot ${connected ? "" : "offline-dot"}`} />{connected ? "Model serving" : "Connection unavailable"}</div>
            <p>{connected ? health?.model_version : "Start FastAPI to connect"}</p>
          </div>
            <div className="sidebar-footer"><CircleDot size={13}/> Maintenance workspace</div>
        </div>
      </aside>

      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> Operations <span>/</span> <strong>Command center</strong></div>
          <div className="topbar-right"><span className="topbar-tag"><span className="live-dot"/> LOCAL INSTANCE</span><div className="avatar">FM</div></div>
        </header>

        <div className="content-container">
          <div className="page-heading">
            <div><div className="eyebrow"><span className="eyebrow-rule"/> COMMAND CENTER <span className="eyebrow-secondary">/ OVERVIEW</span></div><h1>Operational <span>intelligence.</span></h1><p>Your machine assessment pipeline, monitored in one place.</p></div>
            <div className="heading-controls"><div className={`connection-pill ${connected ? "connected" : "disconnected"}`}><span className="live-dot"/>{connected ? "API connected" : "API disconnected"}</div><button className="refresh-button" onClick={() => { void refreshDashboard.current?.(); }} disabled={refreshing} aria-label="Refresh dashboard"><RefreshCw size={16} className={refreshing ? "spinning" : ""}/><span>Refresh</span></button></div>
          </div>

          {error && <div className="error-banner" role="alert"><AlertTriangle size={18}/><div><strong>Unable to update dashboard</strong><p>{error}. Confirm FastAPI is running on port 8000.</p></div><button onClick={() => { void refreshDashboard.current?.(); }}>Retry <ArrowRight size={14}/></button></div>}

          <section className="hero-panel" aria-label="FleetMind pipeline overview">
            <div className="hero-copy"><div className="hero-kicker"><Sparkles size={14}/> MODEL OPERATIONS / LIVE OVERVIEW</div><h2>Every signal.<br/><span>One clear decision.</span></h2><p>Turn raw sensor readings into prioritized maintenance assessments — and keep an auditable record of every prediction.</p><a href="#evaluate" className="hero-cta">Run an assessment <ArrowUpRight size={17}/></a></div>
            <div className="hero-art" aria-hidden="true"><div className="halo halo-one"/><div className="halo halo-two"/><div className="halo halo-three"/><div className="halo-center"><Activity size={49} strokeWidth={1.4}/></div><div className="signal-node node-one"/><div className="signal-node node-two"/><div className="signal-node node-three"/><div className="hero-art-label label-top">SENSOR INTAKE <span>● LIVE</span></div><div className="hero-art-label label-bottom">MODEL / XGBOOST V1</div></div>
          </section>

          <section className="kpi-section" aria-label="Key metrics">
            <div className="section-head"><div><span className="section-overline">01 / SIGNAL HEALTH</span><h2>System snapshot</h2></div><span className="section-note"><span className="small-live-dot"/> {lastSync ? `Updated ${lastSync.toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"})}` : "Awaiting first sync"}</span></div>
            <div className="stat-grid">
              <StatCard label="Total assessments" value={loading && !summary ? "—" : (summary?.total_predictions ?? 0).toLocaleString()} helper="Predictions stored" icon={<ScanLine size={20}/>} tone="blue"/>
              <StatCard label="High-priority alerts" value={loading && !summary ? "—" : String(summary?.high_priority_alerts ?? 0)} helper={highShare} icon={<AlertTriangle size={20}/>} tone="red"/>
              <StatCard label="Review queue" value={loading && !summary ? "—" : String(summary?.review_alerts ?? 0)} helper="Assessments needing review" icon={<Bell size={20}/>} tone="amber"/>
              <StatCard label="Mean failure score" value={loading && !summary ? "—" : scoreText(summary?.average_failure_score ?? 0)} helper="Raw model score · uncalibrated" icon={<Gauge size={20}/>} tone="mint"/>
            </div>
          </section>

          <section className="analytics-section" id="trends">
            <div className="section-head"><div><span className="section-overline">02 / ANALYTICS</span><h2>Prediction dynamics</h2></div><div className="period-switch" aria-label="Time aggregation"><button onClick={() => setIntervalValue("hour")} className={interval === "hour" ? "selected" : ""}>Hourly</button><button onClick={() => setIntervalValue("day")} className={interval === "day" ? "selected" : ""}>Daily</button></div></div>
            <div className="analytics-grid">
              <div className="panel activity-panel"><div className="panel-heading"><div><div className="panel-label"><Activity size={16}/> THROUGHPUT</div><h3>Assessment activity</h3><p>Prediction volume by UTC time period</p></div><div className="panel-icon"><BarChart3 size={18}/></div></div>
                {points.length === 0 ? <EmptyChart text="Send simulated readings through the API to populate this view."/> : <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><AreaChart data={points} margin={{top:18,right:10,left:-21,bottom:0}}><defs><linearGradient id="activityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#39b9d8" stopOpacity={0.34}/><stop offset="95%" stopColor="#39b9d8" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#263443" strokeDasharray="4 5" vertical={false}/><XAxis dataKey="bucket" tick={{fill:"#7f93a8",fontSize:11}} axisLine={false} tickLine={false}/><YAxis allowDecimals={false} tick={{fill:"#7f93a8",fontSize:11}} axisLine={false} tickLine={false}/><Tooltip contentStyle={CHART_TOOLTIP_STYLE}/><Area type="monotone" dataKey="total_predictions" name="Assessments" stroke="#42cae3" strokeWidth={2.6} fill="url(#activityFill)" dot={{r:3,fill:"#42cae3",stroke:"#0b1522",strokeWidth:2}} activeDot={{r:5}}/></AreaChart></ResponsiveContainer></div>}
              </div>
              <div className="panel score-panel"><div className="panel-heading"><div><div className="panel-label"><Gauge size={16}/> MODEL SIGNAL</div><h3>Score movement</h3><p>Average model score over time</p></div></div>
                <div className="score-high"><span>{summary ? scoreText(summary.average_failure_score) : "—"}</span><small>OVERALL MEAN</small></div>
                {points.length === 0 ? <EmptyChart text="A trend appears as predictions accumulate."/> : <div className="score-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={points} margin={{top:10,right:10,left:-29,bottom:0}}><CartesianGrid stroke="#263443" strokeDasharray="3 6" vertical={false}/><XAxis dataKey="bucket" tick={{fill:"#7f93a8",fontSize:10}} axisLine={false} tickLine={false}/><YAxis domain={[0,1]} tick={{fill:"#7f93a8",fontSize:10}} axisLine={false} tickLine={false}/><Tooltip contentStyle={CHART_TOOLTIP_STYLE}/><Line type="monotone" dataKey="score" name="Mean score" stroke="#b7a4ff" strokeWidth={2.6} dot={{r:3,fill:"#b7a4ff"}} activeDot={{r:5}}/></LineChart></ResponsiveContainer></div>}
                <div className="score-footnote"><ShieldCheck size={15}/> Scores are not calibrated failure probabilities.</div>
              </div>
            </div>
          </section>

          <section className="lower-grid" id="activity">
            <PredictionHistory
              page={historyPage}
              filter={filter}
              offset={offset}
              failed={Boolean(error) && !refreshing}
              onFilterChange={(nextFilter) => {
                setFilter(nextFilter);
                setOffset(0);
              }}
              onPageChange={setOffset}
            />
            <div className="panel distribution-panel"><div className="panel-heading"><div><div className="panel-label"><CircleDot size={16}/> ALERT MIX</div><h3>Alert distribution</h3><p>Across recorded assessments</p></div></div>
              <div className="donut-area">{distribution.length ? <><div className="donut-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={distribution} dataKey="value" innerRadius={69} outerRadius={89} paddingAngle={4} stroke="none" startAngle={90} endAngle={-270}>{distribution.map((slice) => <Cell key={slice.name} fill={slice.color}/>)}</Pie><Tooltip contentStyle={CHART_TOOLTIP_STYLE}/></PieChart></ResponsiveContainer></div><div className="donut-center"><strong>{summary?.total_predictions.toLocaleString()}</strong><span>TOTAL</span></div></> : <div className="donut-empty"><CircleDot size={35}/><span>No assessments yet</span></div>}</div>
              <div className="legend-list">{([
                ["High priority",summary?.high_priority_alerts ?? 0,"#ff7788"],
                ["Needs review",summary?.review_alerts ?? 0,"#f3b766"],
                ["No alert",summary?.no_alert_predictions ?? 0,"#3ee0b1"],
              ] as const).map(([label,value,color])=><div className="legend-row" key={label}><span><i style={{backgroundColor:color}}/>{label}</span><strong>{value.toLocaleString()}</strong></div>)}</div>
            </div>
          </section>

          <section className="inference-section" id="evaluate"><div className="section-head"><div><span className="section-overline">03 / INTERACTIVE INFERENCE</span><h2>Machine assessment lab</h2></div><span className="section-note"><Zap size={14}/> Runs against your saved XGBoost model</span></div>
            <div className="inference-grid"><div className="panel inference-panel"><div className="inference-intro"><div className="inference-icon"><Thermometer size={20}/></div><div><h3>Submit a sensor reading</h3><p>Validate the live inference pipeline and persist the result to PostgreSQL.</p></div></div>
                <form onSubmit={(event) => { void runInference(event); }}>
                  <fieldset className="asset-inference-fields" disabled={submitting}>
                    <legend className="asset-visually-hidden">Assessment inputs</legend>
                    <AssetPicker value={asset} onChange={(selection) => {
                      setAsset(selection);
                      updateReading("machine_type", selection?.machine_type ?? reading.machine_type);
                    }} />
                    <div className="sensor-grid">
                      <label className="sensor-field">
                        <span>Machine type</span>
                        <span className="input-shell select-shell">
                          <select value={reading.machine_type} disabled={Boolean(asset)}
                            onChange={(event) => updateReading("machine_type", event.target.value as SensorReading["machine_type"])}>
                            <option value="L">Low / L</option><option value="M">Medium / M</option><option value="H">High / H</option>
                          </select>
                        </span>
                      </label>
                      <NumericInput label="Air temperature" unit="K" value={reading.air_temperature_k} step="any" min={0.001} onChange={(value) => updateReading("air_temperature_k", value)} />
                      <NumericInput label="Process temperature" unit="K" value={reading.process_temperature_k} step="any" min={0.001} onChange={(value) => updateReading("process_temperature_k", value)} />
                      <NumericInput label="Rotational speed" unit="RPM" value={reading.rotational_speed_rpm} step="any" min={0.001} onChange={(value) => updateReading("rotational_speed_rpm", value)} />
                      <NumericInput label="Torque" unit="Nm" value={reading.torque_nm} step="any" onChange={(value) => updateReading("torque_nm", value)} />
                      <NumericInput label="Tool wear" unit="min" value={reading.tool_wear_min} step="any" onChange={(value) => updateReading("tool_wear_min", value)} />
                      <label className="sensor-field">
                        <span>Reading source</span>
                        <span className="input-shell select-shell">
                          <select value={source} onChange={(event) => {
                            setSource(event.target.value === "simulated" ? "simulated" : "manual");
                            setPrediction(null);
                            setSubmitError(null);
                          }}>
                            <option value="manual">Manual entry</option>
                            <option value="simulated">Simulated</option>
                          </select>
                        </span>
                      </label>
                    </div>
                  </fieldset>
                  <div className="form-actions">
                    <div className="derived-chip"><Thermometer size={15} aria-hidden="true" /> Thermal gap
                      <strong>{Number.isFinite(thermalGap) ? `${thermalGap.toFixed(1)} K` : "—"}</strong>
                    </div>
                    <button type="submit" className="submit-btn" disabled={submitting || !connected}>
                      {submitting ? <Loader2 size={16} className="spinning" /> : <Zap size={16} />}
                      {submitting ? "Evaluating…" : "Run prediction"}<ArrowRight size={14} />
                    </button>
                  </div>
                </form>
                {submitError && <div className="submit-message submit-message-error" role="alert"><AlertTriangle size={17}/>{submitError}</div>}
                {prediction && <div className="prediction-result" role="status"><div><span className="result-label"><CheckCircle2 size={15}/> ASSESSMENT SAVED · #{prediction.prediction_id}</span><div className="result-main">Model score <strong>{scoreText(prediction.failure_score)}</strong></div></div><AlertBadge level={prediction.alert_level}/></div>}
              </div>
              <div className="panel knowledge-panel"><div className="knowledge-top"><div className="knowledge-icon"><ShieldCheck size={26}/></div><span>MODEL CARD / V1</span></div><h3>Know what the score means.</h3><p>FleetMind classifies the current reading against patterns learned from the synthetic AI4I 2020 dataset. The score is <strong>not</strong> a calibrated probability or a forecast of when a machine will fail.</p><div className="threshold-list"><div><i className="thresh-green"/><span>No alert</span><strong>&lt; 0.30</strong></div><div><i className="thresh-amber"/><span>Review</span><strong>0.30–0.60</strong></div><div><i className="thresh-red"/><span>High priority</span><strong>≥ 0.60</strong></div></div><div className="knowledge-footer"><ShieldCheck size={16}/> Human review remains essential for maintenance decisions.</div></div>
            </div>
          </section>
          <footer className="footer"><span>© 2026 FleetMind · Predictive Maintenance Intelligence</span><span>LOCAL DEVELOPMENT <i/> MODEL VERSION: XGBOOST_V1</span></footer>
        </div>
      </main>
    </div>
  );
}
