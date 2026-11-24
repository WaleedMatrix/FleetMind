"""One bounded request, a fixed registry, and an extractive answer."""

import asyncio
import logging
import re
from time import perf_counter

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.copilot.evidence import Evidence
from fleetmind.copilot.prompts import final_messages, packed, start_messages
from fleetmind.copilot.providers import ProviderError
from fleetmind.copilot.schemas import Diagnostics, Tokens
from fleetmind.copilot.tools import REGISTRY, AssetInput, ToolFailure, tool_definitions
from fleetmind.copilot.validation import response, validate_final

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, provider, executor, settings, on_event=None):
        self.provider = provider
        self.executor = executor
        self.settings = settings
        self.on_event = on_event

    def emit(self, kind, **details):
        if self.on_event is not None:
            self.on_event(kind, **details)

    async def chat(self, request, context):
        started = perf_counter()
        diagnostics = Diagnostics()
        try:
            async with asyncio.timeout(self.settings.request_timeout):
                result = await self._collect(request, context, diagnostics)
        except TimeoutError:
            diagnostics.issues.append("request_deadline")
            result = response("unavailable", diagnostics)
        except ProviderError as exc:
            diagnostics.issues.append(str(exc))
            result = response("unavailable", diagnostics)
        result.diagnostics.elapsed_ms = round((perf_counter() - started) * 1000, 3)
        return result

    async def _complete(self, messages, tools, diagnostics):
        diagnostics.provider_calls += 1
        result = await self.provider.complete(messages, tools)
        if result.tokens is not None:
            old = diagnostics.tokens or Tokens(input=0, output=0)
            diagnostics.tokens = Tokens(
                input=old.input + result.tokens.input,
                output=old.output + result.tokens.output,
            )
        return result

    async def _collect(self, request, context, diagnostics):
        talk = start_messages(request, context.prediction_id)
        evidence = Evidence()
        seen: set[tuple[str, str]] = set()
        if context.asset_id:
            diagnostics.tool_count += 1
            diagnostics.valid_tool_arguments += 1
            diagnostics.tool_names.append("get_asset")
            self.emit("tool_started", tool="get_asset")
            try:
                await self.executor.run(
                    REGISTRY["get_asset"],
                    AssetInput(asset_id=context.asset_id),
                    context,
                    self.settings.tool_timeout,
                )
                self.emit("tool_completed", tool="get_asset", outcome="ok")
            except ToolFailure as exc:
                self.emit("tool_completed", tool="get_asset", outcome="error")
                diagnostics.issues.append(str(exc))
                if str(exc) == "record_not_found":
                    return response(
                        "clarification_required",
                        diagnostics,
                        answer="The selected asset was not found. Choose a valid ID.",
                    )
                return response("unavailable", diagnostics)
            except (SQLAlchemyError, ValidationError):
                self.emit("tool_completed", tool="get_asset", outcome="error")
                diagnostics.issues.append("asset_verification_failed")
                return response("unavailable", diagnostics)

        definitions = tool_definitions()
        for _ in range(self.settings.max_rounds):
            if diagnostics.tool_count >= self.settings.max_tools:
                break
            result = await self._complete(talk, definitions, diagnostics)
            if not result.calls:
                break
            diagnostics.tool_rounds += 1
            remaining = self.settings.max_tools - diagnostics.tool_count
            calls = result.calls[:remaining]
            if len(result.calls) > remaining:
                diagnostics.issues.append("tool_budget_exceeded")
            # Keep tool messages protocol-valid even if a provider repeats call IDs.
            calls = list({call.id: call for call in reversed(calls)}.values())[::-1]
            talk.append(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.arguments,
                            },
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                payload = await self._invoke(call, context, evidence, seen, diagnostics)
                talk.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": packed(payload),
                    }
                )
            if diagnostics.tool_count >= self.settings.max_tools:
                break
        else:
            diagnostics.issues.append("tool_round_limit")

        if (
            not context.asset_id
            and len(evidence.asset_matches) > 1
            and not any(
                re.search(
                    rf"(?<![\w-]){re.escape(asset)}(?![\w-])", request.question, re.I
                )
                for asset in evidence.asset_matches
            )
        ):
            return response(
                "clarification_required",
                diagnostics,
                answer="Several assets match. Please choose the exact asset ID.",
                asset_ids=sorted(evidence.asset_matches),
            )
        facts = evidence.for_question(request.question)
        if not facts:
            status = (
                "clarification_required"
                if "asset_id_required" in diagnostics.issues
                else "insufficient_evidence"
            )
            return response(status, diagnostics)
        final = await self._complete(
            final_messages(request, facts, context.prediction_id), None, diagnostics
        )
        if final.calls:
            diagnostics.issues.append("final_tool_calls_rejected")
            return response("insufficient_evidence", diagnostics)
        return validate_final(final.text, facts, evidence, diagnostics)

    async def _invoke(self, call, context, evidence, seen, diagnostics):
        diagnostics.tool_count += 1
        tool = REGISTRY.get(call.name)
        started = False
        diagnostics.tool_names.append(call.name if tool else "unknown")
        try:
            if tool is None:
                raise ToolFailure("unknown_tool")
            try:
                args = tool.input.model_validate_json(call.arguments)
            except ValidationError:
                raise ToolFailure("invalid_tool_arguments") from None
            diagnostics.valid_tool_arguments += 1
            canonical = packed(args.model_dump(mode="json"))
            key = (call.name, canonical)
            if key in seen:
                raise ToolFailure("duplicate_tool_call")
            seen.add(key)
            started = True
            self.emit("tool_started", tool=call.name)
            result = await self.executor.run(
                tool, args, context, self.settings.tool_timeout
            )
            if call.name == "search_knowledge" and result.keyword_fallback:
                diagnostics.issues.append("knowledge_keyword_fallback")
            old = set(evidence.facts)
            evidence.ingest(call.name, result, args, context.asset_id)
            self.emit("tool_completed", tool=call.name, outcome="ok")
            if added := len(evidence.facts) - len(old):
                self.emit("evidence", count=added)
            return {
                "facts": [
                    {"id": key, "text": fact.text, "source": fact.citation.title}
                    for key, fact in evidence.facts.items()
                    if key not in old
                ][:12]
            }
        except ToolFailure as exc:
            issue = str(exc)
        except (
            SQLAlchemyError,
            ValidationError,
            ValueError,
            RuntimeError,
            OSError,
        ) as exc:
            logger.warning("Copilot tool failed (%s)", type(exc).__name__)
            issue = "tool_unavailable"
        diagnostics.issues.append(issue)
        if started:
            self.emit("tool_completed", tool=call.name, outcome="error")
        return {"error": issue}
