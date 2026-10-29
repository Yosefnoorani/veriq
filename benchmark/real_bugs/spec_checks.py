"""Independent specification checks for the QuanBench samples flagged during manual review.

The dataset's canonical solution is not always a reliable oracle (some canonicals fail their own tests or deviate
from the prompt), so for every flagged sample whose verdict depends on more than "same measured distribution as the
canonical", this script rebuilds the behaviour the *prompt* asks for and checks the captured candidate circuit
against it. Every number written to results/spec_checks.json is computed here from the captured QPY circuits.

Usage:  .venv/bin/python benchmark/real_bugs/spec_checks.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import CHGate, QFTGate
from qiskit.quantum_info import Operator, Statevector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import quanbench_veriq as qv  # noqa: E402
from veriq import checks  # noqa: E402

RAW = HERE / "raw"
CAPTURES = {"44": RAW / "quanbench44_gpt-4.1_T0.8.capture.jsonl", "117": RAW / "quanbench117_gpt-4o.capture.jsonl"}


def first_circuit(row):
    for c in row["calls"]:
        if c["role"] == "generated" and c["out"].get("kind") == "circuit":
            return qv.load(c["out"])
    return None


def unitary(qc):
    return Operator(checks.unitary_part(qc)).data


def dist_from_zero(qc):
    mm = qv.measured_map(qc)
    return qv.distribution(checks.unitary_part(qv.initial_prep_to_unitary(qc)), mm, qc.num_clbits)


def equal_up_to_phase(a, b, tol=1e-8):
    idx = np.unravel_index(np.argmax(np.abs(b)), b.shape)
    if abs(a[idx]) < 1e-12:
        return False
    ph = b[idx] / a[idx]
    return abs(abs(ph) - 1) < 1e-8 and np.abs(a * ph - b).max() < tol


def ch_spec():
    qc = QuantumCircuit(2)
    qc.append(CHGate(), [0, 1])
    return Operator(qc).data


def check_37(qc):
    Us, Uc = ch_spec(), unitary(qc)
    mm = qv.measured_map(qc)
    out = {"equals_CH_up_to_global_phase": bool(equal_up_to_phase(Us, Uc))}
    if mm:
        out["measured_stats_equal_CH_for_every_input"] = qv.measured_all_inputs(Us, Uc, sorted(mm))
    zero = QuantumCircuit(2)
    zero.append(CHGate(), [0, 1])
    pr, pc = np.abs(Us[:, 0]) ** 2, np.abs(Uc[:, 0]) ** 2
    out["tvd_from_00"] = round(0.5 * float(np.abs(pr - pc).sum()), 6)
    worst = max(0.5 * float(np.abs(np.abs(Us[:, x]) ** 2 - np.abs(Uc[:, x]) ** 2).sum()) for x in range(4))
    out["max_tvd_over_basis_inputs"] = round(worst, 6)
    # an explicit distinguishing input: control |1>, target |+>  (q0 = control)
    psi = Statevector.from_label("+1")  # label is q1 q0 -> q1=|+>, q0=|1>
    a, b = psi.evolve(Operator(Us)), psi.evolve(Operator(Uc))
    out["input_q0=1_q1=+"] = {"CH": {k: round(v, 4) for k, v in a.probabilities_dict().items() if v > 1e-9},
                              "candidate": {k: round(v, 4) for k, v in b.probabilities_dict().items() if v > 1e-9}}
    return out


def check_43(qc):
    ref = QuantumCircuit(3)
    ref.ccx(0, 1, 2)
    return {"equals_CCX_up_to_global_phase": bool(equal_up_to_phase(Operator(ref).data, unitary(qc)))}


def check_28(qc):
    """CCCX, controls 0,1,2, ancilla 3, target 4: the ancilla must be restored, for clean (|0>) and dirty ancilla."""
    ref = QuantumCircuit(5)
    ref.mcx([0, 1, 2], 4)
    Us, Uc = Operator(ref).data, unitary(qc)
    clean = [x for x in range(32) if not (x >> 3) & 1]
    return {"equals_CCCX_on_clean_ancilla_inputs": bool(equal_up_to_phase(Us[:, clean], Uc[:, clean])),
            "equals_CCCX_on_all_inputs_including_dirty_ancilla": bool(equal_up_to_phase(Us, Uc))}


def check_08(qc):
    n = qc.num_qubits
    q = QuantumCircuit(n)
    q.append(QFTGate(n), range(n))
    Q = Operator(q)
    C = Operator(checks.unitary_part(qc))
    sw = QuantumCircuit(n)
    for i in range(n // 2):
        sw.swap(i, n - 1 - i)
    S = Operator(sw)
    return {"equals_QFTGate": bool(C.equiv(Q)),
            "equals_QFT_with_output_bit_reversal": bool(C.equiv(Q.compose(S))),
            "equals_QFT_with_input_bit_reversal": bool(C.equiv(S.compose(Q))),
            "equals_QFT_with_input_and_output_reversal": bool(C.equiv(S.compose(Q).compose(S)))}


def truth_table(qc):
    U = unitary(qc)
    n = qc.num_qubits
    tt = {}
    for x in range(2 ** n):
        col = np.abs(U[:, x]) ** 2
        y = int(np.argmax(col))
        tt[format(x, f"0{n}b")] = format(y, f"0{n}b") if col[y] > 1 - 1e-9 else "superposition"
    return tt


def check_21(qc):
    """Prompt: q0=a, q1=b, q2=c; q2 <- a^b, q1 <- a^c, q0 <- maj. Cuccaro MAJ (the canonical): q1 <- a^b, q2 <- a^c."""
    tt = truth_table(qc)
    prompt_ok = cuccaro_ok = True
    for x, y in tt.items():
        a, b, c = int(x[2]), int(x[1]), int(x[0])
        maj = int(a + b + c >= 2)
        prompt = f"{a ^ b}{a ^ c}{maj}"
        cucc = f"{a ^ c}{a ^ b}{maj}"
        prompt_ok &= y == prompt
        cuccaro_ok &= y == cucc
    return {"matches_prompt_text_on_all_basis_inputs": prompt_ok, "matches_cuccaro_MAJ_on_all_basis_inputs": cuccaro_ok,
            "truth_table_q2q1q0": tt}


def check_09(qc):
    d = dist_from_zero(qc)
    # X has eigenphases 0 and 1/2; with 3 counting qubits an exact QPE can only read 000 or 100 (phase 0 / 0.5)
    allowed = {"000", "100"}
    bad = {k: round(v, 6) for k, v in d.items() if k not in allowed and v > 1e-9}
    return {"distribution": {k: round(v, 6) for k, v in d.items()}, "mass_on_impossible_outcomes": round(sum(bad.values()), 6),
            "impossible_outcomes": bad}


def check_114(qc):
    d = dist_from_zero(qc)
    expected = (1 + abs(np.vdot(Statevector.from_label("++").data, Statevector.from_label("00").data)) ** 2) / 2
    return {"P(ancilla=0)": round(d.get("0", 0.0), 6), "expected_P0_for_|++>_vs_|00>": round(float(expected), 6)}


def simon_check(s):
    """A valid Simon instance with hidden string s measures y uniformly over {y : y.s = 0 mod 2}."""
    def run(qc):
        d = dist_from_zero(qc)
        n = len(s)
        res = {"distribution": {k: round(v, 6) for k, v in d.items()}}
        for conv, ss in (("s_as_written", s), ("s_reversed", s[::-1])):
            perp = [format(y, f"0{n}b") for y in range(2 ** n)
                    if sum(int(a) * int(b) for a, b in zip(format(y, f"0{n}b"), ss)) % 2 == 0]
            uni = all(abs(d.get(y, 0) - 1 / len(perp)) < 1e-6 for y in perp)
            res[f"uniform_over_s_perp_{conv}"] = bool(uni)
        res["support_size"] = sum(1 for v in d.values() if v > 1e-9)
        res["required_support_size"] = 2 ** (len(s) - 1)
        return res
    return run


CHECKS = {
    ("44", "37"): check_37, ("117", "37"): check_37,
    ("117", "43"): check_43, ("117", "28"): check_28,
    ("44", "08"): check_08, ("117", "08"): check_08,
    ("117", "21"): check_21, ("117", "09"): check_09, ("117", "114"): check_114,
    ("117", "13"): simon_check("11"), ("117", "78"): simon_check("10"), ("117", "81"): simon_check("001"),
}


from quanbench_veriq import open_jsonl  # noqa: E402


def main():
    out = []
    for ds, path in CAPTURES.items():
        for line in open_jsonl(path):
            row = json.loads(line)
            fn = CHECKS.get((ds, row["task_id"]))
            if fn is None or not row["passed"]:
                continue
            qc = first_circuit(row)
            if qc is None:
                continue
            res = fn(qc)
            out.append({"dataset": f"QuanBench{ds}", "task_id": row["task_id"], "sample": row["sample"], **res})
            print(ds, row["task_id"], row["sample"], {k: v for k, v in res.items() if k not in ("truth_table_q2q1q0", "distribution")})
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "spec_checks.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
