"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Activity, BookOpen, BrainCircuit, ChartNoAxesCombined, Copy, Database, ExternalLink, Factory, X } from "lucide-react";
import { assetPath, type Asset, type AssetSummary } from "@/lib/assets";
import type { Citation, Message } from "@/lib/copilot";
import type { ModelIntelligence } from "@/lib/model-intelligence";
import { predictionLabel, READING_SOURCES, scoreText, timestampLabel, type Prediction } from "@/lib/predictions";
import { useFleetMindQuery } from "@/lib/use-fleetmind-query";
import { AlertBadge } from "./alert-badge";
import { PredictionExplanation } from "./prediction-explanation";

const SOURCES = {
  asset: { label: "Asset registry", icon: Factory },
  prediction: { label: "Prediction record", icon: Activity },
  explanation: { label: "SHAP explanation", icon: ChartNoAxesCombined },
  model: { label: "Model evaluation", icon: BrainCircuit },
  knowledge: { label: "Knowledge library", icon: BookOpen },
};

const STATUS = {
  answered: "Grounded response",
  clarification_required: "Clarification needed",
  insufficient_evidence: "Insufficient evidence",
  unavailable: "Provider unavailable",
};

const DIAGNOSTIC_LABELS = new Map([
  ["request_deadline", "Request time limit reached"],
  ["provider_timeout", "Provider time limit reached"],
  ["tool_timeout", "Tool time limit reached"],
  ["tool_round_limit", "Tool planning limit reached"],
  ["tool_budget_exceeded", "Tool call limit reached"],
  ["provider_rate_limited", "Provider rate limit reached"],
  ["knowledge_keyword_fallback", "Knowledge search used keyword matching"],
  ["model_version_unavailable", "Matching explanation model unavailable"],
]);

function SourceContent({ citation }: { citation: Citation }) {
  const { asset_id: assetId, prediction_id: predictionId, document_id: documentId, chunk_id: chunkId } = citation;
  switch (citation.kind) {
    case "asset": return assetId && <AssetSource id={assetId} summary={citation.id.endsWith(":summary")} />;
    case "prediction": return predictionId && <PredictionSource id={predictionId} />;
    case "explanation": return predictionId && <PredictionExplanation predictionId={predictionId} />;
    case "model": return <ModelSource version={citation.id.split(":")[1]} />;
    case "knowledge": return documentId && chunkId && <KnowledgeSource documentId={documentId} chunkId={chunkId} />;
  }
}

function SourceQuery<T>({ path, children }: { path: string; children: (data: T) => React.ReactNode }) {
  const { data, error } = useFleetMindQuery<T>(path);
  if (error) return <p className="copilot-error" role="alert">{error}</p>;
  if (!data) return <p className="copilot-muted" role="status">Loading source…</p>;
  return children(data);
}

function AssetSource({ id, summary }: { id: string; summary: boolean }) {
  return <SourceQuery<Asset> path={assetPath(id)}>{(asset) => <>
    <dl className="copilot-source-fields">
      <div><dt>Registered asset</dt><dd>{asset.display_name}</dd></div>
      <div><dt>Asset ID</dt><dd>{asset.asset_id}</dd></div>
      <div><dt>Machine type</dt><dd>{asset.machine_type}</dd></div>
      <div><dt>Location</dt><dd>{asset.location || "Unspecified"}</dd></div>
    </dl>
    {asset.description && <p>{asset.description}</p>}
    {summary && <SourceQuery<AssetSummary> path={`${assetPath(id)}/summary`}>{(stats) => (
      <dl className="copilot-source-fields">
        <div><dt>Current recorded assessments</dt><dd>{stats.total_predictions}</dd></div>
        <div><dt>High priority</dt><dd>{stats.high_priority_alerts}</dd></div>
        <div><dt>Needs review</dt><dd>{stats.review_alerts}</dd></div>
        <div><dt>Mean uncalibrated score</dt><dd>{stats.average_failure_score === null ? "Unavailable" : scoreText(stats.average_failure_score)}</dd></div>
      </dl>
    )}</SourceQuery>}
    <Link className="copilot-link" href={`/${assetPath(id)}`}>Open asset monitor <ExternalLink size={14} /></Link>
  </>}</SourceQuery>;
}

function PredictionSource({ id }: { id: number }) {
  return <SourceQuery<Prediction> path={`predictions/${id}`}>{(record) => <>
    <AlertBadge level={record.alert_level} />
    <dl className="copilot-source-fields">
      <div><dt>Prediction</dt><dd>{predictionLabel(id)}</dd></div>
      <div><dt>Recorded</dt><dd>{timestampLabel(record.created_at, true)}</dd></div>
      <div><dt>Failure score (uncalibrated)</dt><dd>{scoreText(record.failure_score)}</dd></div>
      <div><dt>Origin</dt><dd>{READING_SOURCES[record.source ?? "unknown"]}</dd></div>
      <div><dt>Asset</dt><dd>{record.asset_id || "Unassigned"}</dd></div>
      <div><dt>Model</dt><dd>{record.model_version}</dd></div>
      <div><dt>Machine type</dt><dd>{record.machine_type}</dd></div>
      <div><dt>Air temperature</dt><dd>{record.air_temperature_k} K</dd></div>
      <div><dt>Process temperature</dt><dd>{record.process_temperature_k} K</dd></div>
      <div><dt>Speed</dt><dd>{record.rotational_speed_rpm} rpm</dd></div>
      <div><dt>Torque</dt><dd>{record.torque_nm} N·m</dd></div>
      <div><dt>Tool wear</dt><dd>{record.tool_wear_min} min</dd></div>
    </dl>
  </>}</SourceQuery>;
}

function ModelSource({ version }: { version: string }) {
  return <SourceQuery<ModelIntelligence> path="model/intelligence">{({ metadata, evaluation }) => metadata.model_version !== version
    ? <p className="copilot-muted">The cited model version is no longer available for inspection.</p> : <>
    <dl className="copilot-source-fields">
      <div><dt>Model version</dt><dd>{metadata.model_version}</dd></div>
      <div><dt>Evaluation dataset</dt><dd>{evaluation?.dataset || "Unavailable"}</dd></div>
      {evaluation && <>
        <div><dt>Test observations</dt><dd>{evaluation.test_observations}</dd></div>
        <div><dt>Average precision</dt><dd>{scoreText(evaluation.average_precision)}</dd></div>
        <div><dt>Recall at primary threshold</dt><dd>{scoreText(evaluation.primary_threshold_results.recall)}</dd></div>
        <div><dt>Precision at primary threshold</dt><dd>{scoreText(evaluation.primary_threshold_results.precision)}</dd></div>
      </>}
    </dl>
    <Link className="copilot-link" href="/model-intelligence">Open Model Intelligence <ExternalLink size={14} /></Link>
  </>}</SourceQuery>;
}

function KnowledgeSource({ documentId, chunkId }: { documentId: string; chunkId: string }) {
  const path = `knowledge/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`;
  return <SourceQuery<{ content: string; section: string; position: number }> path={path}>{(chunk) => <>
    <h3>{chunk.section || `Source excerpt ${chunk.position + 1}`}</h3>
    <p className="copilot-source-text">{chunk.content}</p>
  </>}</SourceQuery>;
}

export function SourceDrawer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  const Icon = SOURCES[citation.kind].icon;
  return <dialog ref={ref} className="copilot-source" aria-labelledby="copilot-source-title"
    onClose={() => { if (!ref.current?.open) onClose(); }}>
    <header>
      <div><span className="copilot-source-kind"><Icon size={15} />{SOURCES[citation.kind].label}</span>
        <h2 id="copilot-source-title">{citation.title}</h2></div>
      <button className="copilot-icon-button" type="button" onClick={() => ref.current?.close()} aria-label="Close source"><X size={20} /></button>
    </header>
    {citation.source_ref && <p className="copilot-source-ref">{citation.source_ref}{citation.section ? ` · ${citation.section}` : ""}</p>}
    <SourceContent citation={citation} />
  </dialog>;
}

export function CopilotEvidence({ message, onInspect }: { message: Message; onInspect: (citation: Citation) => void }) {
  const [copyStatus, setCopyStatus] = useState("");
  const response = message.response;
  if (!response) return null;
  const { diagnostics } = response;
  const issueLabels = [...new Set(diagnostics.issues)].flatMap((issue) => {
    const label = DIAGNOSTIC_LABELS.get(issue);
    return label ? [label] : [];
  });
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopyStatus("Copied");
    } catch {
      setCopyStatus("Clipboard unavailable");
    }
  }
  return <>
    <div className="copilot-answer-heading">
      <strong>{STATUS[response.status]}</strong>
      <button type="button" className="copilot-text-button" onClick={() => void copy()}><Copy size={14} /> Copy response</button>
      <span role="status" className="copilot-muted">{copyStatus}</span>
    </div>
    {response.facts.length ? <ul className="copilot-facts">{response.facts.map((fact) => (
      <li key={fact.id}>
        <p>{fact.text}</p>
        <button className="copilot-link copilot-fact-source" type="button" onClick={() => onInspect(fact.citation)}>
          {fact.citation.title} <ExternalLink size={12} aria-hidden="true" />
        </button>
      </li>
    ))}</ul> : <p className="copilot-source-text">{response.answer}</p>}
    {!!response.citations.length && <ul className="copilot-citations" aria-label="Cited evidence">
      {response.citations.map((citation) => {
        const { icon: Icon, label } = SOURCES[citation.kind];
        return <li key={citation.id}>
          <button type="button" onClick={() => onInspect(citation)}>
            <Icon size={17} aria-hidden="true" />
            <span><small>{label}</small><strong>{citation.title}</strong></span>
            <ExternalLink size={13} aria-hidden="true" />
          </button>
        </li>;
      })}
    </ul>}
    {!!response.next_steps.length && <div className="copilot-review"><strong>Maintenance review</strong>
      <ul>{response.next_steps.map((step) => <li key={step}>{step}</li>)}</ul>
    </div>}
    <details className="copilot-diagnostics">
      <summary><Database size={14} aria-hidden="true" /> Request details and model limits</summary>
      <ul>
        <li>{Math.round(diagnostics.elapsed_ms).toLocaleString()} ms · {diagnostics.tool_count} tool calls · {diagnostics.provider_calls} provider calls</li>
        {message.provider && <li>{message.provider}{message.model ? ` · ${message.model}` : ""}</li>}
        {diagnostics.tokens && <li>{diagnostics.tokens.input} input tokens · {diagnostics.tokens.output} output tokens</li>}
        {issueLabels.map((label) => <li key={label}>{label}</li>)}
        {response.limitations.map((limit) => <li key={limit}>{limit}</li>)}
      </ul>
    </details>
  </>;
}
