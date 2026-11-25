"""Canonical facts rendered from validated tool outputs."""

import re

from fleetmind.copilot.relevance import is_instruction, terms
from fleetmind.copilot.schemas import Citation, Fact

_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def label(text: str) -> str:
    return _CONTROL.sub(" ", text).strip()


def prediction_citation(row, kind="prediction"):
    return Citation(
        id=f"{kind}:{row.prediction_id}",
        kind=kind,
        title=f"Prediction #{row.prediction_id}",
        prediction_id=row.prediction_id,
        asset_id=getattr(row, "asset_id", None),
    )


class Evidence:
    def __init__(self):
        self.facts: dict[str, Fact] = {}
        self.asset_matches: set[str] = set()
        self.prediction_assets: dict[int, str] = {}

    def add(self, citation: Citation, *texts: str):
        present = {(fact.citation.id, fact.text) for fact in self.facts.values()}
        used_chars = sum(len(fact.text) for fact in self.facts.values())
        for text in texts:
            text = label(text)
            if (
                10 <= len(text) <= 650
                and len(self.facts) < 80
                and used_chars + len(text) <= 16_000
                and not is_instruction(text)
                and not is_instruction(citation.title)
                and (citation.id, text) not in present
            ):
                key = f"f{len(self.facts) + 1}"
                self.facts[key] = Fact(id=key, text=text, citation=citation)
                used_chars += len(text)
                present.add((citation.id, text))

    def ingest(self, tool: str, result, args, selected: str | None):
        if tool == "search_knowledge":
            for hit in result.hits:
                source = hit.citation
                citation = Citation(
                    id=f"knowledge:{source.chunk_id}",
                    kind="knowledge",
                    title=source.title,
                    document_id=source.document_id,
                    chunk_id=source.chunk_id,
                    source_ref=source.source_ref,
                    section=source.section,
                )
                self.add(
                    citation,
                    *[
                        f"“{sentence}” — {source.title}"
                        for sentence in _SENTENCES.split(hit.content)
                    ],
                )
        elif tool in {"get_asset", "search_assets"}:
            rows = [result] if tool == "get_asset" else result
            if tool == "search_assets" and len(rows) > 1:
                self.asset_matches.update(row.asset_id for row in rows)
            for row in rows:
                citation = Citation(
                    id=f"asset:{row.asset_id}",
                    kind="asset",
                    title=f"Asset {row.asset_id}",
                    asset_id=row.asset_id,
                )
                self.add(
                    citation,
                    f"Asset {row.asset_id} is registered as {row.display_name} "
                    f"(machine type {row.machine_type}).",
                )
                if row.location:
                    self.add(
                        citation,
                        f"Asset {row.asset_id} is registered at {row.location}.",
                    )
        elif tool in {"get_prediction", "get_asset_history", "list_recent_alerts"}:
            rows = [result] if tool == "get_prediction" else result
            for row in rows:
                citation = prediction_citation(row)
                source = {
                    "unknown": "unknown origin",
                    "manual": "manual entry",
                    "simulated": "simulated reading",
                    "telemetry": "caller-declared telemetry",
                }[row.source]
                association = (
                    f"assigned to asset {row.asset_id}"
                    if row.asset_id
                    else "unassigned"
                )
                prefix = f"Prediction #{row.prediction_id}"
                self.add(
                    citation,
                    f"{prefix} has an uncalibrated failure score "
                    f"of {row.failure_score:.6g} and alert level {row.alert_level}.",
                    f"{prefix} is recorded as {source} and {association}.",
                    f"{prefix} records air temperature {row.air_temperature_k:g} K, "
                    f"process temperature {row.process_temperature_k:g} K, "
                    f"rotational speed {row.rotational_speed_rpm:g} RPM, "
                    f"torque {row.torque_nm:g} N·m, and "
                    f"tool wear {row.tool_wear_min:g} min.",
                    f"{prefix} was saved at {row.created_at.isoformat()} "
                    f"with model {row.model_version}.",
                )
                if row.asset_id:
                    self.prediction_assets[row.prediction_id] = row.asset_id
        elif tool == "get_asset_summary":
            asset = args.asset_id or selected
            self.add(
                Citation(
                    id=f"asset:{asset}:summary",
                    kind="asset",
                    asset_id=asset,
                    title=f"Asset {asset} summary",
                ),
                f"Asset {asset} has {result.total_predictions} assigned predictions, "
                f"{result.high_priority_alerts} high-priority alerts and "
                f"{result.review_alerts} review alerts.",
                *(
                    [
                        f"Asset {asset} has an average uncalibrated score of "
                        f"{result.average_failure_score:.6g}."
                    ]
                    if result.average_failure_score is not None
                    else []
                ),
            )
        elif tool == "explain_prediction":
            if selected:
                self.prediction_assets[result.prediction_id] = selected
            citation = prediction_citation(result, "explanation")
            self.add(
                citation,
                f"Prediction #{result.prediction_id} has baseline "
                f"{result.baseline:.6g} and final raw margin "
                f"{result.raw_output:.6g} log-odds.",
            )
            self.add(
                citation,
                *[
                    f"SHAP assigned {feature.label} a contribution of "
                    f"{feature.contribution:+.6g} "
                    f"log-odds for prediction #{result.prediction_id}."
                    for feature in result.features
                ],
            )
        elif tool == "get_model_information":
            meta = result.metadata
            citation = Citation(
                id=f"model:{meta.model_version}",
                kind="model",
                title=f"Frozen model {meta.model_version}",
            )
            self.add(
                citation,
                f"{meta.model_version} is a frozen {meta.algorithm} model "
                f"trained on {meta.training_observations} observations "
                f"with {meta.training_failures} labeled failures.",
            )
            self.add(
                citation,
                f"The frozen review threshold is {meta.thresholds.review:g}, "
                f"the high-priority threshold is {meta.thresholds.high_priority:g}, "
                "and the primary classification threshold is "
                f"{meta.thresholds.primary:g}.",
            )
            if result.evaluation:
                evaluation = result.evaluation
                point = evaluation.primary_threshold_results
                metrics = Citation(
                    id=f"model:{meta.model_version}:evaluation",
                    kind="model",
                    title="Frozen held-out evaluation",
                    source_ref=meta.evaluation_report,
                )
                self.add(
                    metrics,
                    "Held-out average precision was "
                    f"{evaluation.average_precision:.6g} "
                    f"on {evaluation.test_observations} {evaluation.dataset} "
                    "observations.",
                    f"At the {point.threshold:g} threshold, held-out precision was "
                    f"{point.precision:.6g}, recall {point.recall:.6g}, "
                    f"F1 {point.f1:.6g}, "
                    f"and accuracy {point.accuracy:.6g}.",
                    f"The held-out confusion counts were {point.true_positive} "
                    f"true positives, {point.false_positive} false positives, "
                    f"{point.false_negative} false negatives, "
                    f"and {point.true_negative} true negatives.",
                )
            if result.global_importance:
                importance = result.global_importance
                self.add(
                    citation,
                    *[
                        f"{item.label} had a mean absolute SHAP contribution of "
                        f"{item.mean_absolute_shap:.6g} log-odds across "
                        f"{importance.sample_size} training observations."
                        for item in importance.features
                    ],
                )

    def for_question(self, question: str) -> dict[str, Fact]:
        anchors = terms(question)
        # Documents were admitted against the original question at chunk level.
        # Structured facts additionally need a shared question term or reference.
        return {
            key: fact
            for key, fact in self.facts.items()
            if fact.citation.kind == "knowledge" or anchors & terms(fact.text)
        }
