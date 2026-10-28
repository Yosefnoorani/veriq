"""Verified CX optimizer: never returns an unproven candidate; picks the cheapest proven one."""
import json

from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from veriq import cli, optimize, scale
from veriq.optimize import optimize_circuit


def redundant():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1); qc.cx(0, 1)      # cancels
    qc.cx(1, 2); qc.rz(0.3, 2); qc.cx(1, 2)
    qc.swap(0, 2)
    qc.ccx(0, 1, 2)
    return qc


def test_best_is_proven_cheaper_and_equal():
    qc = redundant()
    r = optimize_circuit(qc, seeds=2)
    b = r["best"]
    assert b["status"] == scale.PROVEN
    assert b["cx"] < r["baseline"]["cx"]
    assert Operator(r["best_circuit"]).equiv(Operator(qc))
    assert r["best_qasm"].startswith("OPENQASM 2.0")
    # cheapest-first: everything tried before the winner was cheaper-or-equal but unproven
    for t in r["tried"][:-1]:
        assert t["status"] != scale.PROVEN and (t["cx"], t["depth"]) <= (b["cx"], b["depth"])


def test_permutation_elision_is_rejected_unless_allowed():
    qc = QuantumCircuit(3)
    qc.h(0); qc.cx(0, 1); qc.swap(0, 2); qc.swap(1, 2)
    strict = optimize_circuit(qc, seeds=1)
    assert Operator(strict["best_circuit"]).equiv(Operator(qc))  # drop-in: no hidden permutation
    loose = optimize_circuit(qc, seeds=1, allow_permutation=True)
    assert loose["best"]["cx"] <= strict["best"]["cx"]
    assert "layout" in loose["proof_scope"]


def test_never_returns_unproven(monkeypatch):
    def fake(a, b, mode="unitary", timeout=30.0, **kw):
        return {"status": scale.PROBABLY, "method": "falsify", "evidence": {}, "seconds": 0.0}

    monkeypatch.setattr(optimize.scale, "decide_equivalence", fake)
    r = optimize_circuit(redundant(), seeds=1)
    assert r["best"] is None and r["best_qasm"] is None and r["tried"]
    assert all(t["status"] == scale.PROBABLY for t in r["tried"])


def test_state_mode_allows_zero_init_candidates():
    qc = QuantumCircuit(2)
    qc.x(0); qc.cx(0, 1); qc.cx(0, 1); qc.h(1)
    r = optimize_circuit(qc, mode="state", seeds=1)
    assert r["best"]["status"] == scale.PROVEN and "|0..0>" in r["proof_scope"]


def test_cli_optimize(tmp_path):
    out, js = tmp_path / "best.qasm", tmp_path / "r.json"
    code = cli.main(["optimize", "examples/qft_reference.py", "--seeds", "1", "-o", str(out), "--json", str(js), "-q"])
    assert code == 0 and out.read_text().startswith("OPENQASM")
    assert json.loads(js.read_text())["best"]["status"] == scale.PROVEN
    assert cli.main(["check", str(out), "-r", "examples/qft_reference.py", "-q"]) == 0
