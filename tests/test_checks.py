from qiskit import QuantumCircuit, transpile

from veriq import checks
from veriq.models import CheckResult, Status, overall_verdict


def ghz(n=3):
    qc = QuantumCircuit(n)
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


def test_prove_equivalence_detects_corrupted_compilation():
    qc = ghz()
    tq = transpile(qc, basis_gates=checks.GENERIC_BASIS, optimization_level=3, seed_transpiler=1)
    assert checks.prove_equivalence(qc, tq)[0] == "equivalent"
    broken = tq.copy()
    broken.rz(0.1, 2)  # a "transpiler bug"
    assert checks.prove_equivalence(qc, broken)[0] == "not_equivalent"


def test_operator_fallback():
    qc = ghz()
    v, ev = checks._operator_verify(qc, qc.copy())
    assert v == "equivalent"
    bad = qc.copy()
    bad.z(0)
    assert checks._operator_verify(qc, bad)[0] == "not_equivalent"


def test_transpile_integrity_with_generic_backend():
    res, compiled = checks.transpile_integrity(ghz(4), backend="generic")
    assert res.status == Status.PASS
    assert len(compiled) == 2


def test_counterexample_for_phase_only_difference():
    a = QuantumCircuit(2)
    a.cz(0, 1)
    b = QuantumCircuit(2)  # identity: differs only by relative phase
    cex = checks.find_counterexample(a, b)
    assert cex is not None and cex["input_state"] == "|++>"


def test_reference_qubit_mismatch_fails():
    res = checks.reference_equivalence(ghz(3), ghz(2))
    assert res.status == Status.FAIL


def test_statistical_support_property():
    qc = ghz(3)
    ok = checks.statistical_test(qc, {"support": ["000", "111"]}, None, shots=1000)
    assert ok.status == Status.PASS
    bad = checks.statistical_test(qc, {"support": ["000"]}, None, shots=1000)
    assert bad.status == Status.FAIL


def test_statistical_uses_reference_when_no_expect():
    res = checks.statistical_test(ghz(3), None, ghz(3), shots=2000)
    assert res.status == Status.PASS
    assert res.evidence["expected_source"] == "reference ideal distribution"


def test_statistical_skipped_without_expectation():
    assert checks.statistical_test(ghz(3), None, None).status == Status.SKIPPED


def test_metrics():
    m = checks.circuit_metrics(ghz(3))
    assert m["qubits"] == 3 and m["two_qubit_gates"] == 2 and m["depth"] == 3


def test_overall_verdict_rules():
    P, F, I, S = Status.PASS, Status.FAIL, Status.INCONCLUSIVE, Status.SKIPPED
    mk = lambda *ss: [CheckResult("c", s, "") for s in ss]
    assert overall_verdict(mk(P, S, P)) == P
    assert overall_verdict(mk(P, F, I)) == F
    assert overall_verdict(mk(P, I)) == I
    assert overall_verdict(mk(S, S)) == I
