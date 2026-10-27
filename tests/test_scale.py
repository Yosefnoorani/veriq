"""Large-circuit verification (veriq.scale): proofs, falsification, honesty of the four statuses."""

import sys
import time
from pathlib import Path

import pytest
from qiskit import QuantumCircuit

from veriq import checks, scale, tools
from veriq.models import Status

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark" / "scale"))
from families import build  # noqa: E402


def test_clifford_tableau_proves_and_refutes_at_100_qubits():
    a, b, mode = build("clifford", 100, False)
    r = scale.decide_equivalence(a, b, mode, timeout=30)
    assert r["status"] == scale.PROVEN and r["method"] == "clifford-tableau"
    a, b, mode = build("clifford", 100, True)
    r = scale.decide_equivalence(a, b, mode, timeout=30)
    assert r["status"] == scale.NOT_EQ
    cex = r["evidence"]["counterexample"]
    assert cex["fidelity"] < 1 and cex["input_state"].startswith("|")


def test_clifford_state_mode_ghz_40():
    a, b, _ = build("ghz", 40, False)
    assert checks.state_equivalence(a, b).status == Status.PASS
    a, b, _ = build("ghz", 40, True)
    res = checks.state_equivalence(a, b)
    assert res.status == Status.FAIL and res.evidence["counterexample"]["fidelity"] == pytest.approx(0.25)


def test_partition_into_independent_blocks():
    a, b, mode = build("blocks", 30, False)
    r = scale.decide_equivalence(a, b, mode, timeout=30)
    assert r["status"] == scale.PROVEN and r["method"].startswith("partition")
    assert r["evidence"]["blocks"] == 6
    a, b, mode = build("blocks", 30, True)
    r = scale.decide_equivalence(a, b, mode, timeout=30)
    assert r["status"] == scale.NOT_EQ and "on_qubits" in r["evidence"]["counterexample"]


def test_partition_helper():
    a = QuantumCircuit(4)
    a.cx(0, 1)
    b = QuantumCircuit(4)
    b.cx(2, 3)
    assert scale.partition(a, b) == [[0, 1], [2, 3]]
    b.cx(1, 2)
    assert scale.partition(a, b) == [[0, 1, 2, 3]]


def test_qcec_proves_cuccaro_30_and_finds_witness_for_bug():
    a, b, mode = build("cuccaro", 30, False)
    r = scale.decide_equivalence(a, b, mode, timeout=40)
    assert r["status"] == scale.PROVEN and r["method"].startswith("qcec")
    a, b, mode = build("cuccaro", 30, True)
    r = scale.decide_equivalence(a, b, mode, timeout=40)
    assert r["status"] == scale.NOT_EQ
    assert r["evidence"]["counterexample"]["fidelity"] < 1e-6  # a basis input gives a different sum


def test_zx_proves_qft_24():
    a, b, mode = build("qft", 24, False)
    r = scale.decide_equivalence(a, b, mode, timeout=40)
    assert r["status"] == scale.PROVEN and r["method"] == "qcec-zx"


def test_hard_timeout_really_stops_qcec():
    a, b, _ = build("qft", 40, False)
    t0 = time.perf_counter()
    r = scale.qcec_decide(a, b, ["alternating"], timeout=2.0)
    assert time.perf_counter() - t0 < 8
    assert r["status"] == scale.UNKNOWN
    assert r["evidence"]["qcec_runs"][0]["result"] == "timeout"


def test_falsification_alone_is_never_a_proof():
    a, b, mode = build("qft_approx", 16, False)
    r = scale.decide_equivalence(a, b, mode, timeout=40, strategies=["falsify"], trials=4)
    assert r["status"] == scale.PROBABLY
    assert "NOT a proof" in r["evidence"]["note"]


def test_falsification_finds_bug_without_qcec():
    a, b, mode = build("qft_approx", 16, True)
    r = scale.decide_equivalence(a, b, mode, timeout=40, strategies=["falsify"], trials=4)
    assert r["status"] == scale.NOT_EQ and r["method"] == "mps-falsify"


def test_probably_equivalent_maps_to_inconclusive(monkeypatch):
    fake = {"status": scale.PROBABLY, "method": "mps-falsify", "seconds": 1.0,
            "evidence": {"method": "mps-falsify", "inputs_tried": 32, "note": "falsification only"}}
    monkeypatch.setattr(scale, "decide_equivalence", lambda *a, **k: fake)
    a, b, _ = build("qft", 14, False)
    res = checks.reference_equivalence(a, b)
    assert res.status == Status.INCONCLUSIVE and "NOT a proof" in res.summary
    out = tools.compare_circuits(a, b)
    assert out["status"] == "PROBABLY_EQUIVALENT" and out["verdict"] == "INCONCLUSIVE" and out["equivalent"] is None


def test_exact_mps_overlap_in_state_mode_non_clifford():
    a, b, _ = build("ghz", 22, False)
    a.t(3)
    a.cx(3, 4)
    a.tdg(3)
    a.cx(3, 4)  # non-Clifford detour that cancels (T on a control commutes with CX)
    r = scale.decide_equivalence(a, b, "state", timeout=60, strategies=["falsify"])
    assert r["status"] == scale.PROVEN and r["method"] == "mps-exact-overlap"
    b2 = b.copy()
    b2.t(0)  # relative phase on |1...1>
    r = scale.decide_equivalence(b2, b, "state", timeout=60, strategies=["falsify"])
    assert r["status"] == scale.NOT_EQ


def test_two_sample_statistical_test_at_30_qubits():
    a, b, _ = build("ghz", 30, False)
    assert checks.statistical_test(a, None, b, shots=2000).status == Status.PASS
    bad = QuantumCircuit(30)
    bad.h(0)
    assert checks.statistical_test(bad, None, b, shots=2000).status == Status.FAIL


def test_unknown_strategy_rejected():
    a, b, _ = build("ghz", 8, False)
    with pytest.raises(ValueError):
        scale.decide_equivalence(a, b, strategies=["magic"])


def test_compare_circuits_tool_at_60_qubits():
    a, b, _ = build("clifford", 60, True)
    out = tools.compare_circuits(a, b)
    assert out["verdict"] == "FAIL" and out["counterexample"]["input_state"].startswith("|")


@pytest.mark.slow
def test_oracle_bug_found_by_mps_at_20_qubits():
    a, b, mode = build("oracle", 20, True)
    r = scale.falsify(a, b, mode, budget=90)
    assert r["status"] == scale.NOT_EQ


@pytest.mark.slow
def test_qft_50_proven_by_zx():
    a, b, mode = build("qft", 50, False)
    r = scale.decide_equivalence(a, b, mode, timeout=60)
    assert r["status"] == scale.PROVEN


def test_budget_respected_on_wide_oracle_12():
    """Regression: the 12-qubit exhaustive search on a 11-control mcphase used to run unbudgeted (>120 s)."""
    a, b, mode = build("oracle", 12, False)
    t = time.perf_counter()
    r = scale.decide_equivalence(a, b, mode, timeout=15)
    assert time.perf_counter() - t < 30
    assert r["status"] in (scale.PROBABLY, scale.PROVEN)
