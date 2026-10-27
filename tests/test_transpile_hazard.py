"""examples/transpile_hazard: the documented qubits_initially_zero footgun, reproduced."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Operator, Statevector

from veriq import checks, run_checks
from veriq.cli import main

D = Path(__file__).resolve().parent.parent / "examples" / "transpile_hazard"
BASIS = ["cx", "rz", "sx", "x"]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_th_{name}", D / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def demo():
    return _load("demo").run()


@pytest.mark.parametrize("opt", [0, 1, 2, 3])
def test_minimal_reproducer_all_opt_levels(opt):
    qc = QuantumCircuit(5)
    qc.mcx([0, 1, 2], 3)
    t = transpile(qc, basis_gates=BASIS, optimization_level=opt, seed_transpiler=1)
    assert not Operator(t).equiv(Operator(qc))
    t2 = transpile(qc, basis_gates=BASIS, optimization_level=opt, seed_transpiler=1, qubits_initially_zero=False)
    assert Operator(t2).equiv(Operator(qc))


@pytest.mark.parametrize("controls,idle,bad", [(2, 1, False), (3, 0, False), (3, 1, True), (4, 1, True)])
def test_trigger_shape(controls, idle, bad):
    qc = QuantumCircuit(controls + 1 + idle)
    qc.mcx(list(range(controls)), controls)
    t = transpile(qc, basis_gates=BASIS, optimization_level=1, seed_transpiler=1)
    assert (not Operator(t).equiv(Operator(qc))) is bad


def test_correct_whenever_idle_qubit_starts_at_zero():
    src, comp = _load("block").build(), _load("compiled").build()
    U, V = Operator(src).data, Operator(comp).data
    for x in range(32):
        same = abs(abs(np.vdot(U[:, x], V[:, x])) - 1) < 1e-9
        assert same == (not (x >> 4 & 1 and x >> 2 & 1)), x  # wrong iff q4=1 and q2=1


def test_demo_a_sampling_passes(demo):
    assert demo["a_status"] == "PASS"
    assert demo["a_tvd"] < 0.05


def test_demo_b_veriq_fails_with_counterexample(demo):
    assert demo["b_verdict"] == "FAIL"
    assert demo["b_proof"] == "not_equivalent"
    ce = demo["b_counterexample"]
    assert ce["input_state"] == "|10100>"
    assert ce["fidelity"] == 0.0
    assert set(map(str, ce["candidate_output_top"])) == {"11100"}


def test_demo_c_subblock_reuse_is_wrong(demo):
    assert demo["c_expected"] == {"11111": 1.0}
    assert demo["c_got"] == {"10111": 1.0}


def test_demo_d_safe_compile_is_equivalent(demo):
    assert demo["d_proof_safe"] == "equivalent"


def test_demo_main_exit_code(capsys):
    assert _load("demo").main() == 0
    assert "demo behaved as documented" in capsys.readouterr().out


def test_cli_verdicts(tmp_path):
    comp, block = str(D / "compiled.py"), str(D / "block.py")
    assert main(["check", comp, "-r", block, "-q"]) == 1
    assert main(["check", comp, "--function", "build_safe", "-r", block, "-q"]) == 0
    assert main(["check", block, "-q"]) == 0


def test_block_alone_records_hazard_note():
    rep = run_checks(_load("block").build())
    ti = next(c for c in rep.checks if c.name == "Transpile integrity")
    assert ti.evidence["zero_init_hazard"] is True
    assert "qubits_initially_zero" in ti.summary
