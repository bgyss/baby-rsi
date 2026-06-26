"""Provider-agnostic model interface — the contract every backend satisfies (Goal 07).

This generalizes the Goal 02 single-method ``ModelClient`` into the structured/tool-using
layer the frontier organization needs, *without* changing the loop's safety contract
(``docs/07_model_providers_and_tiers.md``):

    class ModelClient(Protocol):
        def complete(self, request: ModelRequest) -> ModelResponse: ...
        def run(self, messages, tools, response_schema) -> ModelResponse: ...

A model still only produces *text, structured proposals, or tool requests* — never
executes them. The controller (not the model) runs fixed vetted commands in the
execution plane. Backends carry **no** credentials into the execution plane and reach
the network only through the control-plane HTTP layer in ``_http`` against allow-listed
endpoints.

``complete`` is the single primitive each backend implements (as ``_complete``);
:meth:`BaseModelClient.run` and :meth:`BaseModelClient.generate` are convenience
wrappers so the existing Goal 02 ``model.generate(prompt) -> str`` call site keeps
working unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass
class Message:
    """One chat message. ``content`` is plain text; tool results are passed as text."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass
class ToolSpec:
    """A control-plane tool the model may *request*. The controller, not the model,
    decides whether and how to run it (tools are never raw shell/network)."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    """A tool invocation the model asked for. Data only — never auto-executed here."""

    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class Usage:
    """Per-call cost accounting: tokens, estimated USD, and latency (Goal 07).

    This is what makes self-improvement *cost-aware* — the audit ledger and budget
    both read from it (``docs/13_self_improvement_loop.md``).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    pricing_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ModelRequest:
    """A provider-neutral request. ``response_schema`` (when set) forces structured
    output validated against a Pydantic model; ``tools`` offers control-plane tools."""

    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: type[BaseModel] | None = None
    max_tokens: int | None = None
    temperature: float = 0.7


@dataclass
class ModelResponse:
    """A provider-neutral response carrying text/structured content, tool calls, and
    :class:`Usage`. ``structured`` is a validated instance of the request's
    ``response_schema`` when one was supplied."""

    text: str = ""
    structured: BaseModel | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    provider: str = ""
    model: str = ""
    prompt_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None


def prompt_hash(text: str) -> str:
    """Stable short hash of a prompt for the audit ledger (no prompt text is stored)."""
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def messages_hash(messages: list[Message]) -> str:
    """Hash a whole message list — the prompt-hash for multi-message requests."""
    joined = "\n".join(f"{m.role}:{m.content}" for m in messages)
    return prompt_hash(joined)


def extract_code(text: str) -> str:
    """Pull a Python code block out of model output, tolerating markdown fences.

    Models often wrap code in ```python ... ``` fences and add prose. We take the
    first fenced block if present, otherwise the whole (stripped) text. This is the
    only place model output is interpreted — and only as *data* to be written to a
    file, never executed in the control plane.
    """
    fenced = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1).strip() + "\n"
    return text.strip() + "\n"


@runtime_checkable
class ModelClient(Protocol):
    """The provider-agnostic interface. Every backend (local/Claude/GPT) satisfies it,
    so swapping providers never requires editing the controller, evaluator, sandbox,
    gates, or memory schema (``docs/07_model_providers_and_tiers.md``)."""

    def complete(self, request: ModelRequest) -> ModelResponse: ...

    def run(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> ModelResponse: ...

    def generate(self, prompt: str) -> str: ...


class BaseModelClient:
    """Shared plumbing for every backend.

    Subclasses implement only :meth:`_complete`. The base class wraps it to record the
    last :class:`Usage` (so the controller can log and budget it) and provides the
    ``run``/``generate`` conveniences the existing loop depends on.
    """

    provider: str = "base"
    model: str = "base"

    def __init__(self) -> None:
        self.last_usage: Usage = Usage()
        self.last_response: ModelResponse | None = None

    # --- backend hook -------------------------------------------------------
    def _complete(self, request: ModelRequest) -> ModelResponse:  # pragma: no cover - abstract
        raise NotImplementedError

    # --- public interface ---------------------------------------------------
    def complete(self, request: ModelRequest) -> ModelResponse:
        response = self._complete(request)
        self.last_usage = response.usage
        self.last_response = response
        return response

    def run(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        response_schema: type[BaseModel] | None = None,
    ) -> ModelResponse:
        return self.complete(
            ModelRequest(
                messages=list(messages),
                tools=list(tools or []),
                response_schema=response_schema,
            )
        )

    def generate(self, prompt: str) -> str:
        return self.complete(
            ModelRequest(messages=[Message(role="user", content=prompt)])
        ).text


__all__ = [
    "Message",
    "ToolSpec",
    "ToolCall",
    "Usage",
    "ModelRequest",
    "ModelResponse",
    "ModelClient",
    "BaseModelClient",
    "prompt_hash",
    "messages_hash",
    "extract_code",
]
