"""Candidate diversification and conservative lexical evidence admission."""

import re
from itertools import zip_longest

from fleetmind.knowledge.retrieval import search
from fleetmind.knowledge.schemas import Mode, SearchFilters, SearchHit, SearchRequest

STOP = set(
    """a an and are as at be can could did do does for from give have how i in is it
    let make me my of on or say see should show so that the their them this to use
    was what when where which will with would you your before after about using
    need check explain specific represent information mean directly today please
    fleetmind machine equipment system reading readings value values data""".split()
)
INSTRUCTIONS = re.compile(
    r"(?:ignore|override|disregard|forget|bypass)\b.{0,65}"
    r"(?:instruction|policy|prompt|rule|constraint)|"
    r"(?:system prompt|developer message|\[/?INST\]|<\|[^>]+\|>|"
    r"reveal.{0,35}(?:api key|secret|password)|"
    r"(?:you are|act as) (?:the )?(?:assistant|copilot)|"
    r"(?:call|execute|run) (?:the )?(?:tool|shell|command)|"
    r"(?:invent|fabricate) (?:a |the )?(?:citation|record|reading|score))",
    re.IGNORECASE | re.DOTALL,
)
SPECIFIC_ID = re.compile(r"\b[a-z]{2,}[-_][a-z0-9_-]*\d[a-z0-9_-]*\b", re.I)
ASPECTS = (
    (
        {"simulation", "simulate", "simulated", "simulator", "provenance", "telemetry"},
        "simulated readings provenance sensor origin declared telemetry",
    ),
    (
        {"alert", "escalate", "triage", "inspection", "maintenance"},
        "maintenance review alert triage qualified confirmation evidence",
    ),
    (
        {"asset", "registration", "history", "registered"},
        "registered asset monitoring sensor history assigned readings",
    ),
    (
        {"shap", "waterfall", "attribution"},
        "SHAP waterfall signed contribution log odds baseline",
    ),
    (
        {"temperature", "thermal", "kelvin", "sensor"},
        "sensor terminology air process temperature thermal gap",
    ),
)
ALIASES = {
    "simulation": "simulated",
    "simulate": "simulated",
    "simulator": "simulated",
    "synthetic": "simulated",
}


def terms(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", value.lower())
    normalized = {
        word.rstrip("s") for word in words if len(word) > 2 and word not in STOP
    }
    return {ALIASES.get(word, word) for word in normalized}


def is_instruction(value: str) -> bool:
    return bool(INSTRUCTIONS.search(value))


def relevant(question: str, hit: SearchHit) -> bool:
    text = " ".join([hit.citation.title, hit.citation.section, hit.content])
    if is_instruction(text):
        return False
    if any(
        identifier.lower() not in text.lower()
        for identifier in SPECIFIC_ID.findall(question)
    ):
        return False
    anchors = terms(question)
    overlap = anchors & terms(text)
    return bool(anchors) and len(overlap) >= min(2, len(anchors))


def aspect_queries(question: str, proposed: list[str]) -> list[str]:
    aspects = [query for cues, query in ASPECTS if cues & terms(question)]
    # One primary search plus at most two distinct facets, including model proposals.
    candidates = [question[:512], *proposed, *(aspects if len(aspects) > 1 else [])]
    return list(dict.fromkeys(text.strip() for text in candidates if text.strip()))[:3]


def collect_knowledge(
    db,
    question: str,
    proposed: list[str],
    embedder,
    *,
    top_k: int = 5,
    mode: Mode = "hybrid",
    filters: SearchFilters | None = None,
):
    batches = [
        search(
            db,
            SearchRequest(
                query=query,
                top_k=max(top_k, 12),
                mode=mode,
                filters=filters or SearchFilters(),
            ),
            embedder,
            lexical="expanded",
        )
        for query in aspect_queries(question, proposed)
    ]
    batches_hits = [
        [hit for hit in batch.results if relevant(question, hit)] for batch in batches
    ]
    unique = {}
    for row in zip_longest(*batches_hits):
        for hit in row:
            if hit is not None:
                unique.setdefault(hit.citation.chunk_id, hit)
    primary, secondary = [], []
    seen: set[str] = set()
    for hit in unique.values():
        doc = hit.citation.document_id
        (secondary if doc in seen else primary).append(hit)
        seen.add(doc)
    return (primary + secondary)[:top_k], any(
        batch.diagnostics.fallback for batch in batches
    )
