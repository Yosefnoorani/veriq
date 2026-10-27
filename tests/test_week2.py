"""Week 2: state-preparation mode, gate-set constraint, and 'does not build' handling."""
import json
import math

from qiskit import QuantumCircuit

from veriq import checks
from veriq.cli import main
from veriq.loader import BuildError, LoadError, load_circuit
from veriq.models import Status
from veriq.runner import run_checks

MULTI = '''
from qiskit import QuantumCircuit

def build_ghz_a():
    qc = QuantumCircuit(3); qc.h(0); qc.cx(0, 1); qc.cx(0, 2); return qc

def build_ghz_chain():
    qc = QuantumCircuit(3); qc.h(0); qc.cx(0, 1); qc.cx(1, 2); return qc

def build_ghz_wrong():
    qc = QuantumCircuit(3); qc.h(0); qc.cx(0, 1); return qc

def build_broken():
    qc = QuantumCircuit(3); qc.ccx(0, 1, 2, 4); return qc

def build_not_a_circuit():
    return 42
'''


def _write(tmp_path, text=MULTI, name="multi.py"):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_load_named_function(tmp_path):
    p = _write(tmp_path)
    assert load_circuit(p, "build_ghz_chain").num_qubits == 3


def test_build_errors_are_build_errors(tmp_path):
    p = _write(tmp_path)
    for fn, exc_type in [("build_broken", "CircuitError"), ("build_not_a_circuit", "WrongReturnType"),
                         ("missing_fn", "MissingFunction")]:
        try:
            load_circuit(p, fn)
        except BuildError as e:
            assert e.exc_type == exc_type and e.error_type == "does not build"
        else:
            raise AssertionError(fn)
    bad = _write(tmp_path, "raise RuntimeError('boom')\n", "bad.py")
    try:
        load_circuit(bad)
    except BuildError as e:
        assert e.exc_type == "RuntimeError"
    # BuildError stays a LoadError subclass; missing files remain plain input errors
    assert issubclass(BuildError, LoadError)


def test_state_mode_accepts_different_preparations(tmp_path):
    p = _write(tmp_path)
    ref = load_circuit(p, "build_ghz_a")
    chain = load_circuit(p, "build_ghz_chain")
    # Different unitaries ...
    assert checks.reference_equivalence(chain, ref).status == Status.FAIL
    # ... but the same prepared state
    r = checks.state_equivalence(chain, ref)
    assert r.status == Status.PASS and r.evidence["fidelity"] > 1 - 1e-9


def test_state_mode_ignores_global_phase_and_reports_fidelity(tmp_path):
    p = _write(tmp_path)
    ref = load_circuit(p, "build_ghz_a")
    ph = load_circuit(p, "build_ghz_a")
    ph.global_phase = 1.234
    assert checks.state_equivalence(ph, ref).status == Status.PASS
    wrong = load_circuit(p, "build_ghz_wrong")  # (|000>+|011>)/sqrt2
    r = checks.state_equivalence(wrong, ref)
    assert r.status == Status.FAIL and math.isclose(r.evidence["fidelity"], 0.25, abs_tol=1e-9)


def test_state_mode_skipped_and_width_mismatch():
    assert checks.state_equivalence(QuantumCircuit(2), None).status == Status.SKIPPED
    assert checks.state_equivalence(QuantumCircuit(2), QuantumCircuit(3)).status == Status.FAIL


def test_gate_set_check():
    qc = QuantumCircuit(3)
    qc.h(2); qc.cx(0, 2); qc.t(2); qc.p(0.1, 1)
    r = checks.gate_set_check(qc, ["h", "t", "tdg", "cx"])
    assert r.status == Status.FAIL and r.evidence["violations"] == {"p": 1}
    assert checks.gate_set_check(qc, ["h", "t", "cx", "p"]).status == Status.PASS
    assert checks.gate_set_check(qc, None).status == Status.SKIPPED
    qc.ccx(0, 1, 2)  # a ccx is a violation even though it could be decomposed
    assert "ccx" in checks.gate_set_check(qc, ["h", "t", "cx", "p"]).evidence["violations"]


def test_run_checks_gate_set_fail_makes_verdict_fail():
    ref = QuantumCircuit(3); ref.ccx(0, 1, 2)
    cand = QuantumCircuit(3); cand.ccx(0, 1, 2)
    rep = run_checks(cand, reference=ref, allowed_gates=["h", "t", "tdg", "cx"])
    names = {c.name: c.status for c in rep.checks}
    assert names["Reference equivalence"] == Status.PASS
    assert names["Gate-set constraint"] == Status.FAIL and rep.verdict == Status.FAIL


def test_run_checks_state_mode_verdict(tmp_path):
    p = _write(tmp_path)
    rep = run_checks(p, reference=p, function="build_ghz_chain", reference_function="build_ghz_a", mode="state")
    assert rep.verdict == Status.PASS and rep.target.endswith("::build_ghz_chain")
    rep = run_checks(p, reference=p, function="build_ghz_wrong", reference_function="build_ghz_a", mode="state")
    assert rep.verdict == Status.FAIL


def test_does_not_build_is_fail_via_cli(tmp_path):
    p = _write(tmp_path)
    out = tmp_path / "r.html"
    code = main(["check", p, "--function", "build_broken", "--reference", p,
                 "--reference-function", "build_ghz_a", "--report", str(out), "-q"])
    assert code == 1
    data = json.loads(out.with_suffix(".json").read_text())
    assert data["verdict"] == "FAIL"
    assert data["checks"][0]["name"] == "Build"
    assert data["checks"][0]["evidence"]["error_type"] == "does not build"
    assert data["checks"][0]["evidence"]["exception"] == "CircuitError"
    assert "does not build" in out.read_text()


def test_cli_state_mode_and_allowed_gates(tmp_path):
    p = _write(tmp_path)
    assert main(["check", p, "-f", "build_ghz_chain", "-r", p, "--reference-function", "build_ghz_a",
                 "--mode", "state", "-q"]) == 0
    assert main(["check", p, "-f", "build_ghz_chain", "-r", p, "--reference-function", "build_ghz_a",
                 "--mode", "state", "--allowed-gates", "h,cz", "-q"]) == 1
