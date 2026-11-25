"use client";

import { useEngineering } from "@/components/auth-shell";

import { useState } from "react";
import Link from "next/link";
import { Activity, ArrowLeft, BrainCircuit, FlaskConical, Radio } from "lucide-react";
import { marginText, type ModelIntelligence as Intelligence } from "@/lib/model-intelligence";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";

const percentage = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });

function GlobalImportance({ report }: { report: Intelligence["global_importance"] }) {
  const [selected, setSelected] = useState<string | null>(null);
  if (!report) return <p className="model-message" role="status">Global feature importance is unavailable for this model.</p>;

  const ranked = [...report.features].sort((a, b) => b.mean_absolute_shap - a.mean_absolute_shap);
  const largest = ranked[0]?.mean_absolute_shap || 1;
  const feature = ranked.find((item) => item.name === selected);
  return (
    <>
      <p className="model-note">Mean absolute SHAP on {report.sample_size.toLocaleString()} sampled training observations. Larger values indicate greater attributed impact on model margins across this sample.</p>
      <ol className="model-feature-list model-global-features" aria-label="Global feature importance">
        {ranked.map((item) => (
          <li key={item.name}>
            <button type="button" aria-pressed={selected === item.name} onClick={() => setSelected(item.name)}
              title={`${item.label}: ${marginText(item.mean_absolute_shap)} mean absolute SHAP log-odds`}>
              <span className="model-feature-label"><span>{item.label}</span><strong>{marginText(item.mean_absolute_shap)}</strong></span>
              <span className="model-track" aria-hidden="true"><i className="model-fill-positive"
                style={{ width: `${100 * item.mean_absolute_shap / largest}%` }} /></span>
            </button>
          </li>
        ))}
      </ol>
      <div className="model-feature-detail" aria-live="polite">
        {feature ? <p><strong>{feature.label}</strong> had a mean absolute contribution of {marginText(feature.mean_absolute_shap)} log-odds on this sample. Magnitudes omit the direction of individual contributions.</p>
          : <p>Select a feature to inspect its mean absolute contribution.</p>}
      </div>
      <p className="model-note model-provenance">{report.method} · SHAP {report.shap_version} · Split seed {report.split_seed} · Sample seed {report.sample_seed}</p>
    </>
  );
}

function ModelEvaluation({ evaluation }: { evaluation: Intelligence["evaluation"] }) {
  if (!evaluation) return <p className="model-message" role="status">A verified evaluation report is unavailable for this model.</p>;
  const operatingPoint = evaluation.primary_threshold_results;
  return (
    <>
      <p className="model-note">{evaluation.dataset} held-out evaluation · {evaluation.test_observations.toLocaleString()} observations · {evaluation.test_failures.toLocaleString()} labeled failures</p>
      <div className="model-ap">
        <span>Average precision</span><strong>{marginText(evaluation.average_precision)}</strong>
        <small>Ranking performance across score thresholds</small>
      </div>
      <p className="model-note">Classification results at a score threshold of {operatingPoint.threshold.toFixed(2)}.</p>
      <dl className="model-stat-grid model-evaluation-grid">
        <div><dt>Precision</dt><dd>{percentage.format(operatingPoint.precision)}</dd></div>
        <div><dt>Recall</dt><dd>{percentage.format(operatingPoint.recall)}</dd></div>
        <div><dt>F1 score</dt><dd>{marginText(operatingPoint.f1)}</dd></div>
        <div><dt>Accuracy</dt><dd>{percentage.format(operatingPoint.accuracy)}</dd></div>
      </dl>
      <dl className="model-confusion">
        <div><dt>True positives</dt><dd>{operatingPoint.true_positive.toLocaleString()}</dd></div>
        <div><dt>False positives</dt><dd>{operatingPoint.false_positive.toLocaleString()}</dd></div>
        <div><dt>False negatives</dt><dd>{operatingPoint.false_negative.toLocaleString()}</dd></div>
        <div><dt>True negatives</dt><dd>{operatingPoint.true_negative.toLocaleString()}</dd></div>
      </dl>
      <p className="model-note model-provenance">Source · reports/final_test_metrics.json</p>
    </>
  );
}

export function ModelIntelligence() {
  const canEngineer = useEngineering();
  const [revision, setRevision] = useState(0);
  const { data, pending, error } = useFleetMindQuery<Intelligence>("model/intelligence", { revision });
  const metadata = data?.metadata;

  return (
    <>
      <header className="topbar model-topbar">
        <Link className="brand" href="/" aria-label="FleetMind dashboard">
          <span className="brand-symbol"><Activity size={21} aria-hidden="true" /></span>
          <strong>FleetMind<span className="brand-dot">.</span></strong>
        </Link>
        <Link className="asset-home-link" href="/"><ArrowLeft size={16} aria-hidden="true" /> Command center</Link>
        {canEngineer && <Link href="/copilot" className="copilot-link">Ask Copilot</Link>}
      </header>
      <main className="content-container model-content">
        <header className="model-hero">
          <div>
            <h1>Model <span>intelligence.</span></h1>
            <p>Explore what influences FleetMind’s assessments and how the frozen model performed on its held-out evaluation.</p>
          </div>
          {metadata && <div className="model-hero-metadata">
            <Radio size={25} aria-hidden="true" />
            <div><strong>{metadata.model_name}</strong><span>{metadata.model_version}</span></div>
          </div>}
        </header>
        {pending && !data && <p className="panel model-panel" role="status">Loading model intelligence…</p>}
        {error && <div className="model-message" role="alert">
          <strong>Model intelligence unavailable</strong><p>{error}</p>
          <button className="refresh-button" onClick={() => setRevision((count) => count + 1)}>Retry</button>
        </div>}
        {data && metadata && (
          <div className="model-dashboard-grid">
            <section className="panel model-panel">
              <h2><BrainCircuit size={19} aria-hidden="true" /> Global feature importance</h2>
              <GlobalImportance report={data.global_importance} />
            </section>
            <section className="panel model-panel">
              <h2><FlaskConical size={19} aria-hidden="true" /> Held-out evaluation</h2>
              <ModelEvaluation evaluation={data.evaluation} />
            </section>
            <section className="panel model-panel">
              <h2>Frozen model configuration</h2>
              <dl className="model-metadata-list">
                <div><dt>Algorithm</dt><dd>{metadata.algorithm}</dd></div>
                <div><dt>Training observations</dt><dd>{metadata.training_observations.toLocaleString()}</dd></div>
                <div><dt>Labeled training failures</dt><dd>{metadata.training_failures.toLocaleString()} ({percentage.format(metadata.training_failures / metadata.training_observations)})</dd></div>
                <div><dt>Positive-class weight</dt><dd>{metadata.scale_pos_weight.toFixed(2)}</dd></div>
                <div><dt>Thermal gap</dt><dd>{metadata.feature_engineering.thermal_gap ? "Process minus air temperature" : "Disabled"}</dd></div>
                <div><dt>Alert score thresholds</dt><dd>{metadata.thresholds.review} review · {metadata.thresholds.high_priority} high priority</dd></div>
                <div><dt>Artifact dependencies</dt><dd>{Object.entries(metadata.dependencies).map(([name, version]) => `${name.replaceAll("_", "-")} ${version}`).join(" · ")}</dd></div>
              </dl>
            </section>
            <section className="panel model-panel model-limitations">
              <h2>Model limitations</h2>
              <ul>
                <li>Synthetic AI4I data supports benchmark evaluation. Performance on real equipment requires independent validation.</li>
                <li>Failure labels are rare in the training data. The model used class weighting.</li>
                <li>Model scores are uncalibrated. SHAP explains model outputs in log-odds units and cannot establish causation.</li>
                <li>FleetMind has no validated time-to-failure forecast. Maintenance decisions require human confirmation.</li>
              </ul>
            </section>
          </div>
        )}
      </main>
    </>
  );
}
