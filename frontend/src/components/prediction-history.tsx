"use client";

import { useId, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Database, Loader2, ScanLine, Wrench } from "lucide-react";
import {
  ALERT_INFO, PREDICTIONS_PER_PAGE, predictionLabel, scoreText, timestampLabel,
  type AlertFilter, type Prediction, type PredictionPage,
} from "@/lib/predictions";
import { AlertBadge } from "./alert-badge";
import { PredictionInvestigation } from "./prediction-investigation";

const FILTERS = ["all", "high_priority", "review", "no_alert"] as const;

type PredictionHistoryProps = {
  page: PredictionPage | null;
  filter: AlertFilter;
  offset: number;
  failed: boolean;
  onFilterChange: (filter: AlertFilter) => void;
  onPageChange: (offset: number) => void;
};

type Investigation = { record: Prediction; trigger: HTMLButtonElement | null };

export function PredictionHistory({
  page, filter, offset, failed, onFilterChange, onPageChange,
}: PredictionHistoryProps) {
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const activeFilter = useRef<HTMLButtonElement>(null);
  const headingId = useId();
  const resultsId = useId();
  const awaitingPage = !page && !failed;
  const records = page?.records ?? [];
  const recordCount = records.length;
  const emptyMessage = offset > 0
    ? "No predictions on this page. Go to the previous page to continue."
    : filter === "all" ? "No predictions recorded yet." : "No predictions match this alert filter.";

  return (
    <section className="panel alert-center-history" aria-labelledby={headingId}>
      <div className="panel-heading">
        <div>
          <h3 id={headingId} className="alert-center-history-title">
            <ScanLine size={18} aria-hidden="true" /> Alert Intelligence Center
          </h3>
          <p>Open a prediction to review its original readings and model score.</p>
        </div>
      </div>

      <div className="alert-center-filters" role="group" aria-label="Filter predictions by alert level">
        {FILTERS.map((option) => (
          <button
            key={option}
            ref={option === filter ? activeFilter : null}
            type="button"
            aria-pressed={option === filter}
            aria-controls={resultsId}
            onClick={() => onFilterChange(option)}
          >
            {option !== "all" && (
              <span className="alert-center-filter-dot" style={{ backgroundColor: ALERT_INFO[option].color }} aria-hidden="true" />
            )}
            {option === "all" ? "All alerts" : ALERT_INFO[option].label}
          </button>
        ))}
      </div>

      <div id={resultsId} aria-busy={awaitingPage}>
        {recordCount > 0 ? (
          <table className="history-table alert-center-table" aria-label="Prediction history">
            <thead>
              <tr>
                <th scope="col">Prediction</th>
                <th scope="col" className="alert-center-machine-column">Type</th>
                <th scope="col">Score</th>
                <th scope="col">Alert level</th>
                <th scope="col" className="alert-center-time-column">Recorded</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => {
                const id = predictionLabel(record.prediction_id);
                return (
                  <tr
                    key={record.prediction_id}
                    onClick={(event) => setInvestigation({
                      record,
                      trigger: event.currentTarget.querySelector("button"),
                    })}
                  >
                    <td>
                      <button
                        type="button"
                        className="alert-center-record-button"
                        aria-haspopup="dialog"
                        aria-label={`Investigate prediction ${id}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setInvestigation({ record, trigger: event.currentTarget });
                        }}
                      >
                        {id}<ChevronRight size={14} aria-hidden="true" />
                      </button>
                      <span className="asset-record-context" title={record.asset_id ?? undefined}>
                        {record.asset_id ?? "Unassigned"}
                      </span>
                    </td>
                    <td className="alert-center-machine-column">
                      <span className="machine-indicator"><Wrench size={12} aria-hidden="true" />{record.machine_type}</span>
                    </td>
                    <td className="alert-center-table-score">{scoreText(record.failure_score)}</td>
                    <td><AlertBadge level={record.alert_level} /></td>
                    <td className="table-time alert-center-time-column">
                      <time dateTime={record.created_at}>{timestampLabel(record.created_at)}</time>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="alert-center-empty">
            {awaitingPage ? <Loader2 className="spinning" size={22} aria-hidden="true" /> : <Database size={22} aria-hidden="true" />}
            <span>{awaitingPage ? "Loading predictions…" : !page ? "Prediction history is unavailable." : emptyMessage}</span>
          </div>
        )}
      </div>

      <div className="table-footer alert-center-pagination">
        <span role="status">
          {recordCount > 0 ? `${offset + 1}–${offset + recordCount} · Latest first` : page ? "0 records on this page" : ""}
        </span>
        <nav className="page-actions" aria-label="Prediction history pages">
          <button
            type="button" aria-disabled={offset === 0} aria-label="Previous page"
            onClick={() => { if (offset > 0) onPageChange(offset - PREDICTIONS_PER_PAGE); }}
          ><ChevronLeft size={17} aria-hidden="true" /></button>
          <span>Page {Math.floor(offset / PREDICTIONS_PER_PAGE) + 1}</span>
          <button
            type="button" aria-disabled={!page?.hasNext} aria-label="Next page"
            onClick={() => { if (page?.hasNext) onPageChange(offset + PREDICTIONS_PER_PAGE); }}
          ><ChevronRight size={17} aria-hidden="true" /></button>
        </nav>
      </div>

      <PredictionInvestigation
        selection={investigation}
        focusFallback={activeFilter}
      />
    </section>
  );
}
