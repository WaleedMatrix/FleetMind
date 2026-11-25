"""Run the scripted Copilot suite or an explicit live-provider subset."""

import argparse
import asyncio
import hashlib
import json
import statistics
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from fleetmind.copilot.orchestration import Orchestrator
from fleetmind.copilot.schemas import ChatRequest, ChatResponse
from fleetmind.copilot.settings import Settings
from fleetmind.copilot.tools import REGISTRY
from scripts.copilot_fixtures import (
    FixtureEnvironment,
    FixtureToolExecutor,
    ScriptedProvider,
)
from scripts.evaluate_knowledge import percentiles
from scripts.manage_security import read_password

ROOT = Path(__file__).resolve().parents[1]


def payload(case):
    return ChatRequest(question=case["question"], asset_id=case.get("asset_id"))


def inspect_case(case, result, *, live):
    scripted = [name for round_ in case["rounds"] for name, _ in round_]
    expected = set(scripted)
    seen = set(result.diagnostics.tool_names)
    expected_order = (["get_asset"] if case.get("asset_id") else []) + scripted
    expected_order = [
        name if name in REGISTRY else "unknown"
        for name in expected_order[: case.get("max_tools", 8)]
    ]
    status_ok = result.status == case["status"]
    exact_facts = "\n\n".join(fact.text for fact in result.facts)
    citations = {citation.id for citation in result.citations}
    claimed = {fact.citation.id for fact in result.facts}
    citation_ok = citations == claimed and (
        bool(citations) and result.answer == exact_facts
        if result.status == "answered"
        else not citations
    )
    content_ok = all(
        needle.lower() in result.answer.lower() for needle in case.get("contains", [])
    )
    issue_ok = not case.get("issue") or case["issue"] in result.diagnostics.issues
    return {
        "id": case["id"],
        "status": result.status,
        "status_ok": status_ok,
        "tool_selection_ok": expected <= seen
        if live
        else (expected_order == result.diagnostics.tool_names),
        "expected_abstention": case["status"]
        in {"insufficient_evidence", "clarification_required"},
        "tool_argument_validity": (
            result.diagnostics.valid_tool_arguments / result.diagnostics.tool_count
            if result.diagnostics.tool_count
            else None
        ),
        "citation_integrity": citation_ok,
        "answer_check": status_ok and citation_ok and content_ok and issue_ok,
        "elapsed_ms": result.diagnostics.elapsed_ms,
        "tokens": result.diagnostics.tokens.model_dump()
        if result.diagnostics.tokens
        else None,
        "issues": result.diagnostics.issues,
    }


async def mock_cases(cases):
    fixture = FixtureEnvironment()
    try:
        answers = []
        for case in cases:
            request = payload(case)
            runner = Orchestrator(
                ScriptedProvider(case),
                FixtureToolExecutor(fixture.store, fixture.hits, case),
                Settings(
                    request_timeout=0.02 if case.get("deadline") else 12,
                    max_tools=case.get("max_tools", 8),
                ),
            )
            answer = await runner.chat(request, fixture.context(request))
            answers.append(inspect_case(case, answer, live=False))
        return answers
    finally:
        fixture.engine.dispose()


def live_cases(cases, base_url, username, origin):
    url = urlsplit(base_url)
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"localhost", "127.0.0.1", "::1"}
        or url.username
        or url.password
    ):
        raise ValueError("Use a local FleetMind API URL without credentials.")
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=130, follow_redirects=False) as client:
        login = client.post(
            f"{base_url}/api/v1/auth/login",
            headers={"Origin": origin},
            json={
                "username": username,
                "password": read_password("FleetMind password: "),
            },
        )
        if not login.is_success:
            raise ValueError(f"FleetMind sign-in failed ({login.status_code}).")
        csrf = client.cookies.get("__Host-fleetmind_csrf") or client.cookies.get(
            "fleetmind_csrf"
        )
        client.headers.update({"Origin": origin, "X-FleetMind-CSRF": csrf})
        try:
            status = client.get(f"{base_url}/api/v1/copilot/status")
            status.raise_for_status()
            if not status.json()["configured"] or status.json()["provider"] not in {
                "openai",
                "ollama",
            }:
                raise ValueError(
                    "Configure a hosted or Ollama provider before live evaluation."
                )
            rows = []
            for case in cases:
                if not case.get("live"):
                    continue
                result = client.post(
                    f"{base_url}/api/v1/copilot/chat",
                    json=payload(case).model_dump(mode="json"),
                )
                if result.status_code not in (200, 503, 504):
                    result.raise_for_status()
                rows.append(
                    inspect_case(
                        case, ChatResponse.model_validate(result.json()), live=True
                    )
                )
            return rows
        finally:
            client.post(f"{base_url}/api/v1/auth/logout")


def summarize(rows, *, live):
    argument_rates = [
        row["tool_argument_validity"]
        for row in rows
        if row["tool_argument_validity"] is not None
    ]
    token_rows = [row["tokens"] for row in rows if row["tokens"] is not None]
    rates = {
        key: statistics.mean(row[key] for row in rows)
        for key in (
            "status_ok",
            "tool_selection_ok",
            "citation_integrity",
            "answer_check",
        )
    }
    abstentions = [row["status_ok"] for row in rows if row["expected_abstention"]]
    return {
        "provider_mode": "live" if live else "scripted_mock",
        "tool_metric": "required-tool coverage"
        if live
        else "scripted control-path adherence",
        "cases": len(rows),
        "abstention_status_accuracy": statistics.mean(abstentions)
        if abstentions
        else None,
        "rates": rates,
        "mean_per_case_tool_argument_validity": statistics.mean(argument_rates)
        if argument_rates
        else None,
        "latency_ms": percentiles([row["elapsed_ms"] for row in rows]),
        "token_usage": {
            key: sum(row[key] for row in token_rows) for key in ("input", "output")
        }
        if token_rows
        else None,
        "failures": [row["id"] for row in rows if not row["answer_check"]],
        "per_case": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-api",
        help="Explicitly exercise a configured local API and its real provider",
    )
    parser.add_argument("--output", type=Path, help="A new report file")
    parser.add_argument(
        "--username", help="Engineer or administrator username for live evaluation"
    )
    parser.add_argument(
        "--origin",
        default="http://127.0.0.1:3000",
        help="Trusted browser origin for local live evaluation",
    )
    args = parser.parse_args()
    if args.live_api and not args.username:
        parser.error("--live-api requires --username.")
    source = (ROOT / "docs/copilot/evaluation.json").read_bytes()
    cases = json.loads(source)
    rows = (
        live_cases(cases, args.live_api, args.username, args.origin)
        if args.live_api
        else asyncio.run(mock_cases(cases))
    )
    report = summarize(rows, live=bool(args.live_api))
    report["dataset_sha256"] = hashlib.sha256(source).hexdigest()
    body = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(body)
    else:
        print(body, end="")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
