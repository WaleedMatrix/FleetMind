"use client";

import { useState } from "react";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";
import { PORTFOLIO } from "@/lib/profile";
import { marginText, type ExplanationFeature, type PredictionExplanation as Explanation } from "@/lib/model-intelligence";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";

function readingText(feature: ExplanationFeature) {
  const value = feature.derived && typeof feature.value === "number"
    ? Number(feature.value.toFixed(6)) : feature.value;
  return `${value}${feature.unit ? ` ${feature.unit}` : ""}`;
}

function waterfallSteps(features: ExplanationFeature[], baseline: number) {
  let margin = baseline;
  const steps = [];
  for (const feature of features) {
    const end = margin + feature.contribution;
    steps.push({ feature, start: margin, end });
    margin = end;
  }
  return steps;
}

function ExplanationCharts({ data }: { data: Explanation }) {
  const [view, setView] = useState<"contributions" | "waterfall">("contributions");
  const [active, setActive] = useState<string | null>(null);
  const features = [...data.features].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const selected = features.find((item) => item.name === active);
  const maxImpact = Math.max(...features.map(({ contribution }) => Math.abs(contribution)), 0.01);
  const steps = waterfallSteps(features, data.baseline);
  const endpoints = [data.baseline, data.raw_output, ...steps.map(({ end }) => end)];
  const domainMin = Math.min(...endpoints);
  const spread = Math.max(Math.max(...endpoints) - domainMin, 0.01);
  const position = (value: number) => 4 + 92 * (value - domainMin) / spread;

  return (
    <>
      <dl className="model-stat-grid">
        <div><dt>Baseline margin</dt><dd>{marginText(data.baseline)}</dd></div>
        <div><dt>Final raw margin</dt><dd>{marginText(data.raw_output)}</dd></div>
        <div><dt>Saved score</dt><dd>{marginText(data.failure_score)}</dd></div>
      </dl>
      <p className="model-note">{PORTFOLIO && "Precomputed from this simulated reading. "}SHAP contributions add to the raw margin in log-odds units. The model maps that margin to the saved, uncalibrated score.</p>
      <div className="period-switch model-chart-switch" role="group" aria-label="Explanation chart">
        <button type="button" className={view === "contributions" ? "selected" : ""} aria-pressed={view === "contributions"}
          onClick={() => setView("contributions")}>Contributions</button>
        <button type="button" className={view === "waterfall" ? "selected" : ""} aria-pressed={view === "waterfall"}
          onClick={() => setView("waterfall")}>SHAP waterfall</button>
      </div>
      <div className="model-feature-legend">
        <span><ArrowDown size={13} aria-hidden="true" /> Lowers margin</span>
        <span><ArrowUp size={13} aria-hidden="true" /> Raises margin</span>
      </div>
      {view === "waterfall" && <div className="model-waterfall-endpoint">
        <span>Baseline</span><strong>{marginText(data.baseline)}</strong>
        <i aria-hidden="true" style={{ left: `${position(data.baseline)}%` }} />
      </div>}
      <ol className="model-feature-list" aria-label={view === "waterfall" ? "Cumulative SHAP steps" : "Signed feature contributions"}>
        {steps.map(({ feature, start, end }) => {
          const delta = 46 * feature.contribution / maxImpact;
          const left = view === "waterfall" ? position(Math.min(start, end)) : 50 + Math.min(0, delta);
          const width = view === "waterfall" ? Math.abs(position(end) - position(start)) : Math.abs(delta);
          const description = view === "waterfall" ? `Margin ${marginText(start)} to ${marginText(end)}` : "Log-odds contribution";
          return (
            <li key={feature.name}>
              <button type="button" aria-pressed={selected?.name === feature.name} onClick={() => setActive(feature.name)}
                title={`${feature.label}: ${readingText(feature)}. ${description}.`}>
                <span className="model-feature-label">
                  <span>{feature.label}<small>{readingText(feature)}{feature.derived ? " · Derived" : ""}</small></span>
                  <strong className={feature.contribution < 0 ? "model-negative" : "model-positive"}>
                    {marginText(feature.contribution, true)}
                  </strong>
                </span>
                <span className={`model-track ${view === "contributions" ? "model-track-zero" : ""}`} aria-hidden="true">
                  <i className={feature.contribution < 0 ? "model-fill-negative" : "model-fill-positive"}
                    style={{ left: `${left}%`, width: `${width}%` }} />
                </span>
                {view === "waterfall" && <small className="model-step-text">{description}</small>}
              </button>
            </li>
          );
        })}
      </ol>
      {view === "waterfall" && <div className="model-waterfall-endpoint">
        <span>Final raw output</span><strong>{marginText(data.raw_output)}</strong>
        <i aria-hidden="true" style={{ left: `${position(data.raw_output)}%` }} />
      </div>}
      <div className="model-feature-detail" aria-live="polite">
        {selected ? (
          <>
            <strong>{selected.label} · {readingText(selected)}</strong>
            <p>{selected.contribution === 0 ? "This feature had zero attributed impact on the margin."
              : `SHAP attributes a ${marginText(Math.abs(selected.contribution))} log-odds ${selected.contribution < 0 ? "decrease" : "increase"} to this feature.`}</p>
            {selected.derived && <p>Process temperature minus air temperature.</p>}
            {selected.transformed_features.length > 1 && <p>Combines the contributions of all fitted machine-type indicators.</p>}
          </>
        ) : <p>Select a feature to inspect its reading and contribution.</p>}
      </div>
      <p className="model-note">These attributions describe model behavior. They do not establish causes of failure. Maintenance action requires human confirmation.</p>
    </>
  );
}

export function PredictionExplanation({ predictionId }: { predictionId: number }) {
  const [revision, setRevision] = useState(0);
  const { data, pending, error, status } = useFleetMindQuery<Explanation>(
    `predictions/${predictionId}/explanation`, { revision },
  );
  if (pending && !data) return <p className="model-note model-loading" role="status"><Loader2 size={16} aria-hidden="true" /> Computing explanation…</p>;
  if (error) {
    const unavailable = status === 404 || status === 409 || status === 503;
    return <div className="model-message" role="alert">
      <strong>{unavailable ? "Explanation unavailable" : "Could not load explanation"}</strong>
      <p>{error}</p>
      {status !== 409 && status !== 404 && <button type="button" className="refresh-button"
        onClick={() => setRevision((current) => current + 1)}>Retry explanation</button>}
    </div>;
  }
  return data && <ExplanationCharts data={data} />;
}
