"""Structured Chat Completions adapter and a deterministic test provider."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import ValidationError

from fleetmind.copilot.schemas import Tokens, ToolCall
from fleetmind.copilot.settings import Settings


class ProviderError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    tokens: Tokens | None = None


class Provider(Protocol):
    async def complete(
        self, messages: list[dict], tools: list[dict] | None
    ) -> Completion: ...


class MockProvider:
    def __init__(self, steps=()):
        self.steps = deque(steps)
        self.requests: list[list[dict]] = []

    async def complete(self, messages, tools):
        self.requests.append(list(messages))
        if not self.steps:
            return Completion(text='{"status":"insufficient_evidence","fact_ids":[]}')
        result = self.steps.popleft()
        if isinstance(result, Exception):
            raise result
        return result


class ChatCompletionsProvider:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    async def complete(self, messages, tools):
        config = self.settings
        payload = {
            "model": config.model,
            "messages": messages,
            config.token_parameter: config.max_tokens,
        }
        if tools is not None:
            payload.update(tools=tools, tool_choice="auto")
        else:
            payload["response_format"] = {"type": "json_object"}
        headers = (
            {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        )
        async with httpx.AsyncClient(
            timeout=config.provider_timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for attempt in range(config.retries + 1):
                try:
                    async with asyncio.timeout(config.provider_timeout):
                        async with client.stream(
                            "POST",
                            f"{config.base_url}/chat/completions",
                            json=payload,
                            headers=headers,
                        ) as response:
                            response.raise_for_status()
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                body.extend(chunk)
                                if len(body) > 256_000:
                                    raise ProviderError("provider_response_too_large")
                    return parse_completion(body)
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if 400 <= status < 500 and status != 429:
                        raise ProviderError("provider_rejected_request") from None
                    failure = (
                        "provider_rate_limited"
                        if status == 429
                        else "provider_unreachable"
                    )
                except (TimeoutError, httpx.TimeoutException):
                    failure = "provider_timeout"
                except httpx.RequestError:
                    failure = "provider_unreachable"
                if attempt < config.retries:
                    await asyncio.sleep(0.15 * 2**attempt)
        raise ProviderError(failure)


def parse_completion(body: bytes | bytearray) -> Completion:
    import json

    try:
        data = json.loads(body)
        choice = data["choices"][0]
        if choice.get("finish_reason") in {"length", "content_filter"}:
            raise ValueError
        message = choice["message"]
        content = message.get("content")
        raw_calls = message.get("tool_calls")
        content = "" if content is None else content
        raw_calls = [] if raw_calls is None else raw_calls
        if (
            not isinstance(content, str)
            or not isinstance(raw_calls, list)
            or len(raw_calls) > 32
        ):
            raise ValueError
        calls = [
            ToolCall(
                id=call["id"],
                name=call["function"]["name"],
                arguments=call["function"]["arguments"],
            )
            for call in raw_calls
            if call["type"] == "function"
        ]
        if len(calls) != len(raw_calls):
            raise ValueError
        usage = data.get("usage") or {}
        tokens = (
            Tokens(input=usage["prompt_tokens"], output=usage["completion_tokens"])
            if ("prompt_tokens" in usage and "completion_tokens" in usage)
            else None
        )
        return Completion(content, calls, tokens)
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        ValidationError,
    ):
        raise ProviderError("provider_malformed_response") from None
