"""Repair loop driver: pluggable fixer, deterministic demo fixer, bounded retries, CLI."""
import json
import math

from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from veriq import cli
from veriq.repair import FixRequest, demo_fixer, load_fixer, repair_loop


def qft(n, scale=1.0):
    qc = QuantumCircuit(n)
    for j in reversed(range(n)):
        qc.h(j)
        for k in reversed(range(j)):
            qc.cp(scale * math.pi / 2 ** (j - k), k, j)
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc


def drop(qc, i):
    out = QuantumCircuit(qc.num_qubits)
    for k, inst in enumerate(qc.data):
        if k != i:
            out.append(inst)
    return out


def test_demo_fixer_repairs_deleted_gate():
    ref = qft(4)
    res = repair_loop(drop(ref, 5), ref, demo_fixer, max_attempts=3)
    assert res["verdict"] == "PASS" and res["stop_reason"] == "PASS" and res["attempts"] == 1
    assert Operator(res["final_circuit"]).equiv(Operator(ref))
    assert res["history"][0]["verdict"] == "FAIL" and res["history"][1]["fix"]


def test_demo_fixer_repairs_pi_as_314_by_local_edit():
    ref = qft(3)
    res = repair_loop(qft(3, 3.14 / math.pi), ref, demo_fixer, max_attempts=3)
    assert res["verdict"] == "PASS" and "3.14" in res["history"][-1]["fix"]


def test_state_mode_repair():
    ref = QuantumCircuit(3)
    ref.h(0); ref.cx(0, 1); ref.cx(1, 2)
    bad = QuantumCircuit(3)
    bad.h(0); bad.cx(0, 1); bad.cx(2, 1)
    res = repair_loop(bad, ref, mode="state")
    assert res["verdict"] == "PASS" and "flip" in res["history"][-1]["fix"]


def test_already_correct_stops_immediately():
    ref = qft(3)
    calls = []
    res = repair_loop(ref.copy(), ref, lambda r: calls.append(r) or None)
    assert res["verdict"] == "PASS" and res["attempts"] == 0 and not calls


def test_fixer_gives_up_and_max_attempts():
    ref = qft(3)
    bad = drop(ref, 1)
    res = repair_loop(bad, ref, lambda r: None)
    assert res["verdict"] == "FAIL" and res["stop_reason"] == "fixer_gave_up"
    seen = []

    def useless(req: FixRequest):
        seen.append(req.attempt)
        assert req.report["schema"] == "veriq.repair_report/1" and req.report["counterexample"]
        return req.circuit  # returns the same broken circuit forever

    res = repair_loop(bad, ref, useless, max_attempts=2)
    assert res["stop_reason"] == "max_attempts" and res["attempts"] == 2 and seen == [1, 2]


def test_fixer_can_return_source_text():
    ref = QuantumCircuit(2)
    ref.h(0); ref.cx(0, 1)
    bad = QuantumCircuit(2)
    bad.h(0); bad.cx(1, 0)
    src = ("from qiskit import QuantumCircuit\ndef build():\n    qc = QuantumCircuit(2)\n    qc.h(0)\n"
           "    qc.cx(0, 1)\n    return qc\n")
    res = repair_loop(bad, ref, lambda r: src, mode="state")
    assert res["verdict"] == "PASS"
    res = repair_loop(bad, ref, lambda r: "def build(:\n", mode="state")
    assert res["stop_reason"] == "build_error"


def test_inconclusive_stops_the_loop():
    ref = QuantumCircuit(1)
    ref.h(0)
    bad = QuantumCircuit(1, 1)
    bad.h(0); bad.measure(0, 0); bad.h(0)  # mid-circuit measurement: equivalence undefined
    res = repair_loop(bad, ref, demo_fixer)
    assert res["verdict"] == "INCONCLUSIVE" and res["stop_reason"] == "INCONCLUSIVE"


def test_load_fixer():
    assert load_fixer("demo") is demo_fixer
    assert load_fixer("veriq.repair:demo_fixer") is demo_fixer


def test_cli_repair(tmp_path):
    out, log = tmp_path / "fixed.qasm", tmp_path / "log.json"
    code = cli.main(["repair", "examples/ghz_buggy.py", "-r", "examples/ghz_correct.py", "--mode", "state",
                     "--out", str(out), "--json", str(log), "-q"])
    assert code == 0 and out.read_text().startswith("OPENQASM 2.0")
    data = json.loads(log.read_text())
    assert data["verdict"] == "PASS" and data["history"][0]["verdict"] == "FAIL"
    assert cli.main(["check", str(out), "-r", "examples/ghz_correct.py", "--mode", "state", "-q"]) == 0
