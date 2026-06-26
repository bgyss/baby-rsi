import pytest

from siro.archive import JSONLArchive, ModelCallLedger
from siro.cli import main
from siro.controller import Controller
from siro.providers import Message, OpenAIClient
from siro.providers.ops import ProviderError, ProviderErrorKind, RetryPolicy
from siro.research import ResearchArchive
from siro.schemas import AttemptStatus, Candidate, MetricRecord, ModelCall, ResearchAttempt


def test_retryable_failure_retries_then_succeeds():
    calls = {"n": 0}

    def transport(url, payload, headers, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ProviderError(ProviderErrorKind.TRANSIENT, "temporary")
        return {
            "_meta": {"http_status": 200, "provider_request_id": "req-2"},
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }

    client = OpenAIClient(
        api_key="sk",
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0, jitter_seconds=0),
        transport=transport,
    )

    response = client.run([Message(role="user", content="hello")])

    assert response.text == "ok"
    assert calls["n"] == 2
    assert response.metadata["retry_count"] == 1
    assert response.metadata["provider_request_id"] == "req-2"


def test_auth_failure_does_not_retry():
    calls = {"n": 0}

    def transport(url, payload, headers, timeout):
        calls["n"] += 1
        raise ProviderError(ProviderErrorKind.AUTH, "bad key", status_code=401)

    client = OpenAIClient(
        api_key="sk",
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0, jitter_seconds=0),
        transport=transport,
    )

    with pytest.raises(ProviderError) as exc:
        client.run([Message(role="user", content="hello")])

    assert exc.value.kind is ProviderErrorKind.AUTH
    assert calls["n"] == 1


def test_budget_error_does_not_retry():
    calls = {"n": 0}

    def transport(url, payload, headers, timeout):
        calls["n"] += 1
        raise ProviderError(ProviderErrorKind.BUDGET, "budget breached")

    client = OpenAIClient(
        api_key="sk",
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=0, jitter_seconds=0),
        transport=transport,
    )

    with pytest.raises(ProviderError) as exc:
        client.run([Message(role="user", content="hello")])

    assert exc.value.kind is ProviderErrorKind.BUDGET
    assert calls["n"] == 1


def test_malformed_response_is_classified():
    client = OpenAIClient(api_key="sk", transport=lambda *args: {"usage": {}})

    with pytest.raises(ProviderError) as exc:
        client.run([Message(role="user", content="hello")])

    assert exc.value.kind is ProviderErrorKind.MALFORMED_RESPONSE


class _FailingModel:
    provider = "openai"
    model = "gpt-test"

    def generate(self, prompt):
        raise ProviderError(
            ProviderErrorKind.RATE_LIMIT,
            "slow down",
            status_code=429,
            request_id="req-rate",
            retry_count=2,
        )


def test_controller_logs_failed_provider_call(tmp_path):
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    controller = Controller(archive=JSONLArchive(tmp_path / "attempts.jsonl"), ledger=ledger)

    with pytest.raises(ProviderError):
        controller.run_task("tasks/code_improver/task_001", _FailingModel(), generations=1)

    rows = ledger.read_all()
    assert len(rows) == 1
    assert rows[0].final_error_kind == "rate_limit"
    assert rows[0].http_status == 429
    assert rows[0].provider_request_id == "req-rate"
    assert rows[0].retry_count == 2


def test_provider_report_attributes_spend_errors_and_promotions(tmp_path, capsys):
    ledger = ModelCallLedger(tmp_path / "model_calls.jsonl")
    ledger.append(
        ModelCall(
            provider="openai",
            model="gpt-test",
            role="safety",
            prompt_hash="h1",
            input_tokens=10,
            output_tokens=5,
            cost_usd=1.5,
            latency_ms=100,
            experiment_id="task_a",
        )
    )
    ledger.append(
        ModelCall(
            provider="openai",
            model="gpt-test",
            role="safety",
            prompt_hash="h2",
            final_error_kind="rate_limit",
            retry_count=2,
            experiment_id="task_a",
        )
    )
    ResearchArchive(tmp_path / "research.jsonl").append(
        ResearchAttempt(
            attempt_id="a",
            task_id="task_a",
            family="algorithm",
            candidate=Candidate(candidate_id="c", task_id="task_a", code="pass"),
            metric=MetricRecord(primary=1, passed=True, reproducible=True),
            status=AttemptStatus.PROMOTED,
        )
    )

    assert main([
        "provider-report",
        "--model-calls",
        str(tmp_path / "model_calls.jsonl"),
        "--research-attempts",
        str(tmp_path / "research.jsonl"),
    ]) == 0

    out = capsys.readouterr().out
    assert "openai/gpt-test role=safety" in out
    assert "error_rate=50%" in out
    assert "cost_per_promotion=$1.5000" in out
    assert "spend_by_family: algorithm=$1.5000" in out
