"""Hard round (week 3): verified references, locked LLM verdicts, coupling / black-box checks,
the transpiler zero-init hazard, and proof-only mutants that sampling cannot catch."""
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate, UnitaryGate
from qiskit.quantum_info import Operator, Statevector

from veriq import checks
from veriq.cli import main
from veriq.loader import load_circuit
from veriq.models import Status
from veriq.runner import run_checks

ROOT = Path(__file__).resolve().parents[1]
HARD = ROOT / "benchmark" / "hard"
REF_PATH = str(HARD / "references.py")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load("veriq_hard_references_t", HARD / "references.py")
ASSISTANTS = ["chatgpt", "claude", "gemini", "perplexity"]
# Locked verdicts: every LLM circuit in the hard round is correct (proved, not sampled).
EXPECTED = {(a, t): "PASS" for a in ASSISTANTS for t in R.TASKS}


# ---------- references vs. independent specs ----------

@pytest.mark.parametrize("task", sorted(R.SPECS))
def test_reference_matches_truth_table_exactly(task):
    U = Operator(getattr(R, R.TASKS[task]["fn"])()).data
    assert np.allclose(U, R.expected_unitary(task), atol=1e-9)        # exact, incl. phase


@pytest.mark.parametrize("task", sorted(R.TARGET_STATE))
def test_state_reference_prepares_target(task):
    sv = Statevector(getattr(R, R.TASKS[task]["fn"])())
    n, k = R.TARGET_STATE[task]
    assert abs(abs(sv.data[k]) - 1) < 1e-9


def test_specs_are_what_the_prompt_says():
    assert R.spec_maj5(0b000111) == 0b100111 and R.spec_maj5(0b000011) == 0b000011
    for x in range(15):
        assert R.spec_cmul7(x) == x and R.spec_cmul7(16 + x) == 16 + (7 * x) % 15
    assert R.spec_cmul7(15) == 15 and R.spec_cmul7(31) == 31
    assert R.spec_c3x(0b0111) == 0b1111 and R.spec_c3x(0b0011) == 0b0011
    assert R.spec_reverse6(0b000001) == 0b100000
    for a in range(8):
        for b in range(8):
            assert R.spec_add3(a | b << 3) == a | ((a + b) % 8) << 3
    assert len(R.verify_references()) == 7


# ---------- locked LLM verdicts ----------

@pytest.mark.parametrize("assistant,task", sorted(EXPECTED))
def test_llm_verdict_locked(assistant, task):
    spec = R.TASKS[task]
    rep = run_checks(str(HARD / "raw" / f"{assistant}.py"), reference=REF_PATH, function=spec["fn"],
                     reference_function=spec["fn"], mode=spec["mode"], allowed_gates=spec.get("allowed_gates"),
                     coupling=spec.get("coupling"), no_black_boxes=True)
    assert rep.verdict.value == EXPECTED[(assistant, task)]
    names = {c.name for c in rep.checks}
    assert "No black boxes" in names
    if task in ("c3x_linear", "reverse6_nn"):
        assert "Coupling-map constraint" in names and "Gate-set constraint" in names


def test_gemini_c3x_rz_is_only_a_global_phase():
    cand = load_circuit(HARD / "raw" / "gemini.py", "build_c3x_linear")
    U = Operator(cand).data
    V = R.expected_unitary("c3x_linear")
    assert not np.allclose(U, V)                                  # rz instead of p: not identical ...
    assert R.equal_up_to_global_phase(U, V)                       # ... but only by e^{-i pi/16}
    k = int(np.argmax(np.abs(V.ravel())))
    assert math.isclose(float(np.angle(U.ravel()[k])), -math.pi / 16, abs_tol=1e-9)


@pytest.mark.parametrize("assistant", ASSISTANTS)
def test_qpe_inverse_qft_ordering_is_correct(assistant):
    import sys; sys.path.insert(0, str(HARD)); import run_hard
    cand = load_circuit(HARD / "raw" / f"{assistant}.py", "build_qpe_t")
    iq = QuantumCircuit(3)
    iq.append(QFTGate(3).inverse(), [0, 1, 2])
    v, _ = checks.prove_equivalence(run_hard.qpe_iqft_block(cand), iq)
    assert v == "equivalent"


# ---------- coupling-map check ----------

def test_parse_coupling_forms():
    assert checks.parse_coupling("linear", 4) == [(0, 1), (1, 2), (2, 3)]
    assert (0, 3) in checks.parse_coupling("ring", 4)
    assert checks.parse_coupling("2-1,0-1", 3) == [(0, 1), (1, 2)]
    assert checks.parse_coupling([[1, 0]], 2) == [(0, 1)]
    with pytest.raises(ValueError):
        checks.parse_coupling("0-7", 3)
    with pytest.raises(ValueError):
        checks.parse_coupling("0-0", 3)


def test_coupling_check_pass_and_fail():
    ok = QuantumCircuit(3); ok.h(0); ok.cx(0, 1); ok.cx(2, 1)
    assert checks.coupling_check(ok, "linear").status == Status.PASS
    far = QuantumCircuit(3); far.cx(0, 2)
    r = checks.coupling_check(far, "linear")
    assert r.status == Status.FAIL and sum(r.evidence["off_edge_two_qubit_gates"].values()) == 1
    assert checks.coupling_check(far, "ring").status == Status.PASS
    three = QuantumCircuit(3); three.ccx(0, 1, 2)
    r = checks.coupling_check(three, "linear")
    assert r.status == Status.FAIL and sum(r.evidence["multi_qubit_gates"].values()) == 1
    assert checks.coupling_check(ok, None).status == Status.SKIPPED


def test_coupling_is_checked_before_transpile(tmp_path):
    # a far cx that any router would happily fix must still FAIL: the task asks for the circuit as written
    p = tmp_path / "c.py"
    p.write_text("from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(3)\ncircuit.cx(0, 2)\n")
    ref = QuantumCircuit(3); ref.cx(0, 2)
    rep = run_checks(str(p), reference=ref, coupling="linear")
    assert rep.verdict == Status.FAIL
    assert {c.name: c.status for c in rep.checks}["Reference equivalence"] == Status.PASS


# ---------- black-box check ----------

def test_black_box_check():
    qc = QuantumCircuit(2); qc.append(UnitaryGate(np.eye(4)), [0, 1])
    r = checks.black_box_check(qc, True)
    assert r.status == Status.FAIL and "unitary" in r.evidence["black_boxes"]
    q2 = QuantumCircuit(3); q2.append(QFTGate(3), [0, 1, 2])
    assert checks.black_box_check(q2, True).status == Status.FAIL
    q3 = QuantumCircuit(1); q3.initialize([0, 1], 0)
    assert checks.black_box_check(q3, True).status == Status.FAIL
    hand = QuantumCircuit(4); hand.h(0); hand.mcx([0, 1, 2], 3); hand.ccx(0, 1, 2); hand.cp(0.1, 0, 1); hand.barrier()
    assert checks.black_box_check(hand, True).status == Status.PASS
    assert checks.black_box_check(qc, False).status == Status.SKIPPED


# ---------- CLI flags and exit codes ----------

def _cand(tmp_path, body, name="cand.py"):
    p = tmp_path / name
    p.write_text("from qiskit import QuantumCircuit\n" + body)
    return str(p)


def test_cli_new_flags_exit_codes(tmp_path):
    ref = _cand(tmp_path, "circuit = QuantumCircuit(3)\ncircuit.cx(0, 1)\ncircuit.cx(1, 2)\n", "ref.py")
    good = _cand(tmp_path, "circuit = QuantumCircuit(3)\ncircuit.cx(0, 1)\ncircuit.cx(1, 2)\n")
    far = _cand(tmp_path, "circuit = QuantumCircuit(3)\ncircuit.cx(0, 1)\ncircuit.cx(1, 2)\ncircuit.cx(0, 2)\n"
                          "circuit.cx(0, 2)\n", "far.py")
    assert main(["check", good, "-r", ref, "--coupling", "linear", "--no-black-boxes", "-q"]) == 0
    assert main(["check", far, "-r", ref, "--coupling", "linear", "-q"]) == 1
    assert main(["check", far, "-r", ref, "--coupling", "0-1,1-2,0-2", "-q"]) == 0
    assert main(["check", good, "-r", ref, "--coupling", "0-9", "-q"]) == 3
    bb = tmp_path / "bb.py"
    bb.write_text("import numpy as np\nfrom qiskit import QuantumCircuit\nfrom qiskit.circuit.library import UnitaryGate\n"
                  "circuit = QuantumCircuit(1)\ncircuit.append(UnitaryGate(np.eye(2)), [0])\n")
    ref1 = _cand(tmp_path, "circuit = QuantumCircuit(1)\n", "ref1.py")
    assert main(["check", str(bb), "-r", ref1, "-q"]) == 0
    assert main(["check", str(bb), "-r", ref1, "--no-black-boxes", "-q"]) == 1
    out = tmp_path / "r.json"
    main(["check", far, "-r", ref, "--coupling", "linear", "-q", "--json", str(out)])
    data = json.loads(out.read_text())
    assert any(c["name"] == "Coupling-map constraint" and c["status"] == "FAIL" for c in data["checks"])


# ---------- transpiler zero-init hazard ----------

def test_zero_init_hazard_is_flagged_but_not_a_failure():
    qc = QuantumCircuit(6); qc.mcx([0, 3, 4], 5)       # q1, q2 idle: default transpile borrows them
    r, _ = checks.transpile_integrity(qc, None, 7, 30)
    assert r.status == Status.PASS and r.evidence["zero_init_hazard"] is True
    lone = QuantumCircuit(4); lone.mcx([0, 1, 2], 3)    # no idle qubit to borrow
    assert checks.transpile_integrity(lone, None, 7, 30)[0].evidence["zero_init_hazard"] is False


def test_zero_init_hazard_is_real():
    from qiskit import transpile
    qc = QuantumCircuit(6); qc.mcx([0, 3, 4], 5)
    t = transpile(qc, basis_gates=["cx", "rz", "sx", "x"], optimization_level=1, seed_transpiler=1)
    assert checks.prove_equivalence(qc, t)[0] == "not_equivalent"           # wrong as a unitary ...
    for prep in ([0, 3, 4], [0, 3], []):                                      # ... right whenever q1 = q2 = 0
        x = QuantumCircuit(6); [x.x(q) for q in prep]
        assert np.allclose(Statevector(x.compose(t)).probabilities(), Statevector(x.compose(qc)).probabilities())
    x = QuantumCircuit(6); x.x([0, 1, 3, 4])                                  # borrowed ancilla q1 dirty
    assert not np.allclose(Statevector(x.compose(t)).probabilities(), Statevector(x.compose(qc)).probabilities())


# ---------- proof-only mutants (the key research question) ----------

def _negate_first_p(qc):
    out = qc.copy_empty_like()
    done = False
    for ins in qc.data:
        if not done and ins.operation.name in ("p", "rz"):
            getattr(out, ins.operation.name)(-float(ins.operation.params[0]), ins.qubits[0]); done = True
        else:
            out.append(ins)
    assert done
    return out


@pytest.mark.parametrize("assistant", ASSISTANTS)
def test_c3x_phase_bug_invisible_to_any_basis_sampling(assistant):
    cand = load_circuit(HARD / "raw" / f"{assistant}.py", "build_c3x_linear")
    mut = _negate_first_p(cand)
    ref = R.build_c3x_linear()
    assert checks.prove_equivalence(mut, ref)[0] == "not_equivalent"
    assert checks.statistical_test(mut, None, ref, shots=4096, seed=7).status == Status.PASS
    Um, Ur = np.abs(Operator(mut).data) ** 2, np.abs(Operator(ref).data) ** 2
    assert np.allclose(Um, Ur, atol=1e-12)          # identical output distribution for every basis input


def test_qpe_pi_as_3_14_passes_sampling_fails_proof():
    cand = load_circuit(HARD / "raw" / "chatgpt.py", "build_qpe_t")
    mut = cand.copy_empty_like()
    for ins in cand.data:
        op = ins.operation
        if op.params and op.name in ("cp", "p", "rz", "crz"):
            new = op.to_mutable(); new.params = [float(op.params[0]) * 3.14 / math.pi]
            mut.append(new, ins.qubits)
        else:
            mut.append(ins)
    ref = R.build_qpe_t()
    assert checks.state_equivalence(mut, ref).status == Status.FAIL
    assert checks.statistical_test(mut, None, ref, shots=4096, seed=7).status == Status.PASS
    tvd = 0.5 * np.abs(Statevector(mut).probabilities() - Statevector(ref).probabilities()).sum()
    assert tvd < 1e-4                                # ~1e-6: orders of magnitude below shot noise


def test_mutation_study_results_committed():
    m = json.loads((HARD / "results" / "mutation.json").read_text())
    classes = [x["class"] for x in m["mutants"]]
    assert m["total_mutants"] == len(classes) > 500
    assert classes.count("proof_only_invisible_to_sampling") > 0
    assert classes.count("proof_only_sampling_too_weak") > 0
    assert "undecided" not in classes
