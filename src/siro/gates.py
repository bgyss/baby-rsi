"""Promotion gates — the mechanism that keeps self-improvement *bounded* (Goal 04).

These gates are the guardrail every other loop's proposals must pass
(``docs/05_evaluation_and_safety_gates.md``, ``docs/13_self_improvement_loop.md``).
Nothing here *proposes* a change; the gates only judge candidates, and a candidate
promotes only if all of them pass. Each decision is recorded as a typed
:class:`~siro.schemas.GateResult` so a rejected proposal stays auditable data.

Four gates, deliberately conservative and (mostly) static — per the goal's
constraint, the first implementation is *static scanning plus sandbox limits*, not
model-based safety review:

- **Code integrity** — fail candidates that modify tests/evaluator logic, disable
  logging, add suspicious subprocess/network behavior, or change a public function
  signature that wasn't allowed.
- **Safety** — flag candidates that use network libraries, read environment
  variables, touch files outside the sandbox, spawn uncontrolled subprocesses, or
  attempt long sleeps / fork bombs / dynamic code execution.
- **Reproducibility** — rerun the winning candidate at least twice; require
  consistent pass/fail and compatible timing before promotion.
- **Hidden tests** — run a held-out suite stored *outside* the task directory (so it
  never appears in the model prompt); a candidate that overfits the visible tests
  fails here.

The bounds these gates enforce are themselves **read-only to agents**: a loop may
never weaken what judges it. Changing gates/evaluators/tests/logging is human-gated.
"""

from __future__ import annotations

import ast
import re

from .schemas import GateDecision, GateReport, GateResult

# --------------------------------------------------------------------------- #
# Static scan: categorize suspicious constructs in candidate source.
# --------------------------------------------------------------------------- #

#: Root modules that imply network access (control plane only — never the execution plane).
NETWORK_MODULES: frozenset[str] = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "urllib2",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "nntplib",
        "xmlrpc",
        "websocket",
        "websockets",
    }
)

#: Root modules that imply spawning subprocesses or running native/uncontrolled code.
SUBPROCESS_MODULES: frozenset[str] = frozenset(
    {"subprocess", "multiprocessing", "pty", "ctypes"}
)

#: ``os.<call>`` names that spawn external processes.
_OS_SUBPROCESS_CALLS: frozenset[str] = frozenset(
    {"system", "popen", "posix_spawn", "posix_spawnp", "startfile"}
)
#: ``os.<call>`` names that fork the interpreter (fork-bomb surface).
_OS_FORK_CALLS: frozenset[str] = frozenset({"fork", "forkpty"})
#: ``os.<call>`` names that read/write process environment.
_OS_ENV_CALLS: frozenset[str] = frozenset({"getenv", "getenvb", "putenv", "putenvb"})
#: ``os.<call>`` names that mutate the filesystem.
_OS_FS_CALLS: frozenset[str] = frozenset(
    {
        "remove",
        "unlink",
        "rmdir",
        "removedirs",
        "rename",
        "replace",
        "chmod",
        "chown",
        "truncate",
        "mkdir",
        "makedirs",
    }
)

#: time/asyncio sleep at or above this (seconds) is flagged as a long sleep.
SLEEP_THRESHOLD_SECONDS: float = 5.0

#: Findings in these categories are treated as high risk by the gates.
_HIGH_RISK: frozenset[str] = frozenset(
    {
        "network",
        "subprocess",
        "fork",
        "filesystem",
        "env_read",
        "dynamic_exec",
        "modify_tests",
        "modify_evaluator",
        "disable_logging",
    }
)

#: Categories the safety gate owns.
_SAFETY_CATEGORIES: frozenset[str] = frozenset(
    {"network", "subprocess", "fork", "filesystem", "env_read", "long_sleep", "dynamic_exec"}
)
#: Categories the code-integrity gate owns (network/subprocess = "suspicious behavior").
_INTEGRITY_CATEGORIES: frozenset[str] = frozenset(
    {"modify_tests", "modify_evaluator", "disable_logging", "network", "subprocess", "signature_change"}
)

#: A finding is ``(category, human-readable detail)``.
Finding = tuple[str, str]


def _attr_chain(node: ast.AST) -> str | None:
    """Return a dotted attribute chain like ``os.path.join`` for an expression, or None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _check_open(call: ast.Call, findings: list[Finding]) -> None:
    """Flag suspicious ``open(...)`` calls (test peeking / sandbox escape / writes)."""
    path_node = call.args[0] if call.args else None
    mode = ""
    if len(call.args) >= 2:
        mode = _const_str(call.args[1]) or ""
    for kw in call.keywords:
        if kw.arg == "mode":
            mode = _const_str(kw.value) or mode
    write = any(flag in mode for flag in ("w", "a", "x", "+"))
    path = _const_str(path_node)
    if path is not None:
        if re.search(r"test", path, flags=re.IGNORECASE):
            findings.append(("modify_tests", f"opens test file '{path}'"))
        if path.startswith("/") or path.startswith("~") or ".." in path:
            findings.append(("filesystem", f"opens path outside sandbox '{path}'"))
        elif write:
            findings.append(("filesystem", f"opens '{path}' for writing"))
    elif write:
        findings.append(("filesystem", "opens a computed path for writing"))


def _check_sleep(call: ast.Call, chain: str, findings: list[Finding]) -> None:
    """Flag long or dynamic sleeps (a candidate must not stall the loop)."""
    arg = call.args[0] if call.args else None
    if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
        if arg.value >= SLEEP_THRESHOLD_SECONDS:
            findings.append(("long_sleep", f"{chain}({arg.value})"))
    else:
        findings.append(("long_sleep", f"{chain}(<dynamic>)"))


def scan(code: str) -> list[Finding]:
    """Statically scan candidate source for suspicious constructs.

    Returns deduplicated ``(category, detail)`` findings. Syntactically invalid code
    yields no findings — it can't import, so the sandbox already scores it at the
    bottom and it can never be reproducible enough to promote.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else ([node.module] if node.module else [])
            )
            for name in names:
                if not name:
                    continue
                root = name.split(".")[0]
                if root in NETWORK_MODULES:
                    findings.append(("network", f"imports '{name}'"))
                if root in SUBPROCESS_MODULES:
                    findings.append(("subprocess", f"imports '{name}'"))
                segments = set(name.split("."))
                if segments & {"evaluator", "safety", "gates"}:
                    findings.append(("modify_evaluator", f"imports '{name}'"))
                if root == "tests" or name.endswith("tests"):
                    findings.append(("modify_tests", f"imports '{name}'"))

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                fname = node.func.id
                if fname == "open":
                    _check_open(node, findings)
                elif fname in {"eval", "exec", "compile"}:
                    findings.append(("dynamic_exec", f"calls {fname}()"))
                elif fname == "__import__":
                    findings.append(("dynamic_exec", "calls __import__()"))
            chain = _attr_chain(node.func)
            if chain:
                head, _, tail = chain.partition(".")
                spawns = (head == "os" and tail in _OS_SUBPROCESS_CALLS) or chain.startswith(
                    ("os.exec", "os.spawn")
                )
                if spawns:
                    findings.append(("subprocess", f"calls {chain}()"))
                elif head == "os" and tail in _OS_FORK_CALLS:
                    findings.append(("fork", f"calls {chain}()"))
                elif head == "os" and tail in _OS_ENV_CALLS:
                    findings.append(("env_read", f"calls {chain}()"))
                elif head == "os" and tail in _OS_FS_CALLS:
                    findings.append(("filesystem", f"calls {chain}()"))
                elif head == "subprocess":
                    findings.append(("subprocess", f"calls {chain}()"))
                elif chain == "logging.disable":
                    findings.append(("disable_logging", f"calls {chain}()"))
                elif chain in {"time.sleep", "asyncio.sleep"}:
                    _check_sleep(node, chain, findings)

        elif isinstance(node, ast.Attribute):
            chain = _attr_chain(node)
            if chain in {"os.environ", "os.environb"}:
                findings.append(("env_read", f"accesses {chain}"))
            elif chain and set(chain.split(".")) & {"evaluator", "safety"}:
                findings.append(("modify_evaluator", f"references {chain}"))

        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "disabled":
                    findings.append(("disable_logging", "sets a logger's '.disabled' flag"))

    seen: set[Finding] = set()
    unique: list[Finding] = []
    for finding in findings:
        if finding not in seen:
            seen.add(finding)
            unique.append(finding)
    return unique


# --------------------------------------------------------------------------- #
# Public function signatures (the "don't change the signature" integrity check).
# --------------------------------------------------------------------------- #


def _arg_names(args: ast.arguments) -> tuple[str, ...]:
    names = [p.arg for p in (*args.posonlyargs, *args.args)]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names.extend(p.arg for p in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return tuple(names)


def function_signatures(code: str) -> dict[str, tuple[str, ...]]:
    """Map each *top-level* function name to its argument names.

    Only module-level functions are "public" for signature purposes — nested helpers
    are an implementation detail a candidate may freely introduce.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}
    return {
        node.name: _arg_names(node.args)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def signature_findings(code: str, allowed: dict[str, tuple[str, ...]]) -> list[str]:
    """Detail strings for any public function whose signature was removed or changed."""
    candidate = function_signatures(code)
    out: list[str] = []
    for name, sig in allowed.items():
        if name not in candidate:
            out.append(f"removed public function '{name}'")
        elif candidate[name] != sig:
            out.append(f"changed signature of '{name}': expected {sig}, got {candidate[name]}")
    return out


# --------------------------------------------------------------------------- #
# Gates.
# --------------------------------------------------------------------------- #


def _gate(name: str, owned: frozenset[str], findings: list[Finding]) -> GateResult:
    relevant = [(c, d) for c, d in findings if c in owned]
    if not relevant:
        return GateResult(gate=name, decision=GateDecision.PASSED, risk_level="low", notes="no findings")
    risk = "high" if any(c in _HIGH_RISK for c, _ in relevant) else "medium"
    return GateResult(
        gate=name,
        decision=GateDecision.FAILED,
        risk_level=risk,
        findings=[f"{c}: {d}" for c, d in relevant],
    )


def safety_gate(code: str) -> GateResult:
    """Gate C — flag network/env/filesystem/subprocess/fork/sleep/exec behavior."""
    return _gate("safety", _SAFETY_CATEGORIES, scan(code))


def code_integrity_gate(
    code: str, *, allowed_signatures: dict[str, tuple[str, ...]] | None = None
) -> GateResult:
    """Gate A — fail edits to tests/evaluator/logging and unauthorized signature changes."""
    findings = list(scan(code))
    if allowed_signatures:
        findings.extend(("signature_change", detail) for detail in signature_findings(code, allowed_signatures))
    return _gate("code_integrity", _INTEGRITY_CATEGORIES, findings)


def reproducibility_gate(candidate, task, sandbox, *, runs: int = 2) -> GateResult:  # noqa: ANN001
    """Gate B (reproducibility) — rerun the candidate ``>= 2`` times; require consistency.

    Promotion needs identical pass/fail counts across reruns *and* a suite that
    actually executed every time. Timing is recorded in ``notes`` (a noisy signal we
    surface but don't fail on, so CI jitter can't block a deterministic candidate).
    """
    runs = max(runs, 2)
    results = [sandbox.run(candidate, task) for _ in range(runs)]
    runtimes = [round(r.runtime_ms, 1) for r in results]
    counts = {(r.passed_tests, r.failed_tests) for r in results}
    if not all(r.ran for r in results):
        return GateResult(
            gate="reproducibility",
            decision=GateDecision.FAILED,
            risk_level="medium",
            findings=["candidate did not execute the fixed suite on every rerun"],
            notes=f"runtimes_ms={runtimes}",
        )
    if len(counts) != 1:
        return GateResult(
            gate="reproducibility",
            decision=GateDecision.FAILED,
            risk_level="high",
            findings=[f"non-reproducible results across reruns: {sorted(counts)}"],
            notes=f"runtimes_ms={runtimes}",
        )
    passed, failed = next(iter(counts))
    return GateResult(
        gate="reproducibility",
        decision=GateDecision.PASSED,
        risk_level="low",
        notes=f"{runs} reruns consistent at pass={passed} fail={failed}; runtimes_ms={runtimes}",
    )


def hidden_test_gate(candidate, task, sandbox, *, hidden_tests_path=None) -> GateResult:  # noqa: ANN001
    """Gate B (robustness) — run a held-out suite the candidate never saw.

    The hidden suite lives outside the task directory and is never placed in a model
    prompt, so a candidate that overfits the visible tests is caught here. When no
    hidden suite is configured the gate passes (it is optional, per the goal).
    """
    path = hidden_tests_path if hidden_tests_path is not None else getattr(task, "hidden_tests_path", None)
    if not path:
        return GateResult(
            gate="hidden_tests",
            decision=GateDecision.PASSED,
            risk_level="low",
            notes="no hidden tests configured",
        )
    result = sandbox.run(candidate, task, tests_path=path)
    if not result.ran:
        return GateResult(
            gate="hidden_tests",
            decision=GateDecision.FAILED,
            risk_level="medium",
            findings=[f"hidden suite did not execute: {result.error or 'no tests ran'}"],
        )
    if result.failed_tests > 0:
        return GateResult(
            gate="hidden_tests",
            decision=GateDecision.FAILED,
            risk_level="high",
            findings=[f"{result.failed_tests} hidden test(s) failed — candidate may overfit visible tests"],
        )
    return GateResult(
        gate="hidden_tests",
        decision=GateDecision.PASSED,
        risk_level="low",
        notes=f"{result.passed_tests} hidden test(s) passed",
    )


def static_gates(
    code: str, *, allowed_signatures: dict[str, tuple[str, ...]] | None = None
) -> list[GateResult]:
    """The cheap, source-only gates run on *every* attempt for audit (safety + integrity)."""
    return [safety_gate(code), code_integrity_gate(code, allowed_signatures=allowed_signatures)]


def promotion_gate(
    candidate,  # noqa: ANN001
    task,  # noqa: ANN001
    sandbox,  # noqa: ANN001
    *,
    allowed_signatures: dict[str, tuple[str, ...]] | None = None,
    runs: int = 2,
    hidden_tests_path=None,
) -> GateReport:
    """Run all gates a promotion must pass and return the combined report.

    The static gates run first; the heavier sandbox gates (reproducibility, hidden
    tests) run only while everything before them still passes — there's no point
    rerunning a candidate already rejected on integrity or safety grounds.
    """
    results = static_gates(candidate.code, allowed_signatures=allowed_signatures)
    if all(r.decision is GateDecision.PASSED for r in results):
        results.append(reproducibility_gate(candidate, task, sandbox, runs=runs))
    if all(r.decision is GateDecision.PASSED for r in results):
        results.append(hidden_test_gate(candidate, task, sandbox, hidden_tests_path=hidden_tests_path))
    return GateReport(results=results)


__all__ = [
    "Finding",
    "scan",
    "function_signatures",
    "signature_findings",
    "safety_gate",
    "code_integrity_gate",
    "reproducibility_gate",
    "hidden_test_gate",
    "static_gates",
    "promotion_gate",
    "NETWORK_MODULES",
    "SUBPROCESS_MODULES",
    "SLEEP_THRESHOLD_SECONDS",
]
