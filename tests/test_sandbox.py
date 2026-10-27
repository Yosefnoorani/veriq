"""The sandbox that runs untrusted circuit code: limits, isolation, failure modes."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from veriq.sandbox import Limits, network_isolation_method, run_worker

ROOT = Path(__file__).resolve().parents[1]
GOOD = "from qiskit import QuantumCircuit\n\ndef build():\n    qc = QuantumCircuit(2)\n    qc.h(0)\n    qc.cx(0, 1)\n    return qc\n"


def build(code, **lim):
    return run_worker({"op": "build", "source": {"code": code}}, lim.pop("timeout", 30), Limits(**lim))


def test_build_ok_returns_qpy_only():
    r = build("print('hello from user code')\n" + GOOD)
    assert r.ok and r.data["status"] == "ok" and r.data["num_qubits"] == 2
    assert r.data["qpy"] and "hello from user code" in r.data["stdout"]


def test_build_qasm():
    r = build('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n')
    assert r.ok and r.data["status"] == "ok" and r.data["num_qubits"] == 2


def test_user_exception_is_build_error():
    r = build("def build():\n    raise ValueError('nope')\n")
    assert r.ok and r.data["status"] == "build_error" and r.data["exception"] == "ValueError"


def test_wall_clock_timeout_kills_worker():
    t0 = time.perf_counter()
    r = build("while True:\n    pass\n", timeout=4)
    assert not r.ok and r.error == "timeout"
    assert time.perf_counter() - t0 < 15


def test_timeout_kills_child_processes():
    marker = "987654"
    code = f"import subprocess\nsubprocess.Popen(['sleep', '{marker}'])\nwhile True:\n    pass\n"
    r = build(code, timeout=4)
    assert not r.ok and r.error == "timeout"
    time.sleep(0.5)
    ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    assert f"sleep {marker}" not in ps


def test_memory_limit():
    r = build("x = bytearray(6 * 1024**3)\n" + GOOD, memory_mb=2048)
    assert r.ok and r.data["status"] == "build_error" and r.data["exception"] == "MemoryError"


def test_native_crash_is_reported():
    r = build("import ctypes\nctypes.string_at(0)\n")
    assert not r.ok and r.error == "crash" and "signal" in r.detail


def test_hard_exit_is_reported():
    r = build("import os\nos._exit(7)\n")
    assert not r.ok and r.error == "crash" and "code 7" in r.detail


def test_network_blocked_even_with_raw_socket():
    code = ("import _socket\ns = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)\ns.settimeout(3)\n"
            "s.connect(('1.1.1.1', 80))\n" + GOOD)
    r = build(code)
    if network_isolation_method() == "socket-patch":
        pytest.skip("no namespace isolation on this machine; only the socket patch applies")
    assert r.ok and r.data["status"] == "build_error" and r.data["exception"] in ("OSError", "TimeoutError")


def test_socket_module_patched():
    r = build("import socket\nsocket.create_connection(('example.com', 80))\n" + GOOD)
    assert r.ok and r.data["status"] == "build_error" and r.data["exception"] == "PermissionError"


def test_env_is_scrubbed(monkeypatch):
    monkeypatch.setenv("VERIQ_TEST_SECRET_TOKEN", "s3cr3t-value")
    r = build("import os\nprint(sorted(os.environ.items()))\nprint('CWD', os.getcwd())\n" + GOOD)
    assert r.ok and r.data["status"] == "ok"
    out = r.data["stdout"]
    assert "s3cr3t-value" not in out and "VERIQ_TEST_SECRET_TOKEN" not in out
    assert "veriq-sbx-" in out  # cwd/HOME is the private temp dir


@pytest.mark.skipif(network_isolation_method() != "bwrap", reason="read-only filesystem needs bwrap")
def test_filesystem_read_only_outside_workdir():
    target = ROOT / "pwned_by_sandbox.txt"
    r = build(f"open({str(target)!r}, 'w').write('x')\n" + GOOD)
    assert r.ok and r.data["status"] == "build_error" and r.data["exception"] == "OSError"
    assert not target.exists()


@pytest.mark.skipif(network_isolation_method() != "bwrap", reason="home hiding needs bwrap")
def test_home_directory_hidden():
    home = os.path.realpath(os.path.expanduser("~"))
    if str(ROOT).startswith(home + os.sep):
        pytest.skip("project lives under $HOME, so it stays visible")
    r = build(f"import os\nprint('HOME_LIST', os.listdir({home!r}))\n" + GOOD)
    assert r.ok and "HOME_LIST []" in r.data["stdout"]


def test_workdir_removed_afterwards():
    r = build("import os\nprint('WD', os.getcwd())\n" + GOOD)
    wd = [line.split()[1] for line in r.data["stdout"].splitlines() if line.startswith("WD")][0]
    assert not Path(wd).exists()


def test_analyze_rejects_oversized_circuit():
    big = build("from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(7)\n")
    r = run_worker({"op": "analyze", "tool": "circuit_metrics", "max_qubits": 5,
                    "circuits": {"candidate": big.data["qpy"]}, "options": {}}, 60, Limits())
    assert r.ok and r.data["status"] == "limit"
