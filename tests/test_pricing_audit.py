from pathlib import Path

from siro.cli import main
from siro.config import load_config
from siro.providers import LocalOpenAIClient, Message, ProviderConfig, build_client
from siro.providers.pricing import Pricing


def write_config(path: Path, *, backend: str, prices: str = "", budget: str = "") -> Path:
    path.write_text(
        f"""
tier: 1
providers:
  subject:
    backend: {backend}
    name: model-x
{prices}
agent_models:
  default: subject
{budget}
""",
        encoding="utf-8",
    )
    return path


def test_config_price_override_takes_precedence(tmp_path):
    config_path = write_config(
        tmp_path / "tier.yaml",
        backend="openai",
        prices="""
    prices:
      input_per_mtok: 2.0
      output_per_mtok: 4.0
      cached_input_per_mtok: 0.5
      last_reviewed: "2026-06-25"
      source_url: "https://example.invalid/pricing"
""",
    )
    config = load_config(config_path)
    provider = config.providers["subject"]

    pricing = Pricing.resolve(provider.backend, provider.name, provider.prices)

    assert pricing.source_type == "override"
    assert pricing.cached_input_per_mtok == 0.5
    assert pricing.cost_usd(1_000_000, 1_000_000) == 6.0
    assert pricing.source == "https://example.invalid/pricing"


def test_pricing_audit_strict_warns_on_missing_price(tmp_path, capsys):
    config_path = write_config(tmp_path / "missing.yaml", backend="unknown")

    assert main(["pricing-audit", "--config", str(config_path), "--strict"]) == 1

    out = capsys.readouterr().out
    assert "missing-price" in out
    assert "STRICT FAIL" in out


def test_pricing_audit_strict_warns_on_stale_review(tmp_path, capsys):
    config_path = write_config(
        tmp_path / "stale.yaml",
        backend="openai",
        prices="""
    prices:
      input_per_mtok: 2.0
      output_per_mtok: 4.0
      last_reviewed: "2000-01-01"
      source_note: "old review"
""",
    )

    assert main([
        "pricing-audit",
        "--config",
        str(config_path),
        "--stale-days",
        "30",
        "--strict",
    ]) == 1

    out = capsys.readouterr().out
    assert "stale-review" in out
    assert "STRICT FAIL" in out


def test_pricing_estimates_known_token_counts():
    pricing = Pricing(input_per_mtok=2.0, output_per_mtok=4.0)

    assert pricing.cost_usd(500_000, 250_000) == 2.0


def test_local_providers_are_zero_cost_without_explicit_prices():
    client = build_client(ProviderConfig(key="local", backend="llamacpp", name="local-model"))

    assert isinstance(client, LocalOpenAIClient)
    assert client.pricing.cost_usd(1_000_000, 1_000_000) == 0.0
    assert client.pricing.source_type == "backend_default"


def test_model_call_usage_includes_pricing_metadata():
    def transport(url, payload, headers, timeout):
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    client = LocalOpenAIClient(
        pricing=Pricing(input_per_mtok=2.0, output_per_mtok=4.0, source_type="override"),
        transport=transport,
    )
    response = client.run([Message(role="user", content="hello")])

    assert response.usage.cost_usd == 0.00004
    assert response.usage.pricing_metadata["source_type"] == "override"
    assert response.usage.pricing_metadata["input_per_mtok"] == 2.0
