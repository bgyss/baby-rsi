"""Control-plane HTTP — the *only* place the system reaches the network (Goal 07).

Uses the standard library (``urllib``) so Tier 0 stays dependency-light and every
outbound request is auditable in one file. Two safety properties live here:

- **Egress allowlist**: :func:`assert_allowed` refuses any host not on the configured
  allowlist, so the only outbound network permitted is to model-provider endpoints
  (``docs/07_model_providers_and_tiers.md``). This is the control-plane egress control.
- **Injectable transport**: clients post through a ``transport`` callable that defaults
  to :func:`post_json`. Tests pass a fake transport so the whole provider layer runs
  fully offline — the same reason the candidate sandbox has no network.

This module never runs candidate code and never carries credentials into the execution
plane; API keys live only in the per-request headers passed here by the control plane.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from .ops import ProviderError, ProviderErrorKind, classify_http_error

#: A transport posts a JSON body and returns the decoded JSON response.
Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class _SupportsHost(Protocol):  # pragma: no cover - typing only
    hostname: str | None
    port: int | None


def _host_forms(url: str) -> set[str]:
    """Return the host identifiers a URL matches against the allowlist.

    Allowlist entries may be bare hosts (``api.anthropic.com``) or ``host:port``
    (``127.0.0.1:2276``); both forms are accepted.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    forms = {host}
    if parts.port is not None:
        forms.add(f"{host}:{parts.port}")
    return forms


def assert_allowed(url: str, allowed_endpoints: list[str] | None) -> None:
    """Raise ``PermissionError`` if ``url``'s host is not on the egress allowlist.

    ``allowed_endpoints is None`` disables the check (Tier 0 default, where the only
    endpoint is the local llama.cpp socket). When a list is given, the host must match
    one entry exactly — default-deny.
    """
    if allowed_endpoints is None:
        return
    allowed = {e.strip() for e in allowed_endpoints}
    if not (_host_forms(url) & allowed):
        raise PermissionError(
            f"Egress blocked: {urlsplit(url).hostname} is not on the allowlist "
            f"({', '.join(sorted(allowed))})."
        )


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the decoded JSON response (control plane)."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if isinstance(body, dict):
                body.setdefault("_meta", {})
                body["_meta"].update(
                    {
                        "http_status": resp.status,
                        "provider_request_id": (
                            resp.headers.get("x-request-id")
                            or resp.headers.get("request-id")
                            or resp.headers.get("anthropic-request-id")
                            or ""
                        ),
                        "provider_version": resp.headers.get("openai-model") or "",
                    }
                )
            return body
    except urllib.error.HTTPError as exc:  # pragma: no cover - needs a live server
        body = exc.read().decode("utf-8", "replace")
        request_id = (
            exc.headers.get("x-request-id")
            or exc.headers.get("request-id")
            or exc.headers.get("anthropic-request-id")
            or ""
        )
        raise classify_http_error(
            exc.code, f"Provider HTTP {exc.code} from {url}: {body}", request_id=request_id
        ) from exc
    except urllib.error.URLError as exc:  # pragma: no cover - needs a live server
        raise ProviderError(
            ProviderErrorKind.TRANSIENT,
            f"Provider endpoint unreachable at {url}: {exc.reason}",
        ) from exc


__all__ = ["Transport", "assert_allowed", "post_json"]
