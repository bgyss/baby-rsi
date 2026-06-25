"""Provider operations: classified errors, bounded retries, and request metadata."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ProviderErrorKind(str, Enum):
    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    BUDGET = "budget"
    MALFORMED_RESPONSE = "malformed_response"
    POLICY_REFUSAL = "policy_refusal"
    CLIENT_CONFIG = "client_config"


@dataclass
class ProviderError(RuntimeError):
    kind: ProviderErrorKind
    message: str
    status_code: int | None = None
    request_id: str = ""
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    jitter_seconds: float = 0.05

    @classmethod
    def from_config(cls, block: dict[str, Any] | None) -> "RetryPolicy":
        block = block or {}
        return cls(
            max_attempts=max(1, int(block.get("max_attempts", 1))),
            initial_backoff_seconds=float(block.get("initial_backoff_seconds", 0.25)),
            max_backoff_seconds=float(block.get("max_backoff_seconds", 2.0)),
            jitter_seconds=float(block.get("jitter_seconds", 0.05)),
        )

    def delay(self, retry_index: int) -> float:
        base = min(
            self.max_backoff_seconds,
            self.initial_backoff_seconds * (2 ** max(0, retry_index)),
        )
        return base + (random.random() * self.jitter_seconds if self.jitter_seconds else 0.0)


@dataclass(frozen=True)
class ProviderOpsConfig:
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    requests_per_minute: int | None = None
    concurrency_limit: int | None = None

    @classmethod
    def from_block(cls, block: dict[str, Any]) -> "ProviderOpsConfig":
        ops = block.get("ops") or {}
        return cls(
            retry=RetryPolicy.from_config(ops.get("retry")),
            requests_per_minute=(
                None if ops.get("requests_per_minute") is None else int(ops["requests_per_minute"])
            ),
            concurrency_limit=(
                None if ops.get("concurrency_limit") is None else int(ops["concurrency_limit"])
            ),
        )


RETRYABLE_KINDS = {ProviderErrorKind.TRANSIENT, ProviderErrorKind.RATE_LIMIT}


def classify_http_error(status_code: int, message: str, *, request_id: str = "") -> ProviderError:
    if status_code in {401, 403}:
        kind = ProviderErrorKind.AUTH
    elif status_code == 429:
        kind = ProviderErrorKind.RATE_LIMIT
    elif 500 <= status_code <= 599:
        kind = ProviderErrorKind.TRANSIENT
    elif status_code == 400:
        kind = ProviderErrorKind.CLIENT_CONFIG
    else:
        kind = ProviderErrorKind.CLIENT_CONFIG
    return ProviderError(kind=kind, message=message, status_code=status_code, request_id=request_id)


def provider_metadata(body: dict[str, Any], *, retry_count: int = 0) -> dict[str, Any]:
    meta = body.get("_meta") if isinstance(body.get("_meta"), dict) else {}
    return {
        "provider_request_id": str(
            meta.get("provider_request_id") or body.get("id") or body.get("request_id") or ""
        ),
        "http_status": int(meta.get("http_status", 200) or 200),
        "retry_count": retry_count,
        "provider_version": str(
            meta.get("provider_version") or body.get("model_version") or body.get("model") or ""
        ),
        "final_error_kind": "",
    }


def call_with_retries(
    call: Callable[[], dict[str, Any]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], int]:
    attempts = 0
    while True:
        try:
            return call(), attempts
        except ProviderError as exc:
            if exc.kind not in RETRYABLE_KINDS or attempts >= policy.max_attempts - 1:
                exc.retry_count = attempts
                raise
            sleep(policy.delay(attempts))
            attempts += 1


__all__ = [
    "ProviderError",
    "ProviderErrorKind",
    "ProviderOpsConfig",
    "RetryPolicy",
    "call_with_retries",
    "classify_http_error",
    "provider_metadata",
]
