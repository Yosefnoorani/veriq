"""veriq.tools: the analysis behind the MCP tools, called directly on circuits (no sandbox)."""

from math import pi

from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate

from veriq import tools
from veriq.loader import load_circuit
from veriq.mcp_server import explain


def ghz(n=3, bug=False):
    qc = QuantumCircuit(n)
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    if bug:
        qc.z(1)
    return qc


def qft_ref(n):
    qc = QuantumCircuit(n)
    qc.append(QFTGate(n), range(n))
    return qc.decompose()


def test_verify_pass_with_reference():
    r = tools.verify_circuit(ghz(), ghz())
    assert r["verdict"] == "PASS"
    assert r["counterexample"] is None
    assert r["metrics"]["qubits"] == 3
    assert any(c["name"] == "Reference equivalence" and c["status"] == "PASS" for c in r["checks"])


def test_verify_fail_has_counterexample_and_hints(ex):
    cand = load_circuit(ex("qft_buggy.py"))
    ref = load_circuit(ex("qft_reference.py"))
    r = tools.verify_circuit(cand, ref)
    assert r["verdict"] == "FAIL"
    assert r["counterexample"]["input_state"].startswith("|")
    assert r["counterexample"]["fidelity"] < 1
    assert r["hints"] and "Counterexample" in r["hints"][0]


def test_hint_reversed_bits_qft_without_swaps():
    n = 3
    qc = QuantumCircuit(n)
    for j in reversed(range(n)):
        qc.h(j)
        for k in reversed(range(j)):
            qc.cp(pi / 2 ** (j - k), k, j)
    r = tools.verify_circuit(qc, qft_ref(n))  # missing final swap
    assert r["verdict"] == "FAIL"
    assert r["counterexample"] is not None


def test_hint_phase_only_difference():
    a = QuantumCircuit(2)
    a.h([0, 1])
    a.cz(0, 1)
    b = QuantumCircuit(2)
    b.h([0, 1])
    b.cp(pi / 2, 0, 1)
    r = tools.compare_circuits(a, b)
    assert r["status"] == "NOT_EQUIVALENT" and r["equivalent"] is False and r["verdict"] == "FAIL"
    assert r["counterexample"] is not None


def test_verify_constraints_hints():
    qc = QuantumCircuit(3)
    qc.ccx(0, 1, 2)
    r = tools.verify_circuit(qc, allowed_gates=["h", "t", "tdg", "cx"], coupling="linear")
    assert r["verdict"] == "FAIL"
    text = " ".join(r["hints"])
    assert "Disallowed instructions ['ccx']" in text
    assert "coupling map" in text


def test_verify_state_mode():
    a = ghz()
    b = QuantumCircuit(3)
    b.h(0)
    b.cx(0, 2)
    b.cx(0, 1)
    assert tools.verify_circuit(a, b, mode="state")["verdict"] == "PASS"
    assert tools.verify_circuit(ghz(bug=True), b, mode="state")["verdict"] == "FAIL"


def test_compare_qubit_mismatch_and_proof():
    r = tools.compare_circuits(ghz(3), ghz(4))
    assert r["status"] == "NOT_EQUIVALENT" and "widths" in r["summary"]
    r = tools.compare_circuits(ghz(4), ghz(4))
    assert r["status"] == "PROVEN_EQUIVALENT" and r["equivalent"] is True and r["method"]


def test_check_transpile_zero_init_hazard(ex):
    block = load_circuit(ex("transpile_hazard/block.py"))
    r = tools.check_transpile(block)
    assert r["verdict"] == "PASS"
    assert r["zero_init_hazard"] is True
    assert r["runs"]["qubits_initially_zero=True"]["status"] == "NOT_EQUIVALENT"
    r1 = tools.check_transpile(block, qubits_initially_zero=True)
    assert r1["verdict"] == "FAIL" and r1["zero_init_hazard"] is True
    assert r1["runs"]["qubits_initially_zero=True"]["equal_on_zero_input"] is True


def test_check_transpile_plain_and_options():
    r = tools.check_transpile(qft_ref(4), optimization_level=1, basis_gates=["u", "cx"], coupling="ring")
    assert r["verdict"] == "PASS" and r["zero_init_hazard"] is False
    assert r["options"]["basis_gates"] == ["u", "cx"]


def test_metrics():
    m = tools.circuit_metrics(ghz(4))
    assert m["source"]["qubits"] == 4 and m["source"]["two_qubit_gates"] == 3
    assert m["compiled"]["two_qubit_gates"] >= 3
    assert m["is_clifford"] is True
    qc = QuantumCircuit(1)
    qc.t(0)
    assert tools.circuit_metrics(qc, compile=False)["is_clifford"] is False


def test_explain_verdict():
    r = tools.verify_circuit(ghz(bug=True), ghz())
    e = explain(r)
    assert e["verdict"] == "FAIL" and e["safe_to_present_as_verified"] is False
    assert "Counterexample" in e["explanation"]
    assert explain({"status": "PROBABLY_EQUIVALENT"})["safe_to_present_as_verified"] is False
    assert explain(tools.verify_circuit(ghz(), ghz()))["safe_to_present_as_verified"] is True


def test_trim_caps_large_count_dicts():
    big = {format(i, "08b"): i for i in range(200)}
    t = tools._trim({"observed_counts": big})["observed_counts"]
    assert len(t) == tools.MAX_EVIDENCE_KEYS + 1 and "…" in t
