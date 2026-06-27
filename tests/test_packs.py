from __future__ import annotations

from pathlib import Path

import pytest

from siro.agents.roles import IMPLEMENTATION, build_agent
from siro.config import load_config
from siro.model_client import ScriptedModelClient
from siro.orchestrator import Orchestrator
from siro.packs import EvaluatorRegime, PackError, load_pack
from siro.research import load_research_task, run_research_eval
from siro.sandbox import Sandbox


def test_builtin_ml_pack_loads_and_narrows_only_global_tools():
    pack = load_pack("ml")
    assert pack.id == "ml"
    assert pack.regime is EvaluatorRegime.SEEDED_DETERMINISTIC
    assert {"read_allowed_file", "propose_patch"} <= pack.tools
    assert pack.tasks_dir == Path("packs/ml/tasks")


def test_default_adapter_matches_eval_py_metric():
    pack = load_pack("ml")
    task = load_research_task("packs/ml/tasks/algorithm/pair_count", pack=pack)
    metric = run_research_eval(task, task.surface_code, Sandbox())
    direct = pack.adapter.evaluate(task, task.surface_code, Sandbox())
    assert metric == direct
    assert task.pack_id == "ml"
    assert task.pack_version == pack.version
    assert task.evaluator_regime is EvaluatorRegime.SEEDED_DETERMINISTIC


def test_pack_evaluator_py_must_supply_adapter(tmp_path):
    root = tmp_path / "packs"
    bad = root / "bad"
    bad.mkdir(parents=True)
    (bad / "tasks").mkdir()
    (bad / "evaluator.py").write_text("", encoding="utf-8")
    (bad / "pack.toml").write_text(
        "\n".join(
            [
                'id = "bad"',
                'title = "Bad pack"',
                'version = "0.0.1"',
                'evaluator_regime = "exact"',
                "tier_floor = 0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PackError, match="get_adapter"):
        load_pack("bad", root=root)


def test_unknown_configured_pack_fails_closed(tmp_path):
    config_path = tmp_path / "tier0.yaml"
    config_path.write_text(
        "tier: 0\npack: missing\nproviders: {}\nagent_models: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(PackError, match="Unknown domain pack"):
        Orchestrator.from_config(load_config(config_path))


def test_pack_tool_whitelist_cannot_widen_global_tools(tmp_path):
    root = tmp_path / "packs"
    bad = root / "bad"
    bad.mkdir(parents=True)
    (bad / "tasks").mkdir()
    (bad / "evaluator.py").write_text("", encoding="utf-8")
    (bad / "pack.toml").write_text(
        "\n".join(
            [
                'id = "bad"',
                'title = "Bad pack"',
                'version = "0.0.1"',
                'evaluator_regime = "exact"',
                "tier_floor = 0",
            ]
        ),
        encoding="utf-8",
    )
    (bad / "tools.allow").write_text("read_allowed_file\nshell\n", encoding="utf-8")

    with pytest.raises(PackError, match="may only narrow"):
        load_pack("bad", root=root)


def test_pack_required_tools_cannot_widen_global_tools(tmp_path):
    root = tmp_path / "packs"
    bad = root / "bad"
    bad.mkdir(parents=True)
    (bad / "tasks").mkdir()
    (bad / "evaluator.py").write_text(
        "from siro.packs import EvalPyAdapter\n"
        "def get_adapter(regime):\n"
        "    return EvalPyAdapter(regime=regime)\n",
        encoding="utf-8",
    )
    (bad / "pack.toml").write_text(
        "\n".join(
            [
                'id = "bad"',
                'title = "Bad pack"',
                'version = "0.0.1"',
                'evaluator_regime = "exact"',
                'required_tools = ["shell"]',
                "tier_floor = 0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PackError, match="required_tools"):
        load_pack("bad", root=root)


def test_pack_prompt_override_is_optional_and_falls_back(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "implementation.md").write_text("PACK IMPLEMENTATION PROMPT", encoding="utf-8")
    agent = build_agent(
        IMPLEMENTATION,
        ScriptedModelClient(['{"code": "x = 1"}']),
        prompts_dir=prompts,
    )
    assert agent.system_prompt == "PACK IMPLEMENTATION PROMPT"

    fallback = build_agent(
        "hypothesis",
        ScriptedModelClient(['{"statement": "x"}']),
        prompts_dir=prompts,
    )
    assert fallback.system_prompt != "PACK IMPLEMENTATION PROMPT"
    assert "hypothesis" in fallback.system_prompt.lower()
