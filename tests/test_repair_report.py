"""Structured repair report: counterexample, localization, exact fixes, hardware violations, CLI flag."""
import json
import math

import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector

from veriq import cli
from veriq.repair_report import apply_fix, build_repair_report, localize, operator_support
from veriq.runner import run_checks


def qft(n):
    qc = QuantumCircuit(n)
    for j in reversed(range(n)):
        qc.h(j)
        for k in reversed(range(j)):
            qc.cp(math.pi / 2 ** (j - k), k, j)
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc


def without(qc, i):
    out = QuantumCircuit(qc.num_qubits)
    for k, inst in enumerate(qc.data):
        if k != i:
            out.append(inst)
    return out


def replaced(qc, i, op, qubits):
    out = QuantumCircuit(qc.num_qubits)
    for k, inst in enumerate(qc.data):
        out.append(op, qubits) if k == i else out.append(inst)
    return out


def equal(a, b):
    return Operator(a).equiv(Operator(b))


def test_support_of_local_operator():
    qc = QuantumCircuit(4)
    qc.cx(1, 3)
    assert operator_support(Operator(qc).data, 4) == [1, 3]
    assert operator_support(Operator(QuantumCircuit(4)).data, 4) == []


def test_equivalent_circuit_has_empty_support():
    ref = qft(4)
    loc = localize(ref.copy(), ref)
    assert loc["available"] and loc["equivalent"] and loc["min_support_qubits"] == 0


@pytest.mark.parametrize("i", [0, 3, 6, 9])
def test_deleted_gate_is_localized_and_fixed(i):
    ref = qft(4)
    bad = without(ref, i)
    rep = build_repair_report(bad, ref, result=run_checks(bad, reference=ref).to_dict())
    assert rep["verdict"] == "FAIL" and rep["counterexample"]["input_state"]
    loc = rep["localization"]
    assert loc["min_support_qubits"] <= 2
    assert any(r["gap_start"] <= i <= r["gap_end"] for r in loc["regions"])  # the missing gate's gap
    fixed = apply_fix(bad, loc["fixes"][0])
    assert equal(fixed, ref)
    assert any(h.startswith("Exact fix found") for h in rep["hints"])


def test_negated_angle_gives_replace_fix():
    ref = qft(3)
    i = next(k for k, inst in enumerate(ref.data) if inst.operation.name == "cp")
    from qiskit.circuit.library import CPhaseGate
    qs = [ref.find_bit(q).index for q in ref.data[i].qubits]
    bad = replaced(ref, i, CPhaseGate(-ref.data[i].operation.params[0]), qs)
    loc = build_repair_report(bad, ref)["localization"]
    assert any(r["gate_start"] <= i <= r["gate_end"] for r in loc["regions"])
    assert any(f["action"] == "replace" and f["gate_index"] == i for f in loc["fixes"])
    assert all(equal(apply_fix(bad, f), ref) for f in loc["fixes"])


def test_flipped_cx_named_fix():
    ref = QuantumCircuit(4)
    ref.h(0); ref.cx(0, 1); ref.cx(1, 2); ref.t(2); ref.cx(2, 3); ref.h(3)
    bad = ref.copy_empty_like()
    for k, inst in enumerate(ref.data):
        if k == 2:
            bad.cx(2, 1)
        else:
            bad.append(inst)
    loc = localize(bad, ref)
    assert loc["min_support_qubits"] <= 2
    assert any(r["gate_start"] <= 2 <= r["gate_end"] for r in loc["regions"])
    assert any(f["action"] == "replace" and f["gate"]["name"] == "cx" and f["gate"]["qubits"] == [1, 2]
               for f in loc["fixes"])


def test_state_mode_localization():
    ref = QuantumCircuit(3)
    ref.h(0); ref.cx(0, 1); ref.cx(1, 2)
    bad = QuantumCircuit(3)
    bad.h(0); bad.cx(0, 1); bad.cx(2, 1)
    rep = build_repair_report(bad, ref, mode="state")
    assert rep["counterexample"]["input_state"] == "|000>"
    assert rep["counterexample"]["expected_output_top"] == {"000": 0.5, "111": 0.5}
    loc = rep["localization"]
    assert loc["available"] and loc["min_support_qubits"] in (1, 2)
    assert any(r["gate_start"] <= 2 <= r["gate_end"] for r in loc["regions"])


def test_hardware_violations_and_metric_deltas():
    ref = QuantumCircuit(3)
    ref.ccx(0, 1, 2)
    cand = ref.copy()
    res = run_checks(cand, reference=ref, allowed_gates=["h", "t", "tdg", "cx"], coupling="linear").to_dict()
    rep = build_repair_report(cand, ref, result=res)
    names = {v["check"] for v in rep["hardware_violations"]}
    assert names == {"Gate-set constraint", "Coupling-map constraint"}
    assert rep["counterexample"] is None
    assert rep["localization"] is None  # equivalent: nothing to localize
    assert rep["metric_deltas"]["multi_qubit_gates"] == {"candidate": 1, "reference": 1, "delta": 0}
    assert any("Hardware constraint violated" in h for h in rep["hints"])


def test_wide_circuit_localization_unavailable():
    a, b = QuantumCircuit(12), QuantumCircuit(12)
    a.x(0)
    loc = localize(a, b)
    assert not loc["available"] and "limit" in loc["reason"]


def test_cli_repair_report(tmp_path):
    out = tmp_path / "rep.json"
    code = cli.main(["verify", "examples/ghz_buggy.py", "-r", "examples/ghz_correct.py", "--mode", "state",
                     "--repair-report", str(out), "-q"])
    assert code == 1
    rep = json.loads(out.read_text())
    assert rep["schema"] == "veriq.repair_report/1" and rep["verdict"] == "FAIL"
    assert rep["counterexample"]["expected_output_top"]
    assert any(r["gate_start"] <= 2 <= r["gate_end"] for r in rep["localization"]["regions"])


def test_cli_repair_report_on_pass(tmp_path):
    out = tmp_path / "rep.json"
    code = cli.main(["check", "examples/ghz_correct.py", "-r", "examples/ghz_correct.py", "--repair-report",
                     str(out), "-q"])
    assert code == 0
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS" and rep["localization"] is None


def test_cli_repair_report_build_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def build():\n    raise RuntimeError('boom')\n")
    out = tmp_path / "rep.json"
    cli.main(["check", str(bad), "-r", "examples/ghz_correct.py", "--repair-report", str(out), "-q"])
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL" and not rep["localization"]["available"]
