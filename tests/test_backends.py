"""Goal 15 — resource-isolation backends.

Split into two groups, as the goal requires:

- **Portable local backend** tests run everywhere (the developer fallback). They exercise
  the process-*group* monitor: a child cannot fork to dodge the memory or process-count
  ceiling, and the wall-clock deadline always halts.
- **Hard-isolation** tests (``linux_guarded``) run only when the cgroup v2 backend is actually
  available; otherwise they skip with a clear reason. There they assert the *kernel* enforces
  the memory and process ceilings (OOM-kill / pids.max), not a sampled monitor.
"""

from __future__ import annotations

import os
import sys
import textwrap

import pytest

from siro.backends import (
    BackendUnavailable,
    LocalGuardBackend,
    ResourceLimits,
    available_backends,
    get_backend,
    resolve_backend,
)
from siro.safety import scrub_execution_env

_HARD = get_backend("linux_guarded")
_HARD_OK, _HARD_REASON = _HARD.available()
hard_only = pytest.mark.skipif(not _HARD_OK, reason=f"linux_guarded unavailable: {_HARD_REASON}")


def _run(backend, script: str, tmp_path, *, wall_clock=10.0, memory_mb=None, max_processes=None):
    """Write ``script`` to a temp file and run it under ``backend`` with the given ceilings."""
    path = tmp_path / "prog.py"
    path.write_text(textwrap.dedent(script), encoding="utf-8")
    limits = ResourceLimits(
        wall_clock_seconds=wall_clock, memory_mb=memory_mb, max_processes=max_processes
    )
    return backend.run(
        [sys.executable, str(path)], cwd=tmp_path, env=scrub_execution_env(), limits=limits
    )


# --- backend registry + policy ---------------------------------------------


def test_local_backend_always_available_and_soft():
    backend = get_backend("local")
    usable, _reason = backend.available()
    assert usable is True
    assert backend.is_hard is False


def test_available_backends_lists_both():
    names = available_backends()
    assert set(names) == {"local", "linux_guarded"}
    assert names["local"][0] is True


def test_get_unknown_backend_raises():
    with pytest.raises(BackendUnavailable, match="unknown sandbox backend"):
        get_backend("nope")


def test_resolve_require_hard_refuses_portable_backend():
    # A hard backend is required, only the portable one is available, no dev override → refuse.
    with pytest.raises(BackendUnavailable, match="not a hard-isolation backend"):
        resolve_backend("local", require_hard=True)


def test_resolve_require_hard_allows_local_dev_override():
    backend = resolve_backend("local", require_hard=True, allow_local_dev=True)
    assert backend.name == "local"


# --- portable local backend: process-group accounting ----------------------


def test_local_clean_run_reports_metrics(tmp_path):
    result = _run(
        LocalGuardBackend(),
        "import json\nprint(json.dumps({'primary': 1.0, 'passed': True}))\n",
        tmp_path,
    )
    assert not result.breached
    assert result.returncode == 0
    assert "'primary'" in result.stdout or '"primary"' in result.stdout
    assert result.backend == "local"


def test_local_wall_clock_deadline_halts(tmp_path):
    result = _run(LocalGuardBackend(), "import time\ntime.sleep(5)\n", tmp_path, wall_clock=0.5)
    assert result.timed_out and result.breached


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_local_memory_ceiling_counts_forked_children(tmp_path):
    """A parent that stays small but forks memory-hungry children must still trip the ceiling.

    Parent RSS alone would never exceed 64MB; only summing the whole process group catches the
    ~160MB held across the children. This is the process-tree accounting the goal requires.
    """
    script = """
        import os, time
        for _ in range(4):
            if os.fork() == 0:
                blob = bytearray(40 * 1024 * 1024)  # ~40MB resident, zero-filled
                time.sleep(3)
                os._exit(0)
        time.sleep(3)
    """
    result = _run(LocalGuardBackend(), script, tmp_path, wall_clock=10.0, memory_mb=64)
    assert result.memory_exceeded
    assert result.peak_memory_mb > 64


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_local_process_ceiling_counts_forked_children(tmp_path):
    script = """
        import os, time
        for _ in range(6):
            if os.fork() == 0:
                time.sleep(3)
                os._exit(0)
        time.sleep(3)
    """
    result = _run(LocalGuardBackend(), script, tmp_path, wall_clock=10.0, max_processes=3)
    assert result.process_exceeded


# --- hard isolation (Linux cgroup v2): kernel-enforced ----------------------


@hard_only
def test_hard_backend_is_hard():
    assert get_backend("linux_guarded").is_hard is True


@hard_only
def test_hard_memory_breach_is_oom_killed(tmp_path):
    script = "x = bytearray(400 * 1024 * 1024)\nimport json; print(json.dumps({'primary': 1.0}))\n"
    result = _run(_HARD, script, tmp_path, wall_clock=15.0, memory_mb=64)
    assert result.memory_exceeded


@hard_only
def test_hard_process_breach_hits_pids_max(tmp_path):
    script = """
        import os, time
        for _ in range(50):
            try:
                if os.fork() == 0:
                    time.sleep(2); os._exit(0)
            except OSError:
                pass
        time.sleep(1)
    """
    result = _run(_HARD, script, tmp_path, wall_clock=15.0, max_processes=4)
    assert result.process_exceeded


@hard_only
def test_hard_clean_run_reports_metrics(tmp_path):
    result = _run(
        _HARD,
        "import json\nprint(json.dumps({'primary': 1.0, 'passed': True}))\n",
        tmp_path,
        memory_mb=256,
        max_processes=16,
    )
    assert not result.breached and result.returncode == 0
