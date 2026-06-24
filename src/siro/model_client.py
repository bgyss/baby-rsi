"""Model client abstraction (Protocol) + a local llama.cpp/LlamaBarn client.

Goal 02 keeps the interface as small and provider-neutral as Goal 01 defined it so
Goal 07 can generalize it into the full provider layer (local + Claude + GPT)
without breaking callers:

    class ModelClient(Protocol):
        def generate(self, prompt: str) -> str: ...

A model produces *text* — proposals/patches — and nothing else. It never executes
commands, holds a network handle in the execution plane, or sees credentials there
(``docs/07_model_providers_and_tiers.md``). The only network the local client
touches is the allow-listed provider socket ``127.0.0.1:2276`` (control plane).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

#: Default Tier 0 endpoint — the OpenAI-compatible llama.cpp / LlamaBarn server.
DEFAULT_BASE_URL = "http://127.0.0.1:2276/v1"
DEFAULT_MODEL = "unsloth/Qwen3.6-27B-GGUF:Q8_0"


@runtime_checkable
class ModelClient(Protocol):
    """Minimal provider-neutral interface. Generalized in Goal 07."""

    def generate(self, prompt: str) -> str:
        """Return model output text for ``prompt``."""
        ...


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


class NullModelClient:
    """Offline placeholder that refuses to generate. Useful as an explicit default."""

    def generate(self, prompt: str) -> str:  # noqa: ARG002 - stub
        raise NotImplementedError(
            "No model provider is configured. Use LocalOpenAIClient (llama.cpp / "
            "LlamaBarn) or a ScriptedModelClient for offline tests."
        )


class ScriptedModelClient:
    """Deterministic offline client that replays canned responses, in order.

    Lets the full code-improver loop (and its tests) run for N generations with no
    model server and no network — the same way negative results stay reproducible.
    """

    def __init__(self, responses: list[str]) -> None:
        if not responses:
            raise ValueError("ScriptedModelClient needs at least one response")
        self.provider = "scripted"
        self.model = "scripted"
        self._responses = list(responses)
        self._i = 0

    def generate(self, prompt: str) -> str:  # noqa: ARG002 - prompt unused by design
        response = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return response


class LocalOpenAIClient:
    """llama.cpp / LlamaBarn client over the OpenAI-compatible ``/chat/completions``.

    Uses only the standard library (``urllib``) to keep Tier 0 dependency-light. The
    endpoint is the allow-listed local provider socket; no credentials are sent.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 120.0,
        temperature: float = 0.7,
    ) -> None:
        self.provider = "local"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def generate(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:  # pragma: no cover - needs a live server
            raise RuntimeError(
                f"Local model server unreachable at {self.base_url}. "
                "Start it with `mise run serve-model`."
            ) from exc
        return body["choices"][0]["message"]["content"]


__all__ = [
    "ModelClient",
    "NullModelClient",
    "ScriptedModelClient",
    "LocalOpenAIClient",
    "extract_code",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
]
