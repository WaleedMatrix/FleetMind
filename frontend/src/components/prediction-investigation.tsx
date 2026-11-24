"use client";

import { useId, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import Link from "next/link";
import { BrainCircuit, ClipboardCheck, Gauge, Layers, ScanLine, Thermometer, Timer, Wrench, X } from "lucide-react";
import {
  ALERT_INFO, READING_SOURCES, predictionLabel, scoreText, timestampLabel, type AlertLevel, type Prediction,
} from "@/lib/predictions";
import { assetPath } from "@/lib/assets";
import { AlertBadge } from "./alert-badge";
import { PredictionExplanation } from "./prediction-explanation";

const GUIDANCE = {
  high_priority: {
    title: "Prioritize a qualified review",
    steps: [
      "Flag this assessment for the maintenance team under your site’s escalation procedure.",
      "Verify the captured readings against approved equipment limits and inspect the asset according to site procedures.",
    ],
  },
  review: {
    title: "Verify the reading in context",
    steps: [
      "Check for sensor or operating changes around this assessment.",
      "Compare with the asset’s maintenance history and operating baseline, if available.",
    ],
  },
  no_alert: {
    title: "Continue routine monitoring",
    steps: [
      "Keep the asset on its normal inspection and maintenance schedule.",
      "Follow site procedures if an operator reports unusual behavior or if independent checks indicate a concern.",
    ],
  },
} satisfies Record<AlertLevel, { title: string; steps: string[] }>;

function FailureScore({ score }: { score: number }) {
  const fill = Math.min(1, Math.max(0, score)) * 270;

  return (
    <section className="alert-center-score-panel" aria-label="Failure score">
      <div className="alert-center-gauge">
        <div className="alert-center-gauge-arc" style={{ "--score-sweep": `${fill}deg` } as CSSProperties} aria-hidden="true" />
        <div className="alert-center-gauge-readout">
          <strong>{scoreText(score)}</strong>
          <span>Failure score</span>
        </div>
        <div className="alert-center-gauge-scale" aria-hidden="true"><span>0.000</span><span>1.000</span></div>
      </div>
      <p>Uncalibrated model score on a 0–1 scale. It does not estimate failure probability or time to failure.</p>
    </section>
  );
}

function SensorSnapshot({ record }: { record: Prediction }) {
  const temperatures = [
    { label: "Air temperature", value: record.air_temperature_k },
    { label: "Process temperature", value: record.process_temperature_k },
  ];
  const maxTemperature = Math.max(record.air_temperature_k, record.process_temperature_k);
  const readings = [
    { label: "Machine type", value: record.machine_type, icon: Layers },
    { label: "Rotational speed", value: record.rotational_speed_rpm, unit: "RPM", icon: Gauge },
    { label: "Torque", value: record.torque_nm, unit: "N·m", icon: Wrench },
    { label: "Tool wear", value: record.tool_wear_min, unit: "min", icon: Timer },
  ];

  return (
    <section className="alert-center-drawer-section">
      <h3>Original sensor inputs</h3>
      <div className="alert-center-temperature-panel">
        <div className="alert-center-temperature-title"><Thermometer size={16} aria-hidden="true" /> Temperature comparison</div>
        <dl className="alert-center-temperature-readings">
          {temperatures.map(({ label, value }) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                {value} K
                <span className="alert-center-temperature-track" aria-hidden="true">
                  <span style={{ width: `${maxTemperature > 0 ? (value / maxTemperature) * 100 : 0}%` }} />
                </span>
              </dd>
            </div>
          ))}
        </dl>
        <div className="alert-center-temperature-scale" aria-hidden="true">
          <span>0 K</span><span>{maxTemperature} K</span>
        </div>
      </div>
      <dl className="alert-center-sensor-cards">
        {readings.map(({ label, value, unit, icon: Icon }) => (
          <div key={label}>
            <Icon size={16} aria-hidden="true" />
            <dt>{label}</dt>
            <dd>{value}{unit && <span> {unit}</span>}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

type PredictionInvestigationProps = {
  selection: { record: Prediction; trigger: HTMLButtonElement | null } | null;
  focusFallback: RefObject<HTMLButtonElement | null>;
};

export function PredictionInvestigation({ selection, focusFallback }: PredictionInvestigationProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const explanationId = useId();
  const [explain, setExplain] = useState(false);

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!selection || !dialog || dialog.open) return;

    dialog.showModal();
    dialog.scrollTop = 0;
    closeRef.current?.focus();
  }, [selection]);

  if (!selection) return null;

  const { record, trigger } = selection;
  const guidance = GUIDANCE[record.alert_level];

  return (
    <dialog
      ref={dialogRef}
      data-prediction-investigation
      className="alert-center-drawer"
      style={{ "--alert-accent": ALERT_INFO[record.alert_level].color } as CSSProperties}
      aria-labelledby={titleId}
      onClose={() => {
        if (dialogRef.current?.open) return;
        setExplain(false);
        const returnTarget = trigger?.isConnected ? trigger : focusFallback.current;
        returnTarget?.focus({ preventScroll: true });
      }}
    >
      <header className="alert-center-drawer-header">
        <div>
          <div className="alert-center-drawer-label"><ScanLine size={15} aria-hidden="true" /> Prediction investigation</div>
          <h2 id={titleId}>Assessment {predictionLabel(record.prediction_id)}</h2>
        </div>
        <button
          ref={closeRef}
          type="button"
          className="alert-center-close"
          aria-label="Close investigation"
          onClick={() => dialogRef.current?.close()}
        ><X size={20} aria-hidden="true" /></button>
      </header>

      <div className="alert-center-drawer-body">
        <AlertBadge level={record.alert_level} />
        <dl className="alert-center-metadata">
          <div>
            <dt>Recorded at</dt>
            <dd><time dateTime={record.created_at}>{timestampLabel(record.created_at, true)}</time></dd>
          </div>
          <div>
            <dt>Model version</dt>
            <dd>{record.model_version}</dd>
          </div>
          <div>
            <dt>Asset</dt>
            <dd>{record.asset_id ? <Link className="asset-inline-link" href={`/${assetPath(record.asset_id)}`}>{record.asset_id}</Link> : "Unassigned"}</dd>
          </div>
          <div>
            <dt>Reading source</dt>
            <dd>{READING_SOURCES[record.source ?? "unknown"]}</dd>
          </div>
        </dl>
        <FailureScore score={record.failure_score} />
        <section className="model-local">
          <div className="model-local-heading">
            <h3><BrainCircuit size={17} aria-hidden="true" /> Why this score?</h3>
            <button type="button" className="refresh-button" aria-expanded={explain} aria-controls={explanationId}
              onClick={() => setExplain((open) => !open)}>
              {explain ? "Hide explanation" : "Explain assessment"}
            </button>
          </div>
          <div id={explanationId} hidden={!explain}>
            {explain && <PredictionExplanation key={record.prediction_id} predictionId={record.prediction_id} />}
          </div>
        </section>
        <SensorSnapshot record={record} />
        <section className="alert-center-guidance">
          <h3><ClipboardCheck size={18} aria-hidden="true" /> Suggested maintenance review</h3>
          <strong>{guidance.title}</strong>
          <p>This alert is a model classification. A qualified review is needed to confirm any fault.</p>
          <ul>{guidance.steps.map((step) => <li key={step}>{step}</li>)}</ul>
        </section>
      </div>
    </dialog>
  );
}
