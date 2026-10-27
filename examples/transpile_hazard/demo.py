"""Transpile hazard demo: a compiled block that passes sampling and is still wrong.

    python examples/transpile_hazard/demo.py

(a) Aer histogram from |0..0> (controls in superposition): compiled == source -> PASS
(b) Veriq equivalence proof: FAIL, with a concrete basis-state counterexample
(c) the compiled block reused via to_gate() inside a larger circuit: wrong output
(d) the fix: transpile(..., qubits_initially_zero=False) -> proof PASS
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qiskit  # noqa: E402
from qiskit import QuantumCircuit  # noqa: E402

from veriq import checks, run_checks  # noqa: E402

from block import build as build_source  # noqa: E402
from compiled import build as build_compiled, build_safe  # noqa: E402

SHOTS, SEED = 4096, 7


def sampling_harness(block: QuantumCircuit) -> QuantumCircuit:
    """Typical test: start from |0..0>, put the controls in superposition, run the block."""
    qc = QuantumCircuit(block.num_qubits)
    qc.h([0, 1, 2])
    qc.compose(block, inplace=True)
    return qc


def larger_circuit(block: QuantumCircuit) -> QuantumCircuit:
    """A bigger program where q4 is a flag set to |1> *before* the block runs."""
    qc = QuantumCircuit(block.num_qubits, name="program")
    qc.x(4)            # flag qubit, owned by the surrounding program
    qc.x([0, 1, 2])    # all three controls on -> the block must flip q3
    qc.append(block.to_gate(label=block.name), range(block.num_qubits))
    return qc


def tvd(p: dict[str, int], q: dict[str, int]) -> float:
    keys = set(p) | set(q)
    sp, sq = sum(p.values()), sum(q.values())
    return 0.5 * sum(abs(p.get(k, 0) / sp - q.get(k, 0) / sq) for k in keys)


def run() -> dict:
    src, comp, safe = build_source(), build_compiled(), build_safe()
    out: dict = {"qiskit": qiskit.__version__}

    # (a) sampling
    cs = checks.sample(sampling_harness(src), SHOTS, SEED)
    cc = checks.sample(sampling_harness(comp), SHOTS, SEED)
    out["a_tvd"] = tvd(cs, cc)
    stat = checks.statistical_test(sampling_harness(comp), None, sampling_harness(src), shots=SHOTS, seed=SEED)
    out["a_status"] = stat.status.value

    # (b) proof + counterexample
    verdict, _ = checks.prove_equivalence(src, comp)
    out["b_proof"] = verdict
    report = run_checks(comp, reference=src, seed=SEED)
    out["b_verdict"] = report.verdict.value
    out["b_counterexample"] = checks.find_counterexample(comp, src)

    # (c) reuse as a sub-block
    want = checks.ideal_distribution(larger_circuit(src))
    got = checks.ideal_distribution(larger_circuit(comp))
    out["c_expected"] = {str(k): round(float(v), 4) for k, v in want.items()}
    out["c_got"] = {str(k): round(float(v), 4) for k, v in got.items()}

    # (d) fix
    out["d_proof_safe"] = checks.prove_equivalence(src, safe)[0]
    out["cx_default"] = comp.count_ops().get("cx", 0)
    out["cx_safe"] = safe.count_ops().get("cx", 0)
    return out


def _fmt(d: dict) -> str:
    return ", ".join(f"|{k}>: {float(v):g}" for k, v in d.items())


def main() -> int:
    r = run()
    print(f"Qiskit {r['qiskit']} | block: mcx(controls=[0,1,2], target=3) on 5 qubits, q4 idle")
    print(f"(a) Aer sampling from |0..0>, controls in superposition: TVD = {r['a_tvd']:.4f} -> {r['a_status']}")
    ce = r["b_counterexample"]
    print(f"(b) Veriq check vs source: {r['b_verdict']} (equivalence proof: {r['b_proof']})")
    print(f"    counterexample input {ce['input_state']} (bit order q4..q0), fidelity {ce['fidelity']}")
    print(f"    source   -> {_fmt(ce['reference_output_top'])}")
    print(f"    compiled -> {_fmt(ce['candidate_output_top'])}")
    print("(c) as a to_gate() sub-block, q4 = |1> flag, controls on (bit order q4..q0):")
    print(f"    expected {_fmt(r['c_expected'])}")
    print(f"    got      {_fmt(r['c_got'])}")
    print(f"(d) fix qubits_initially_zero=False: proof {r['d_proof_safe'].upper()} "
          f"(cx {r['cx_safe']} vs {r['cx_default']} with the default)")
    ok = (r["a_status"] == "PASS" and r["b_verdict"] == "FAIL" and r["b_proof"] == "not_equivalent" and r["c_got"] != r["c_expected"]
          and r["d_proof_safe"] == "equivalent")
    print("demo behaved as documented" if ok else "UNEXPECTED: demo did not reproduce the hazard")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
