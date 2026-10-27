"""Subprocess sandbox for running untrusted circuit code (used by the MCP server).

Design (two stages, nothing user-supplied is ever executed in the server process):

1. **build**: the untrusted Python/QASM source runs in its own short-lived worker process
   (``python -I -m veriq._sandbox_worker``) and the only thing that comes back is the circuit,
   serialized as QPY. Candidate and reference are built in *separate* processes, so one cannot
   tamper with the other.
2. **analyze**: a second, fresh worker deserializes the QPY circuits and runs the Veriq checks.
   No user code runs there, so user code cannot monkeypatch the checker and forge a verdict.

Every worker gets:
  * a wall-clock timeout (the process group is SIGKILLed when it expires),
  * RLIMIT_AS (address space), RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NOFILE and RLIMIT_CORE=0,
  * a fresh temporary directory as cwd and HOME (deleted afterwards),
  * a scrubbed environment (PATH, a few thread-count variables and nothing else),
  * isolation, strongest available first:
      - ``bwrap`` (bubblewrap): read-only view of the filesystem, a private /tmp, only the job's
        temp dir writable, the user's home hidden (unless the venv lives there), new network / PID /
        IPC namespaces (so no network at all);
      - else ``unshare -rn``: new user + network namespace (no network, filesystem still visible);
      - in every case ``socket`` is disabled inside the worker before user code runs (best effort).

This is defense in depth for a *local* tool, not a hardened multi-tenant jail: run the MCP server
on your own machine, for your own agent sessions.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

MAX_SOURCE_BYTES = 200_000


@dataclass
class Limits:
    build_timeout_s: float = 30.0
    analyze_timeout_s: float = 120.0
    memory_mb: int = 3072
    max_qubits: int = 50
    max_output_bytes: int = 20_000_000
    network: bool = False  # True would skip the namespace isolation (never used by the server)

    @classmethod
    def from_env(cls) -> "Limits":
        lim = cls()
        env = os.environ
        if "VERIQ_MCP_BUILD_TIMEOUT" in env:
            lim.build_timeout_s = float(env["VERIQ_MCP_BUILD_TIMEOUT"])
        if "VERIQ_MCP_ANALYZE_TIMEOUT" in env:
            lim.analyze_timeout_s = float(env["VERIQ_MCP_ANALYZE_TIMEOUT"])
        if "VERIQ_MCP_MEMORY_MB" in env:
            lim.memory_mb = int(env["VERIQ_MCP_MEMORY_MB"])
        if "VERIQ_MCP_MAX_QUBITS" in env:
            lim.max_qubits = int(env["VERIQ_MCP_MAX_QUBITS"])
        return lim

    def to_dict(self) -> dict[str, Any]:
        return {"build_timeout_s": self.build_timeout_s, "analyze_timeout_s": self.analyze_timeout_s,
                "memory_mb": self.memory_mb, "max_qubits": self.max_qubits,
                "isolation": network_isolation_method()}


@dataclass
class SandboxResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # "timeout" | "memory" | "crash" | "protocol"
    detail: str = ""
    seconds: float = 0.0
    stderr_tail: str = ""


@lru_cache(maxsize=1)
def network_isolation_method() -> str:
    """'bwrap', 'unshare' or 'socket-patch' (in-process best effort), whichever works here."""
    if os.environ.get("VERIQ_SANDBOX_ISOLATION") in ("bwrap", "unshare", "socket-patch"):
        return os.environ["VERIQ_SANDBOX_ISOLATION"]
    bw = shutil.which("bwrap")
    if bw and sys.platform.startswith("linux"):
        try:
            r = subprocess.run([bw, "--ro-bind", "/", "/", "--dev", "/dev", "--unshare-all", "--die-with-parent",
                                "true"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return "bwrap"
        except Exception:
            pass
    exe = shutil.which("unshare")
    if exe and sys.platform.startswith("linux"):
        try:
            r = subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return "unshare"
        except Exception:
            pass
    return "socket-patch"


def _scrubbed_env(tmp: str) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": tmp,
        "TMPDIR": tmp,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "RAYON_NUM_THREADS": "2",
        "QISKIT_PARALLEL": "FALSE",
        "QISKIT_SETTINGS": os.path.join(tmp, "qiskit_settings.conf"),
        "MPLBACKEND": "Agg",
    }


def _preexec(limits: Limits, cpu_s: int):
    def fn():  # runs in the child between fork and exec
        import resource

        os.setsid()
        mem = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 5))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return fn


def run_worker(job: dict[str, Any], timeout_s: float, limits: Limits) -> SandboxResult:
    """Run one job in a fresh sandboxed worker and return its JSON result."""
    t0 = time.perf_counter()
    tmp = tempfile.mkdtemp(prefix="veriq-sbx-")
    cmd = [sys.executable, "-I", "-m", "veriq._sandbox_worker"]
    method = "none" if limits.network else network_isolation_method()
    if method == "bwrap":
        cmd = _bwrap_prefix(tmp, job.get("readable_dirs", [])) + cmd
    elif method == "unshare":
        cmd = [shutil.which("unshare") or "unshare", "-rn", "--"] + cmd
    # CPU budget: worker may use a couple of threads, so allow 2x wall time of CPU.
    cpu_s = max(5, int(timeout_s * 2) + 5)
    payload = json.dumps(dict(job, workdir=tmp)).encode()
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=tmp, env=_scrubbed_env(tmp), preexec_fn=_preexec(limits, cpu_s),
                                close_fds=True)
        try:
            out, err = proc.communicate(payload, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            out, err = proc.communicate()
            return SandboxResult(False, error="timeout",
                                 detail=f"worker exceeded the {timeout_s:g}s wall-clock limit and was killed",
                                 seconds=time.perf_counter() - t0, stderr_tail=_tail(err))
        rc = proc.returncode
        sec = time.perf_counter() - t0
        text = out[: limits.max_output_bytes].decode("utf-8", "replace").strip()
        last = text.splitlines()[-1] if text else ""
        if rc == 0 and last.startswith("{"):
            try:
                return SandboxResult(True, json.loads(last), seconds=sec, stderr_tail=_tail(err))
            except json.JSONDecodeError:
                pass
        errtxt = _tail(err)
        if rc is not None and 128 < rc < 160 and network_isolation_method() in ("bwrap", "unshare"):
            rc = -(rc - 128)  # bwrap/unshare report a child's fatal signal N as exit status 128+N
        if "MemoryError" in errtxt or "std::bad_alloc" in errtxt or "Cannot allocate memory" in errtxt:
            kind, detail = "memory", f"worker ran out of memory (limit {limits.memory_mb} MB)"
        elif rc in (-signal.SIGXCPU, -signal.SIGKILL) and "Killed" not in errtxt:
            kind, detail = "timeout", f"worker exceeded its CPU-time limit ({cpu_s}s, signal {-rc})"
        elif rc is not None and rc < 0:
            try:
                name = signal.Signals(-rc).name
            except ValueError:
                name = "unknown"
            kind, detail = "crash", f"worker killed by signal {-rc} ({name})"
        elif rc != 0:
            kind, detail = "crash", f"worker exited with code {rc}"
        else:
            kind, detail = "protocol", "worker produced no result"
        return SandboxResult(False, error=kind, detail=detail, seconds=sec, stderr_tail=errtxt)
    finally:
        if proc is not None and proc.poll() is None:
            _kill_group(proc)
        shutil.rmtree(tmp, ignore_errors=True)


def _bwrap_prefix(tmp: str, readable_dirs: list[str]) -> list[str]:
    args = [shutil.which("bwrap") or "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp"]
    home = os.path.realpath(os.path.expanduser("~"))
    needed = [os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix),
              os.path.realpath(os.path.dirname(os.path.dirname(__file__)))]
    if home not in ("/", "") and not any(n == home or n.startswith(home + os.sep) for n in needed):
        args += ["--tmpfs", home]  # hide ~/.ssh, browser profiles, tokens, ...
        for d in readable_dirs:  # a path input under $HOME stays readable
            args += ["--ro-bind", d, d]
    args += ["--bind", tmp, tmp, "--unshare-all", "--die-with-parent", "--new-session", "--chdir", tmp, "--"]
    return args


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _tail(b: bytes | None, n: int = 1500) -> str:
    if not b:
        return ""
    return b.decode("utf-8", "replace")[-n:]
