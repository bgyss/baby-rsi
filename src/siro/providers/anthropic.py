"""Anthropic (Claude) backend — the Messages API with tool use and structured output.

Claude's wire format differs from OpenAI's: a top-level ``system`` field, ``input_tokens``/
``output_tokens`` in ``usage``, and structured output expressed as a **forced tool call**
rather than ``response_format``. This module owns that translation so the rest of the
system stays provider-neutral (``docs/07_model_providers_and_tiers.md``). The API key is
read in the control plane only and sent as the ``x-api-key`` header — never placed in any
environment handed to the execution plane.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from ._http import Transport, assert_allowed, post_json
from .base import BaseModelClient, ModelRequest, ModelResponse, ToolCall, Usage, messages_hash
from .pricing import Pricing, estimate_tokens

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-opus-4-8"
ANTHROPIC_VERSION = "2023-06-01"

#: Name of the synthetic tool used to force structured (schema-validated) output.
_STRUCTURED_TOOL = "emit_structured_result"


class AnthropicClient(BaseModelClient):
    """Claude via the Messages API."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 120.0,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        pricing: Pricing | None = None,
        allowed_endpoints: list[str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__()
        self.provider = "anthropic"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.default_max_tokens = max_tokens
        self.pricing = pricing or Pricing.resolve("anthropic", model)
        self.allowed_endpoints = allowed_endpoints
        self._transport = transport or post_json

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
        }

    def _build_payload(self, request: ModelRequest) -> dict[str, Any]:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        turns = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": turns,
            "max_tokens": request.max_tokens or self.default_max_tokens,
            "temperature": request.temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        tools: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters
             or {"type": "object", "properties": {}}}
            for t in request.tools
        ]
        if request.response_schema is not None:
            # Structured output = a forced tool whose input *is* the schema. Claude must
            # call it, so its validated input becomes the structured result.
            tools.append(
                {
                    "name": _STRUCTURED_TOOL,
                    "description": "Return the final result as structured JSON.",
                    "input_schema": request.response_schema.model_json_schema(),
                }
            )
            payload["tool_choice"] = {"type": "tool", "name": _STRUCTURED_TOOL}
        if tools:
            payload["tools"] = tools
        return payload

    def _complete(self, request: ModelRequest) -> ModelResponse:
        url = f"{self.base_url}/messages"
        assert_allowed(url, self.allowed_endpoints)
        payload = self._build_payload(request)
        start = time.perf_counter()
        body = self._transport(url, payload, self._headers(), self.timeout_seconds)
        latency_ms = (time.perf_counter() - start) * 1000.0

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        structured: BaseModel | None = None
        for block in body.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                name = block.get("name", "")
                args = block.get("input") or {}
                if name == _STRUCTURED_TOOL and request.response_schema is not None:
                    structured = request.response_schema.model_validate(args)
                else:
                    tool_calls.append(ToolCall(name=name, arguments=args, id=block.get("id", "")))
        text = "".join(text_parts)

        usage_block = body.get("usage") or {}
        input_tokens = int(usage_block.get("input_tokens", 0)) or estimate_tokens(
            "".join(m.content for m in request.messages)
        )
        output_tokens = int(usage_block.get("output_tokens", 0)) or estimate_tokens(text)
        usage = Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self.pricing.cost_usd(input_tokens, output_tokens),
            latency_ms=latency_ms,
        )
        return ModelResponse(
            text=text,
            structured=structured,
            tool_calls=tool_calls,
            usage=usage,
            provider=self.provider,
            model=self.model,
            prompt_hash=messages_hash(request.messages),
            raw=body,
        )


__all__ = ["AnthropicClient", "DEFAULT_BASE_URL", "DEFAULT_MODEL"]
