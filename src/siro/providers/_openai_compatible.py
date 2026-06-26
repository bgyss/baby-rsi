"""Shared request/response plumbing for OpenAI-compatible Chat Completions.

The local llama.cpp / LlamaBarn server and the OpenAI API speak the *same* wire format,
so ``local.py`` and ``openai.py`` differ only in ``base_url`` and credentials — exactly
as Goal 07 calls for. This module owns the payload build and response parse (text,
tool calls, structured output, usage) so neither client repeats it.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from ._http import Transport, assert_allowed, post_json
from .base import (
    BaseModelClient,
    ModelRequest,
    ModelResponse,
    ToolCall,
    Usage,
    messages_hash,
)
from .ops import ProviderError, ProviderErrorKind, RetryPolicy, call_with_retries, provider_metadata
from .pricing import Pricing, estimate_tokens


def _tool_to_openai(spec_name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec_name,
            "description": description,
            "parameters": parameters or {"type": "object", "properties": {}},
        },
    }


def build_payload(model: str, request: ModelRequest) -> dict[str, Any]:
    """Translate a provider-neutral :class:`ModelRequest` to a Chat Completions body."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "stream": False,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [
            _tool_to_openai(t.name, t.description, t.parameters) for t in request.tools
        ]
    if request.response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.response_schema.__name__,
                "schema": request.response_schema.model_json_schema(),
                "strict": True,
            },
        }
    return payload


def parse_response(
    body: dict[str, Any],
    request: ModelRequest,
    provider: str,
    model: str,
    pricing: Pricing,
    latency_ms: float,
    metadata: dict[str, Any] | None = None,
) -> ModelResponse:
    """Parse a Chat Completions body into a provider-neutral :class:`ModelResponse`."""
    if isinstance(body.get("error"), dict):
        err = body["error"]
        message = str(err.get("message") or err)
        kind = ProviderErrorKind.POLICY_REFUSAL if "policy" in message.lower() else ProviderErrorKind.CLIENT_CONFIG
        raise ProviderError(kind, message)
    if not body.get("choices"):
        raise ProviderError(ProviderErrorKind.MALFORMED_RESPONSE, "missing choices in provider response")
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message", {})
    text = message.get("content") or ""

    tool_calls: list[ToolCall] = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments")}
        tool_calls.append(ToolCall(name=fn.get("name", ""), arguments=args, id=call.get("id", "")))

    structured: BaseModel | None = None
    if request.response_schema is not None and text:
        structured = request.response_schema.model_validate_json(text)

    usage_block = body.get("usage") or {}
    input_tokens = int(usage_block.get("prompt_tokens", 0)) or estimate_tokens(
        "".join(m.content for m in request.messages)
    )
    output_tokens = int(usage_block.get("completion_tokens", 0)) or estimate_tokens(text)
    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=pricing.cost_usd(input_tokens, output_tokens),
        latency_ms=latency_ms,
        pricing_metadata=pricing.metadata(),
    )
    response_meta = metadata or provider_metadata(body)
    return ModelResponse(
        text=text,
        structured=structured,
        tool_calls=tool_calls,
        usage=usage,
        provider=provider,
        model=model,
        prompt_hash=messages_hash(request.messages),
        metadata=response_meta,
        raw=body,
    )


class OpenAICompatibleClient(BaseModelClient):
    """Base for any OpenAI-compatible Chat Completions endpoint (local *and* GPT)."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        temperature: float = 0.7,
        pricing: Pricing | None = None,
        retry_policy: RetryPolicy | None = None,
        allowed_endpoints: list[str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.pricing = pricing or Pricing()
        self.retry_policy = retry_policy or RetryPolicy()
        self.allowed_endpoints = allowed_endpoints
        self._transport = transport or post_json

    def _headers(self) -> dict[str, str]:
        # Credentials live only in the control-plane request header — never in env
        # handed to the execution plane.
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _complete(self, request: ModelRequest) -> ModelResponse:
        import time

        if request.temperature is None:  # pragma: no cover - defensive
            request.temperature = self.temperature
        url = f"{self.base_url}/chat/completions"
        assert_allowed(url, self.allowed_endpoints)
        payload = build_payload(self.model, request)
        start = time.perf_counter()
        try:
            body, retry_count = call_with_retries(
                lambda: self._transport(url, payload, self._headers(), self.timeout_seconds),
                self.retry_policy,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(ProviderErrorKind.TRANSIENT, str(exc)) from exc
        latency_ms = (time.perf_counter() - start) * 1000.0
        metadata = provider_metadata(body, retry_count=retry_count)
        return parse_response(
            body, request, self.provider, self.model, self.pricing, latency_ms, metadata=metadata
        )


__all__ = ["OpenAICompatibleClient", "build_payload", "parse_response"]
