"""Render answers exclusively from exact facts collected during this request."""

from pydantic import ValidationError

from fleetmind.copilot.schemas import ChatResponse, FinalSelection

LIMITS = [
    "Stored scores are uncalibrated. SHAP explains model behavior in raw log-odds.",
    "FleetMind has no validated time-to-failure forecast.",
    "A qualified human reviewer must confirm faults and authorize maintenance.",
]
MESSAGES = {
    "insufficient_evidence": "There is too little relevant evidence to answer.",
    "clarification_required": "Provide the exact record ID or narrow the question.",
    "unavailable": "The FleetMind Copilot is temporarily unavailable.",
}


def response(status, diagnostics, *, answer=None, asset_ids=None):
    return ChatResponse(
        status=status,
        answer=answer or MESSAGES[status],
        diagnostics=diagnostics,
        asset_ids=asset_ids or [],
        limitations=LIMITS,
    )


def validate_final(text, facts, evidence, diagnostics):
    try:
        selection = FinalSelection.model_validate_json(text)
    except ValidationError:
        diagnostics.issues.append("invalid_final_response")
        return response("insufficient_evidence", diagnostics)
    if any(key not in facts for key in selection.fact_ids):
        diagnostics.issues.append("invalid_citation")
        return response("insufficient_evidence", diagnostics)
    if selection.status != "answered":
        return response(selection.status, diagnostics)
    selected = [facts[key] for key in dict.fromkeys(selection.fact_ids)]
    if not selected:
        return response("insufficient_evidence", diagnostics)
    citations = {fact.citation.id: fact.citation for fact in selected}
    prediction_ids = sorted(
        {item.prediction_id for item in citations.values() if item.prediction_id}
    )
    asset_ids = {item.asset_id for item in citations.values() if item.asset_id}
    asset_ids.update(
        evidence.prediction_assets[key]
        for key in prediction_ids
        if key in evidence.prediction_assets
    )
    return ChatResponse(
        status="answered",
        answer="\n\n".join(fact.text for fact in selected),
        facts=selected,
        citations=list(citations.values()),
        asset_ids=sorted(asset_ids),
        prediction_ids=prediction_ids,
        diagnostics=diagnostics,
        limitations=LIMITS,
        next_steps=[
            "Confirm maintenance decisions with a qualified reviewer "
            "using approved procedures."
        ]
        if any(
            item.kind in {"prediction", "explanation", "knowledge"}
            for item in citations.values()
        )
        else [],
    )
