"""Execution-plane resource-isolation backends (Goal 15).

Goal 11 enforced compute ceilings with a portable controller-side monitor (parent RSS via
``ps``, process-group kill on breach). That ``local`` backend stays the **developer
fallback**, but it is best-effort: it samples RSS on a poll interval and relies on
cooperative process-group membership. For trusted Tier 2 scale-up — where
``docs/14_project_retrospective.md`` flags that "memory enforcement must be reliable before
Tier 2 compute scale-up is trusted" — we need *hard* isolation the operating system enforces.

This module factors guarded execution into a backend abstraction so the same
:meth:`siro.sandbox.Sandbox.run_guarded` contract can run on either:

- :class:`LocalGuardBackend` — portable (macOS/Linux): a hard wall-clock deadline plus a
  monitor that now sums the **whole process group's** RSS and counts its processes, so a
  child cannot fork under the radar to dodge the memory ceiling. Still best-effort (sampled,
  cooperative); it is a developer fallback, not the production isolation story.
- :class:`LinuxCgroupBackend` — hard isolation on Linux cgroup v2: ``memory.max`` +
  ``memory.swap.max=0`` (the kernel OOM-kills the cgroup on breach — enforcement, not
  sampling), ``pids.max`` (a hard process-count ceiling), peak read from ``memory.peak``, and
  an OOM detected from ``memory.events``. Network stays blocked by the sandbox's
  ``sitecustomize`` (the cross-backend guarantee); a private network namespace is added when
  ``unshare`` is available as defense in depth.

Plane isolation is never relaxed by a bigger budget, and **a candidate never chooses the
backend or the limits** — :mod:`siro.scale` policy and config do, on the control plane.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

#: Mount point of the cgroup v2 unified hierarchy on Linux.
CGROUP_ROOT = Path("/sys/fs/cgroup")


class BackendUnavailable(RuntimeError):
    """Raised when a requested isolation backend is not usable in this environment."""


@dataclass(frozen=True)
class ResourceLimits:
    """The hard ceilings for one guarded execution. ``None`` means that limit is unbounded."""

    wall_clock_seconds: float
    memory_mb: int | None = None
    max_processes: int | None = None
    poll_interval: float = 0.05


@dataclass(frozen=True)
class GuardExec:
    """Raw outcome of a guarded subprocess run, before metric parsing.

    ``timed_out`` / ``memory_exceeded`` / ``process_exceeded`` flag *which* hard ceiling was
    breached; ``peak_memory_mb`` is the observed peak (process-tree on the local backend,
    ``memory.peak`` on the cgroup backend); ``backend`` records which backend ran it (audit).
    """

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    memory_exceeded: bool = False
    process_exceeded: bool = False
    peak_memory_mb: float = 0.0
    backend: str = "local"

    @property
    def breached(self) -> bool:
        return self.timed_out or self.memory_exceeded or self.process_exceeded


# --- shared subprocess helpers ---------------------------------------------


def _kill_process_group(proc: "subprocess.Popen") -> None:
    """Hard-kill a child and its process group (started with ``start_new_session=True``)."""
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _drain(proc: "subprocess.Popen") -> tuple[str, str]:
    """Collect remaining output from a killed child without blocking forever."""
    try:
        out, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        out, err = "", ""
    return out or "", err or ""


def _process_group_stats(pgid: int) -> tuple[float, int] | None:
    """Return ``(total_rss_mb, process_count)`` for every process in group ``pgid``.

    ``ps -e -o pgid=,rss=`` lists all processes with their group id and resident set size
    (KB on both macOS and Linux). Summing by group id counts the **whole process tree** — a
    child that forks to spread its allocation cannot stay under the ceiling, which a parent-RSS
    probe would miss. Returns ``None`` if ``ps`` fails or the group has already exited.
    """
    try:
        out = subprocess.run(
            ["ps", "-e", "-o", "pgid=,rss="], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return None
    total_kb = 0
    count = 0
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            group = int(parts[0])
            rss = int(parts[1])
        except ValueError:
            continue
        if group == pgid:
            total_kb += rss
            count += 1
    if count == 0:
        return None
    return total_kb / 1024.0, count


class GuardBackend:
    """Abstract resource-isolation backend. Subclasses enforce limits for one execution."""

    name: str = "base"
    is_hard: bool = False

    def available(self) -> tuple[bool, str]:
        """Return ``(usable, reason)`` for this environment."""
        raise NotImplementedError

    def run(
        self, cmd: list[str], *, cwd: Path, env: dict, limits: ResourceLimits
    ) -> GuardExec:
        """Run ``cmd`` under ``limits`` and return its :class:`GuardExec`."""
        raise NotImplementedError


class LocalGuardBackend(GuardBackend):
    """Portable, best-effort isolation: process-group monitor + hard wall-clock kill.

    Always available. The developer fallback — sampled and cooperative, not OS-enforced — but
    it now accounts for the whole process group's memory and process count, so a forked child
    cannot dodge the ceiling.
    """

    name = "local"
    is_hard = False

    def available(self) -> tuple[bool, str]:
        return True, "portable process-group monitor (developer fallback)"

    def run(
        self, cmd: list[str], *, cwd: Path, env: dict, limits: ResourceLimits
    ) -> GuardExec:
        deadline = time.perf_counter() + limits.wall_clock_seconds
        # start_new_session=True ⇒ the child leads a new process group we can kill wholesale
        # and sum/count by group id.
        proc = subprocess.Popen(  # noqa: S603 - fixed controller-built command
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = proc.pid

        peak_mb = 0.0
        timed_out = memory_exceeded = process_exceeded = False
        while True:
            if proc.poll() is not None:
                break
            if time.perf_counter() >= deadline:
                timed_out = True
                break
            stats = _process_group_stats(pgid)
            if stats is not None:
                rss_mb, nproc = stats
                peak_mb = max(peak_mb, rss_mb)
                if limits.memory_mb is not None and rss_mb > limits.memory_mb:
                    memory_exceeded = True
                    break
                if limits.max_processes is not None and nproc > limits.max_processes:
                    process_exceeded = True
                    break
            time.sleep(limits.poll_interval)

        if timed_out or memory_exceeded or process_exceeded:
            _kill_process_group(proc)
            out, err = _drain(proc)
            return GuardExec(
                -1, out, err, timed_out, memory_exceeded, process_exceeded, peak_mb, self.name
            )
        out, err = proc.communicate()
        return GuardExec(proc.returncode, out or "", err or "", peak_memory_mb=peak_mb, backend=self.name)


# --- Linux cgroup v2 hard backend ------------------------------------------


def _cgroup_v2_root() -> Path | None:
    """Return the cgroup v2 unified-hierarchy root, or ``None`` if not mounted."""
    return CGROUP_ROOT if (CGROUP_ROOT / "cgroup.controllers").is_file() else None


def _current_cgroup_dir(root: Path) -> Path:
    """The cgroup directory of the current process (the writable base for child cgroups)."""
    line = Path("/proc/self/cgroup").read_text(encoding="utf-8").strip()
    rel = line.split("::", 1)[1] if "::" in line else "/"
    return root / rel.lstrip("/")


def _read_controllers(path: Path) -> set[str]:
    try:
        return set((path / "cgroup.controllers").read_text(encoding="utf-8").split())
    except OSError:
        return set()


def _enable_subtree(base: Path, controllers: tuple[str, ...]) -> None:
    """Delegate ``controllers`` to ``base``'s children (no-op if already enabled).

    Raises :class:`OSError` if the kernel refuses (e.g. the no-internal-process rule when the
    base cgroup holds processes and is not the namespace root) — the caller treats that as
    "hard backend unavailable here".
    """
    control = base / "cgroup.subtree_control"
    try:
        current = control.read_text(encoding="utf-8").split()
    except OSError:
        current = []
    missing = [c for c in controllers if c not in current]
    if missing:
        control.write_text(" ".join(f"+{c}" for c in missing), encoding="utf-8")


def _parse_events(path: Path, key: str) -> int:
    """Read a ``key N`` counter from a cgroup ``*.events`` flat-keyed file (0 if absent)."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == key:
                return int(parts[1])
    except (OSError, ValueError):
        return 0
    return 0


def _cgroup_peak_mb(cg: Path) -> float:
    """Best peak memory in MB: ``memory.peak`` if the kernel exposes it, else current."""
    for name in ("memory.peak", "memory.current"):
        try:
            return int((cg / name).read_text(encoding="utf-8").strip()) / (1024.0 * 1024.0)
        except (OSError, ValueError):
            continue
    return 0.0


def _kill_cgroup_members(cg: Path) -> None:
    try:
        pids = (cg / "cgroup.procs").read_text(encoding="utf-8").split()
    except OSError:
        return
    for pid in pids:
        try:
            os.kill(int(pid), 9)
        except (OSError, ValueError):
            pass


def _remove_cgroup(cg: Path) -> None:
    _kill_cgroup_members(cg)
    for _ in range(5):
        try:
            cg.rmdir()
            return
        except OSError:
            time.sleep(0.02)


def _unshare_net_available() -> bool:
    """Whether ``unshare --net`` works here (real empty netns; defense in depth)."""
    try:
        proc = subprocess.run(
            ["unshare", "--net", "true"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


class LinuxCgroupBackend(GuardBackend):
    """Hard isolation on Linux cgroup v2: kernel-enforced memory and process ceilings.

    Available only on Linux with a cgroup v2 unified hierarchy whose ``memory`` and ``pids``
    controllers can be delegated to a child cgroup (the common case inside a container with a
    private cgroup namespace). Where delegation is refused, :meth:`available` reports the
    reason and the caller skips/refuses rather than silently downgrading.
    """

    name = "linux_guarded"
    is_hard = True

    def available(self) -> tuple[bool, str]:
        if platform.system() != "Linux":
            return False, "linux_guarded backend requires Linux"
        root = _cgroup_v2_root()
        if root is None:
            return False, "cgroup v2 unified hierarchy not mounted at /sys/fs/cgroup"
        controllers = _read_controllers(root)
        for needed in ("memory", "pids"):
            if needed not in controllers:
                return False, f"cgroup controller {needed!r} unavailable"
        try:
            probe = self._create_cgroup(root)
        except OSError as exc:
            return False, f"cannot create a delegated cgroup: {exc}"
        _remove_cgroup(probe)
        return True, "cgroup v2 memory+pids enforcement available"

    def _create_cgroup(self, root: Path) -> Path:
        base = _current_cgroup_dir(root)
        _enable_subtree(base, ("memory", "pids"))
        child = base / f"siro-guard-{uuid.uuid4().hex[:12]}"
        child.mkdir()
        return child

    def _apply_limits(self, cg: Path, limits: ResourceLimits) -> None:
        if limits.memory_mb is not None:
            (cg / "memory.max").write_text(str(int(limits.memory_mb) * 1024 * 1024), encoding="utf-8")
            try:  # deny swap so a memory breach is a real OOM, not silent paging
                (cg / "memory.swap.max").write_text("0", encoding="utf-8")
            except OSError:
                pass
        if limits.max_processes is not None:
            (cg / "pids.max").write_text(str(int(limits.max_processes)), encoding="utf-8")

    def run(
        self, cmd: list[str], *, cwd: Path, env: dict, limits: ResourceLimits
    ) -> GuardExec:
        root = _cgroup_v2_root()
        if root is None:
            raise BackendUnavailable("cgroup v2 not available")
        cg = self._create_cgroup(root)
        procs_file = str(cg / "cgroup.procs")

        def _join_cgroup() -> None:  # runs in the child, after fork, before exec
            with open(procs_file, "w", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))

        launch = list(cmd)
        if _unshare_net_available():
            # A real empty network namespace; the sitecustomize blocker remains as well.
            launch = ["unshare", "--net", "--", *cmd]

        try:
            deadline = time.perf_counter() + limits.wall_clock_seconds
            self._apply_limits(cg, limits)
            proc = subprocess.Popen(  # noqa: S603 - fixed controller-built command
                launch, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True, preexec_fn=_join_cgroup,
            )
            peak_mb = 0.0
            timed_out = False
            while True:
                if proc.poll() is not None:
                    break
                if time.perf_counter() >= deadline:
                    timed_out = True
                    break
                peak_mb = max(peak_mb, _cgroup_peak_mb(cg))
                time.sleep(limits.poll_interval)
            peak_mb = max(peak_mb, _cgroup_peak_mb(cg))

            if timed_out:
                _kill_process_group(proc)
                out, err = _drain(proc)
                return GuardExec(-1, out, err, timed_out=True, peak_memory_mb=peak_mb, backend=self.name)

            out, err = proc.communicate()
            memory_exceeded = _parse_events(cg / "memory.events", "oom_kill") > 0
            process_exceeded = _parse_events(cg / "pids.events", "max") > 0
            return GuardExec(
                proc.returncode, out or "", err or "",
                memory_exceeded=memory_exceeded, process_exceeded=process_exceeded,
                peak_memory_mb=peak_mb, backend=self.name,
            )
        finally:
            _remove_cgroup(cg)


#: The built-in backends, keyed by the name used in config/policy.
BACKENDS: dict[str, type[GuardBackend]] = {
    LocalGuardBackend.name: LocalGuardBackend,
    LinuxCgroupBackend.name: LinuxCgroupBackend,
}


def get_backend(name: str) -> GuardBackend:
    """Instantiate a backend by name (no availability check)."""
    try:
        return BACKENDS[name]()
    except KeyError:
        raise BackendUnavailable(
            f"unknown sandbox backend {name!r}; known: {sorted(BACKENDS)}"
        ) from None


def available_backends() -> dict[str, tuple[bool, str]]:
    """Map every backend name to its ``(usable, reason)`` in this environment."""
    return {name: cls().available() for name, cls in BACKENDS.items()}


def resolve_backend(
    name: str = "local", *, require_hard: bool = False, allow_local_dev: bool = False
) -> GuardBackend:
    """Pick a usable backend, enforcing the hard-isolation policy.

    Raises :class:`BackendUnavailable` if the named backend is not usable here, or if
    ``require_hard`` is set but the chosen backend is not hard and ``allow_local_dev`` was not
    explicitly granted (so a Tier 2 scaled run cannot silently fall back to the portable
    developer monitor).
    """
    backend = get_backend(name)
    usable, reason = backend.available()
    if not usable:
        raise BackendUnavailable(f"sandbox backend {name!r} is unavailable: {reason}")
    if require_hard and not backend.is_hard and not allow_local_dev:
        raise BackendUnavailable(
            f"sandbox backend {name!r} is not a hard-isolation backend; a hard backend is "
            "required for this compute tier (set compute.allow_local_dev to override for "
            "local development only)"
        )
    return backend


__all__ = [
    "CGROUP_ROOT",
    "BackendUnavailable",
    "ResourceLimits",
    "GuardExec",
    "GuardBackend",
    "LocalGuardBackend",
    "LinuxCgroupBackend",
    "BACKENDS",
    "get_backend",
    "available_backends",
    "resolve_backend",
]
