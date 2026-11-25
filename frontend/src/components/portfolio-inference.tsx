"use client";

import { useState } from "react";
import { fleetMindRequest } from "@/lib/api";
import { predictions } from "@/lib/portfolio";
import { ALERT_INFO, scoreText, type InferenceResult } from "@/lib/predictions";

const examples = [
  predictions.find(row => row.alert_level === "no_alert"),
  predictions.find(row => row.alert_level === "high_priority"),
].filter(entry => entry !== undefined);

export function PortfolioInference({ available }: { available: boolean }) {
  const [selection, setSelection] = useState(0);
  const [result, setResult] = useState<Omit<InferenceResult, "prediction_id"> | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const example = examples[selection];
  if (!example) return null;
  const reading = {
    machine_type: example.machine_type, air_temperature_k: example.air_temperature_k,
    process_temperature_k: example.process_temperature_k,
    rotational_speed_rpm: example.rotational_speed_rpm, torque_nm: example.torque_nm,
    tool_wear_min: example.tool_wear_min,
  };
  async function evaluate() {
    setBusy(true);
    setResult(null);
    setProblem("");
    try {
      setResult(await fleetMindRequest<Omit<InferenceResult, "prediction_id">>("demo/infer", {
        method: "POST", body: JSON.stringify(reading),
        headers: { "Content-Type": "application/json" },
        signal: AbortSignal.timeout(36_000),
      }));
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Inference is unavailable.");
    } finally {
      setBusy(false);
    }
  }
  return <section className="panel model-panel">
    <h2>Optional live inference</h2>
    <p>Score a simulated reading with the frozen CPU model. The service processes one request at a time and does not save readings.</p>
    <label className="portfolio-select">Simulated input
      <select value={selection} disabled={busy} onChange={event => {
        setSelection(Number(event.target.value));
        setProblem("");
        setResult(null);
      }}>
        {examples.map((entry, index) => <option key={entry.prediction_id} value={index}>
          {ALERT_INFO[entry.alert_level].label} example
        </option>)}
      </select>
    </label>
    <p>Recorded score <strong>{scoreText(example.failure_score)}</strong> · {ALERT_INFO[example.alert_level].label}</p>
    {available ? <button className="security-primary" disabled={busy} onClick={() => { void evaluate(); }}>
      {busy ? "Scoring or waking the service…" : "Score this reading"}
    </button> : <p role="status">This deployment uses recorded scores. Live inference is optional.</p>}
    {problem && <p className="model-message" role="alert">{problem} The recorded score remains available.</p>}
    {result && <p role="status">Live score <strong>{scoreText(result.failure_score)}</strong> · {ALERT_INFO[result.alert_level].label}</p>}
  </section>;
}
