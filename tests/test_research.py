"""Goal 09 — research-shaped task suite + evaluation harness, fully offline.

The org runs with scripted clients (no network, no server, no credentials), simulating
distinct providers to keep the cross-model-review invariant exercised. The task evaluators
run in the real offline sandbox — they are the authority for promotion.
"""

from __future__ import annotations

import json

import pytest

from siro.agents.roles import MODEL_ROLES, build_agent
from siro.archive import ModelCallLedger
from siro.memory import ResearchMemory
from siro.model_client import ScriptedModelClient
from siro.orchestrator import Orchestrator
from siro.research import (
    ResearchArchive,
    discover_research_tasks,
    entry_from_research_attempt,
    load_research_task,
    research_improves,
    research_reproducibility_gate,
    run_research_eval,
    summarize_research,
)
from siro.sandbox import Sandbox
from siro.schemas import AttemptStatus, GateDecision, MetricRecord, ResearchAttempt

ALGO = "tasks/research/algorithm/pair_count"
TRAIN = "tasks/research/training/tiny_mlp"
POLICY = "tasks/research/policy/sentiment_rules"

# Known-good candidates per family (objective improvements over each seed).
ALGO_GOOD = (
    "def count_pairs(nums, target):\n"
    "    seen = {}\n"
    "    count = 0\n"
    "    for v in nums:\n"
    "        count += seen.get(target - v, 0)\n"
    "        seen[v] = seen.get(v, 0) + 1\n"
    "    return count\n"
)
TRAIN_GOOD = "CONFIG = {'learning_rate': 0.2, 'epochs': 60, 'hidden_size': 8, 'batch_size': 16, 'seed': 0}\n"
POLICY_GOOD = (
    "POS = {'great','loved','wonderful','fun','brilliant','moving','delicious','excellent',"
    "'enjoyed','recommend','fantastic','charming','delightful','perfectly','happy','amazing',"
    "'inspiring','good','satisfying','warm','clever','funny','best'}\n"
    "NEG = {'terrible','boring','hated','waste','cold','disgusting','awful','dull','slow',"
    "'poorly','broke','disappointing','forgettable','cheap','ugly','badly','worst','frustrating'}\n"
    "def classify(text):\n"
    "    words = text.lower().replace(',', ' ').split()\n"
    "    score = 0\n"
    "    for i, w in enumerate(words):\n"
    "        if w in POS:\n"
    "            score += -1 if i > 0 and words[i-1] == 'not' else 1\n"
    "        elif w in NEG:\n"
    "            score -= 1\n"
    "    return 1 if score > 0 else 0\n"
)


# --- task loading -----------------------------------------------------------


def test_discover_finds_three_families():
    tasks = discover_research_tasks()
    families = {t.family for t in tasks}
    assert {"algorithm", "training", "policy"} <= families


def test_load_task_exposes_only_agent_visible_surface():
    task = load_research_task(ALGO)
    assert task.edit_surface == "solution.py"
    assert "count_pairs" in task.surface_code
    assert task.hidden_dir is not None  # held-out data exists
    # The brief (the only agent-visible text) must not contain the held-out labels.
    assert "expected" not in task.brief


# --- the evaluation harness is the authority (per family) -------------------


@pytest.mark.parametrize(
    "task_dir, candidate",
    [(ALGO, ALGO_GOOD), (TRAIN, TRAIN_GOOD), (POLICY, POLICY_GOOD)],
)
def test_each_family_improves_reproducibly(task_dir, candidate):
    sandbox = Sandbox()
    task = load_research_task(task_dir)
    baseline = run_research_eval(task, task.surface_code, sandbox)
    cand = run_research_eval(task, candidate, sandbox)
    assert baseline.passed and cand.passed
    improved, _ = research_improves(cand, baseline)
    assert improved
    repro = research_reproducibility_gate(task, candidate, sandbox)
    assert repro.decision is GateDecision.PASSED


def test_seed_is_reproducible_but_not_an_improvement_over_itself():
    sandbox = Sandbox()
    task = load_research_task(ALGO)
    seed = run_research_eval(task, task.surface_code, sandbox)
    improved, why = research_improves(seed, seed)
    assert not improved and "no improvement" in why


def test_fast_but_wrong_candidate_cannot_win():
    # Returns a constant: cheap to execute, but wrong — must fail the precondition.
    sandbox = Sandbox()
    task = load_research_task(ALGO)
    wrong = "def count_pairs(nums, target):\n    return 0\n"
    baseline = run_research_eval(task, task.surface_code, sandbox)
    cand = run_research_eval(task, wrong, sandbox)
    assert not cand.passed
    improved, why = research_improves(cand, baseline)
    assert not improved and "precondition" in why


def test_improves_respects_metric_direction():
    # Higher-is-better: larger primary wins. Lower-is-better: smaller primary wins.
    hi_lo = MetricRecord(primary_name="acc", higher_is_better=True, passed=True, primary=0.6)
    hi_hi = MetricRecord(primary_name="acc", higher_is_better=True, passed=True, primary=0.9)
    assert research_improves(hi_hi, hi_lo)[0]
    assert not research_improves(hi_lo, hi_hi)[0]
    lo_hi = MetricRecord(primary_name="loss", higher_is_better=False, passed=True, primary=0.9)
    lo_lo = MetricRecord(primary_name="loss", higher_is_better=False, passed=True, primary=0.2)
    assert research_improves(lo_lo, lo_hi)[0]
    assert not research_improves(lo_hi, lo_lo)[0]


# --- the org runs the full lifecycle on a research task ----------------------


def _responses(**overrides):
    base = {
        "hypothesis": {
            "statement": "use a single-pass hashmap",
            "proposed_experiment": "replace the nested loop with dict counting",
            "required_metrics": ["executed_lines"],
            "predicted_result": "far fewer executed lines",
            "expected_failure": "none",
        },
        "literature": {"novelty": "incremental", "is_duplicate": False, "prior_art": "two-sum"},
        "implementation": {"code": ALGO_GOOD, "implementation_notes": "hashmap"},
        "evaluation": {"pass_fail": True, "regression_report": "executed lines dropped"},
        "safety": {"classification": "safe", "escalate": False},
        "interpretation": {"result_summary": "works", "confidence": 0.9, "follow_up_experiments": ["try Counter"]},
        "memory": {"strategy": "hashmap", "lessons_learned": ["O(n) beats O(n^2)"], "retrieval_tags": ["pairs"], "follow_up": "explore Counter"},
        "meta_research": {"proposed_change": "surface more lessons", "target": "retrieval_limit", "rollback_plan": "revert"},
    }
    base.update(overrides)
    return {role: json.dumps(payload) for role, payload in base.items()}


def _org(tmp_path, *, responses=None, require_cross_model=True, safety_provider="openai"):
    responses = responses or _responses()
    mem = ResearchMemory(tmp_path / "memory.jsonl")
    agents = {}
    for role in MODEL_ROLES:
        provider = safety_provider if role == "safety" else "anthropic"
        agents[role] = build_agent(
            role,
            ScriptedModelClient([responses[role]], provider=provider, model=provider),
            memory=mem,
            task_id="pair_count",
            allowed_surfaces=[f"{ALGO}/baseline/solution.py"],
        )
    orch = Orchestrator(
        agents,
        memory=mem,
        ledger=ModelCallLedger(tmp_path / "model_calls.jsonl"),
        research_archive=ResearchArchive(tmp_path / "research_attempts.jsonl"),
        require_cross_model=require_cross_model,
    )
    return orch, mem


def test_full_research_cycle_promotes_on_objective_evaluator(tmp_path):
    orch, mem = _org(tmp_path)
    result = orch.run_research_cycle("Make count_pairs cheaper", ALGO)
    assert result.promotion_decision is GateDecision.PASSED
    assert result.promoted
    assert result.metric.passed and result.metric.primary < result.baseline_metric.primary
    assert set(result.agent_outputs) == set(MODEL_ROLES)
    # Memory written through the curator (negative + positive results are first-class).
    entries = mem.all_entries()
    assert len(entries) == 1 and entries[0].strategy == "hashmap"


def test_every_model_call_logged_and_attempt_archived(tmp_path):
    orch, _ = _org(tmp_path)
    orch.run_research_cycle("obj", ALGO)
    assert len(ModelCallLedger(tmp_path / "model_calls.jsonl").read_all()) == len(MODEL_ROLES)
    attempts = ResearchArchive(tmp_path / "research_attempts.jsonl").read_all()
    assert len(attempts) == 1 and attempts[0].family == "algorithm"


def test_objective_evaluator_overrides_model_self_judgment(tmp_path):
    # Model proposes the unchanged seed (no improvement) but the eval agent claims pass;
    # the objective evaluator is authoritative, so it is rejected, not promoted.
    seed = load_research_task(ALGO).surface_code
    responses = _responses(implementation={"code": seed})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_research_cycle("obj", ALGO)
    assert result.promotion_decision is GateDecision.FAILED
    assert "no improvement" in result.attempt.reason


def test_safety_disagreement_escalates_instead_of_promoting(tmp_path):
    responses = _responses(safety={"classification": "unsafe", "escalate": True})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_research_cycle("obj", ALGO)
    assert result.promotion_decision is GateDecision.ESCALATED
    assert not result.promoted
    assert result.attempt.status is AttemptStatus.REJECTED


def test_candidate_reading_hidden_data_is_blocked_before_execution(tmp_path):
    # The held-out data lives outside the candidate cwd; the only way to reach it is the
    # SIRO_HIDDEN_PATH env var, and reading it from candidate code trips the static safety
    # gate (env_read) before any sandbox run — leakage is enforced, not assumed.
    leak = (
        "import os\n"
        "def count_pairs(nums, target):\n"
        "    open(os.environ['SIRO_HIDDEN_PATH'])\n"
        "    return 0\n"
    )
    responses = _responses(implementation={"code": leak})
    orch, _ = _org(tmp_path, responses=responses)
    result = orch.run_research_cycle("obj", ALGO)
    assert result.promotion_decision is GateDecision.FAILED
    assert result.metric is None  # never executed — blocked by the static gate


def test_no_relative_hidden_file_in_candidate_cwd():
    # There is no `_hidden.json` for the candidate to open by a relative name: a candidate
    # that tries gets a runtime error inside eval.py, never the held-out data.
    sandbox = Sandbox()
    task = load_research_task(ALGO)
    peeking = (
        "import json\n"
        "def count_pairs(nums, target):\n"
        "    with open('_hidden.json') as fh:\n"
        "        json.load(fh)\n"
        "    return 0\n"
    )
    metric = run_research_eval(task, peeking, sandbox)
    assert not metric.passed  # the relative open raises; no leakage, no pass


def test_same_provider_safety_refused_when_required(tmp_path):
    orch, _ = _org(tmp_path, safety_provider="anthropic", require_cross_model=True)
    with pytest.raises(ValueError, match="Cross-model review"):
        orch.run_research_cycle("obj", ALGO)


# --- suite summary ----------------------------------------------------------


def _attempt(family, task_id, code, *, primary, passed, status, reason="", gates=None):
    from siro.schemas import Candidate, GateReport

    metric = MetricRecord(primary_name="m", primary=primary, passed=passed, reproducible=passed)
    report = GateReport(results=gates) if gates is not None else None
    return ResearchAttempt(
        attempt_id=task_id + code[-1],
        task_id=task_id,
        family=family,
        candidate=Candidate(candidate_id="c" + code[-1], task_id=task_id, code=code),
        metric=metric,
        status=status,
        reason=reason,
        gates=report,
    )


def test_summarize_reports_per_family(tmp_path):
    from siro.schemas import GateResult, ModelCall

    attempts = [
        _attempt("algorithm", "pair_count", "code_a", primary=400, passed=True, status=AttemptStatus.PROMOTED),
        _attempt("algorithm", "pair_count", "code_b", primary=0, passed=False, status=AttemptStatus.REJECTED, reason="failed",
                 gates=[GateResult(gate="safety", decision=GateDecision.FAILED, findings=["network"])]),
        _attempt("policy", "sentiment_rules", "code_c", primary=0.9, passed=True, status=AttemptStatus.PROMOTED),
    ]
    ledger = [ModelCall(provider="anthropic", model="m", prompt_hash="h", input_tokens=10, output_tokens=5, experiment_id="pair_count")]
    summ = summarize_research(attempts, ledger_rows=ledger)
    algo = summ["algorithm"]
    assert algo.attempts == 2 and algo.promoted == 1
    assert algo.pass_rate == 0.5
    assert algo.safety_gate_failures == 1
    assert algo.tokens == 15  # attributed to the family by task id
    assert algo.strategy_diversity == 1.0  # two distinct candidate codes
    assert summ["policy"].pass_rate == 1.0


def test_entry_from_attempt_keeps_negative_results():
    attempt = _attempt("algorithm", "pair_count", "code_x", primary=0, passed=False, status=AttemptStatus.REJECTED, reason="2 test(s) failing")
    entry = entry_from_research_attempt(attempt)
    assert entry.task_id == "pair_count"
    assert entry.status is AttemptStatus.REJECTED
    assert entry.score == 0.0  # failed candidates score 0 for selection, but are recorded
