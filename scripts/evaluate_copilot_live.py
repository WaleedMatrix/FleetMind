"""Run an opt-in real-provider benchmark using synthetic FleetMind fixtures."""

import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from math import isfinite
from pathlib import Path
from secrets import token_urlsafe
from time import perf_counter
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import Field, TypeAdapter
from sqlalchemy.orm import sessionmaker

from fleetmind.api.copilot import router as copilot_router
from fleetmind.api.copilot_conversations import conversation_store
from fleetmind.api.copilot_conversations import router as conversations_router
from fleetmind.api.security import router as security_router
from fleetmind.copilot.conversations import ConversationStore
from fleetmind.copilot.orchestration import Orchestrator
from fleetmind.copilot.providers import (
    ChatCompletionsProvider,
    ProviderError,
    make_provider,
)
from fleetmind.copilot.schemas import ChatRequest, Status
from fleetmind.copilot.settings import Settings
from fleetmind.copilot.tools import REGISTRY
from fleetmind.security.protect import SecurityMiddleware
from fleetmind.security.settings import SecuritySettings
from fleetmind.security.store import SecurityStore
from scripts.copilot_fixtures import FixtureEnvironment, FixtureToolExecutor
from scripts.evaluate_copilot import inspect_case
from scripts.evaluate_knowledge import percentiles

SUITE = Path("docs/copilot/live-evaluation-m11b.json")


class Case(ChatRequest):
    id: Annotated[str, Field(pattern=r"^live-[a-z]+$")]
    category: str
    status: Status
    required_tools: list[str] = Field(default_factory=list)
    contains: list[str] = Field(default_factory=list)


def load_cases(path=SUITE):
    raw = path.read_bytes()
    cases = TypeAdapter(list[Case]).validate_json(raw)
    if not cases or len(cases) != len({case.id for case in cases}):
        raise ValueError("Live suite requires unique case IDs.")
    if any(set(case.required_tools) - set(REGISTRY) for case in cases):
        raise ValueError("Live suite names an unregistered tool.")
    return cases, hashlib.sha256(raw).hexdigest()


def authorization_probe(fixture):
    local = FastAPI()
    local.add_middleware(SecurityMiddleware)
    local.include_router(security_router)
    local.include_router(copilot_router)
    local.include_router(conversations_router)
    store = SecurityStore(sessionmaker(fixture.engine, expire_on_commit=False))
    local.state.security_store = store
    local.state.security_settings = SecuritySettings(
        frozenset({"http://testserver"}), True
    )
    local.dependency_overrides[conversation_store] = lambda: ConversationStore(
        store.factory
    )
    password = token_urlsafe(24)
    admin = store.create_user("fixture-owner", password, "administrator")
    store.create_user("fixture-viewer", password, "viewer", actor=admin.id)
    store.create_user("fixture-engineer", password, "engineer", actor=admin.id)

    def sign_in(client, username):
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://testserver"},
            json={"username": username, "password": password},
        )
        response.raise_for_status()
        client.headers.update(
            {
                "Origin": "http://testserver",
                "X-FleetMind-CSRF": client.cookies["fleetmind_csrf"],
            }
        )

    with (
        TestClient(local) as owner,
        TestClient(local) as viewer,
        TestClient(local) as engineer,
    ):
        prefix = "/api/v1/copilot/conversations"
        anonymous = viewer.get(prefix).status_code == 401
        sign_in(owner, "fixture-owner")
        sign_in(viewer, "fixture-viewer")
        sign_in(engineer, "fixture-engineer")
        response = owner.post(prefix, json={"title": "Private evaluator fixture"})
        response.raise_for_status()
        location = prefix + "/" + response.json()["id"]
        return {
            "unsigned_conversation_list_denied": anonymous,
            "viewer_chat_denied": viewer.post(
                "/api/v1/copilot/chat",
                json={
                    "question": "Read the private fixture.",
                },
            ).status_code
            == 403,
            "cross_owner_read_hidden": engineer.get(location).status_code == 404,
            "cross_owner_stream_hidden": engineer.post(
                location + "/messages/stream",
                json={
                    "request_id": "20000000-0000-0000-0000-000000000001",
                    "question": "Read the private fixture.",
                },
            ).status_code
            == 404,
        }


async def transport_probe():
    settings = Settings(
        provider="ollama",
        model="fixture",
        base_url="http://127.0.0.1:11434/v1",
        retries=0,
    )

    async def timeout(request):
        raise httpx.ReadTimeout("Fixture timeout.", request=request)

    probes = [
        ("provider_timeout", timeout),
        ("provider_rate_limited", lambda _request: httpx.Response(429)),
        ("provider_rejected_request", lambda _request: httpx.Response(400)),
    ]
    outcomes = {}
    for expected, handler in probes:
        provider = ChatCompletionsProvider(
            settings, transport=httpx.MockTransport(handler)
        )
        try:
            await provider.complete([], [])
        except ProviderError as exc:
            outcomes[expected] = str(exc) == expected
        else:
            outcomes[expected] = False
    return outcomes


async def evaluate_live(suite, fixture, settings, pricing):
    rows = []
    for case in suite:
        request = ChatRequest.model_validate(
            case.model_dump(include={"question", "asset_id", "context"})
        )
        executor = FixtureToolExecutor(fixture.store, fixture.hits, {})
        started = perf_counter()
        response = await Orchestrator(make_provider(settings), executor, settings).chat(
            request,
            fixture.context(request),
        )
        assertions = {
            **case.model_dump(),
            "rounds": [[[name, {}] for name in case.required_tools]],
        }
        result = inspect_case(assertions, response, live=True)
        result["wall_ms"] = round((perf_counter() - started) * 1000, 3)
        result["category"] = case.category
        result["provider_calls"] = response.diagnostics.provider_calls
        tokens = result["tokens"]
        result["estimated_usd"] = (
            (tokens["input"] * pricing[0] + tokens["output"] * pricing[1]) / 1e6
            if pricing is not None and tokens is not None
            else None
        )
        rows.append(result)
    return {
        "provider": settings.provider,
        "model": settings.model,
        "latency_ms": percentiles([row["wall_ms"] for row in rows]),
        "failures": [
            row["id"]
            for row in rows
            if not (
                row["answer_check"]
                and row["tool_selection_ok"]
                and row["tool_argument_validity"] in (None, 1.0)
            )
        ],
        "per_case": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly call the configured LLM"
    )
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="Confirm authorization for hosted charges",
    )
    parser.add_argument("--case")
    parser.add_argument(
        "--pricing-usd-per-million", nargs=2, type=float, metavar=("INPUT", "OUTPUT")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pricing = args.pricing_usd_per_million
    if pricing and any(not isfinite(value) or value < 0 for value in pricing):
        parser.error("Prices must be finite nonnegative numbers.")
    suite, digest = load_cases()
    if args.case:
        suite = [case for case in suite if case.id == args.case]
        if not suite:
            parser.error("Unknown suite case.")
    settings = None
    if args.live:
        settings = Settings.from_environment()
        if settings.provider not in {"openai", "ollama"}:
            parser.error("Configure a real Ollama or hosted provider.")
        host = urlsplit(settings.base_url).hostname
        paid = settings.provider == "openai" or host not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (paid or "cloud" in settings.model.lower()) and not args.allow_paid:
            parser.error(
                "Hosted providers require explicit --allow-paid authorization."
            )
        settings = replace(settings, max_rounds=min(settings.max_rounds, 4), retries=0)

    fixture = FixtureEnvironment()
    try:
        authorization = authorization_probe(fixture)
        transport = asyncio.run(transport_probe())
        live_result = (
            asyncio.run(evaluate_live(suite, fixture, settings, pricing))
            if settings
            else None
        )
        report = {
            "suite_sha256": digest,
            "planned_cases": len(suite),
            "fixture": "synthetic local records and frozen knowledge passages",
            "authorization": authorization,
            "provider_error_fixture": transport,
            "provider_evaluation": live_result,
            "live_status": "measured" if settings else "pending",
            "pricing_usd_per_million": pricing,
        }
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(f"Saved {args.output}. Live provider evaluation {report['live_status']}.")
        return int(
            not (all(authorization.values()) and all(transport.values()))
            or bool(live_result and live_result["failures"])
        )
    finally:
        fixture.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
