"""Manual-review table and headline number for the QuanBench generations.

Every sample that passes the dataset's own tests but that Veriq did not prove equivalent to the canonical solution
was reviewed by hand (prompt, canonical, test and candidate code read side by side). The verdicts are encoded below
with their reasons; where a verdict rests on a computation, that computation is in spec_checks.py and its output in
results/spec_checks.json. This script joins the verdicts with raw/*.veriq.jsonl, fails loudly if a flagged passing
sample has no verdict, and writes results/manual_review.json and results/headline.json.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW, RES = HERE / "raw", HERE / "results"
RUNS = {"QuanBench44 / GPT-4.1 (T=0.8)": "quanbench44_gpt-4.1_T0.8", "QuanBench117 / GPT-4o": "quanbench117_gpt-4o"}

# Categories
WRONG = "wrong"                    # observable deviation from the prompt's contract on a classical (|0> or basis) input
WRONG_GATE = "wrong_on_superposed_inputs"  # gate-decomposition task; equal on every basis input, wrong on a superposed one
OK = "ok_dont_care"                # difference is unobservable under the contract (phase before measurement, ancilla, ...)
CONVENTION = "qubit_order_convention"  # equal up to a qubit-ordering convention the prompt does not fix
AMBIGUOUS = "ambiguous_or_inconsistent_spec"
EXCLUDED = "excluded_no_unique_answer"  # variational / heuristic task with no unique correct output
SUSPICIOUS = "suspicious_unconfirmed"
UNDECIDED = "undecided"

R = {
 "05": (EXCLUDED, "QAOA knapsack: heuristic; any circuit that samples a good solution is acceptable, no unique output."),
 "40": (EXCLUDED, "VQE ansatz: underspecified, and the canonical itself deviates from the prompt (undocumented U3(pi,0,pi), param[5] on q1)."),
 "04": (EXCLUDED, "QAOA MaxCut ansatz with free beta/gamma: ZZ/RX angle conventions (rz(2g) vs rzz(g), rx(2b)) are not fixed by the prompt."),
 "06": (OK, "Swap test: only the ancilla is measured and its distribution equals the canonical's."),
 "07": (OK, "Swap tests with individual ancillas: measured ancilla distribution equals the canonical's (fixed input)."),
 "12": (OK, "Deutsch-Jozsa: measured distribution equal for every input (measured_equal_all_inputs)."),
 "01": (OK, "Grover |00>: fixed-input circuit; same output state, differs only on inputs the task never uses."),
 "02": (OK, "State preparation from |000>: identical prepared state."),
 "17": (OK, "GHZ from |000>: identical distribution/state; the unitary differs only on unused inputs."),
 "23": (OK, "Fixed-input subtractor: same measured sum bits (different ancilla count)."),
 "26": (OK, "GHZ-vs-|+++> swap test: ancilla distribution equal."),
 "30": (OK, "OR gate: hand-checked on all four inputs (cx,cx,ccx computes a OR b on q2); extra copy qubit is allowed by the prompt's wording."),
 "62": (OK, "Bernstein-Vazirani: same measured distribution from |0>."),
 "65": (OK, "Grover |11>: same measured distribution; candidate unitary is the inverse of the canonical's on the 2 qubits."),
 "83": (OK, "Hadamard test (fixed input): ancilla distribution equal."),
 "85": (OK, "Hadamard test (fixed input): ancilla distribution equal."),
 "88": (OK, "Hadamard test (fixed input): ancilla distribution equal."),
 "106": (OK, "Swap test against |+>: measured ancilla statistics equal for every input."),
 "116": (OK, "QFT encoding of 5: measured distribution equal; difference is a phase before measurement."),
 "28": (OK, "CCCNOT: spec check shows the candidate equals CCCX on every clean-ancilla input (samples 0-2 even for a dirty ancilla); the canonical itself is broken (measures the ancilla instead of the target)."),
 "43": (OK, "Toffoli decomposition: spec check shows the candidate equals CCX up to global phase; the canonical is wrong (fails its own test), and the only issue is using h/t instead of the requested rz/sx gate set."),
 "08": (CONVENTION, "6-qubit QFT: spec check shows the candidate equals QFTGate up to bit reversal of inputs and/or outputs (textbook big-endian QFT); the prompt does not fix the qubit order."),
 "11": (AMBIGUOUS, "DJ 'oracle with bitstring 1100': the candidate implements f(x)=b.x (output 0011), the canonical uses the Qiskit-textbook oracle where the string only selects X padding (output 1111). Both are valid balanced oracles."),
 "21": (AMBIGUOUS, "MAJ: the prompt text, the canonical (Cuccaro MAJ) and the tests disagree with each other (the canonical fails the tests); the candidate matches neither text nor canonical but does satisfy the tests."),
 "79": (AMBIGUOUS, "'Grover-like brute force' Simon task is internally inconsistent; the candidate (two CZ = identity) outputs 00, which the test accepts. Not counted."),
 "25": (SUSPICIOUS, "QPE of the |00>-Grover operator: candidate marks 3 states (~a|~b), applies an extra G and uses H instead of the inverse QFT; its deterministic 000 could still be produced by a correct QPE on a phase-0 eigenstate, so not counted."),
 "09": (WRONG, "QPE of X: the eigenphases of X are 0 and 1/2, so a correct 3-bit QPE can only read 000 or 100; the candidate (controlled-phase angles pi, pi/2, pi/4 instead of powers of X) puts 57.3% of its mass on impossible outcomes. It passes because the test only checks the most likely outcome."),
 "13": (WRONG, "Simon s=11: candidate's 'oracle' (cx; x) makes the output always 00, which carries no information about s; a valid Simon circuit is uniform over {00,11}."),
 "78": (WRONG, "Simon s=10: candidate's oracle is constant (only an X on the output register), output always 00; a valid instance is uniform over 2 strings."),
 "81": (WRONG, "Simon s=001: candidate copies only one input bit (a 4-to-1 function), so the output is uniform over 2 strings instead of the 4 required; s cannot be recovered."),
 "114": (WRONG, "Swap test |++> vs |00>: candidate prepares the second register as |+0> (h on qubit 2), giving P(0)=0.75 instead of (1+1/4)/2=0.625."),
 "37": (None, "Controlled-Hadamard decomposition, see per-sample verdicts."),
}
PER_SAMPLE = {
 ("QuanBench44", "37"): {s: (WRONG_GATE, "ry(pi/4); cx; ry(-pi/4); cx implements controlled-(H.Z), not CH: equal on all basis inputs, but on control=|1>, target=|+> CH gives 01 with certainty and the candidate gives 11. The test composes only X on the control.") for s in range(5)},
 ("QuanBench117", "37"): {
    0: (WRONG_GATE, "Same controlled-(H.Z) construction as above: wrong on control=|1>, target=|+>."),
    4: (WRONG_GATE, "Same controlled-(H.Z) construction as above: wrong on control=|1>, target=|+>."),
    1: (WRONG, "Extra ry(pi/4) at the end: from |00> the target is rotated even though the control is 0 (P(10)=0.146); the test only checks the control=1 branch."),
    2: (WRONG, "Extra ry(pi/4) at the end: from |00> the target is rotated even though the control is 0 (P(10)=0.146); the test only checks the control=1 branch."),
    3: (OK, "h/t/cx construction: measured statistics equal CH for every input state (differs only by a diagonal phase before measurement)."),
 },
}
SAFE = {"unitary_equivalent"}


def main() -> int:
    RES.mkdir(exist_ok=True)
    rows, missing = [], []
    head = {}
    for label, stem in RUNS.items():
        ds = label.split(" /")[0]
        cnt = Counter()
        passed = 0
        for line in (RAW / f"{stem}.veriq.jsonl").open():
            r = json.loads(line)
            if not r["tests_passed"]:
                continue
            passed += 1
            cls = r["class"]
            if cls in SAFE:
                cnt["proved_equivalent_to_canonical"] += 1
                continue
            if cls == "no_circuit_pair":
                cnt["no_circuit_to_compare"] += 1
                continue
            ps = PER_SAMPLE.get((ds, r["task_id"]), {})
            if r["sample"] in ps:
                cat, why = ps[r["sample"]]
            elif r["task_id"] in R and R[r["task_id"]][0] is not None:
                cat, why = R[r["task_id"]]
            elif cls in ("undecided", "partially_undecided"):
                cat, why = UNDECIDED, "Veriq could not decide (e.g. mid-circuit measurement); not counted."
            else:
                missing.append((ds, r["task_id"], r["sample"], cls))
                continue
            cnt[cat] += 1
            rows.append({"dataset": ds, "task_id": r["task_id"], "sample": r["sample"], "veriq_class": cls,
                         "verdict": cat, "reason": why})
        wrong, wrong_any = cnt[WRONG], cnt[WRONG] + cnt[WRONG_GATE]
        decided = passed - cnt["no_circuit_to_compare"] - cnt[UNDECIDED] - cnt[EXCLUDED]
        head[label] = {"tests_passed": passed, **dict(sorted(cnt.items())),
                       "wrong_strict": wrong, "wrong_incl_superposed_inputs": wrong_any,
                       "decided_and_in_scope": decided,
                       "share_wrong_strict_of_passed": round(wrong / passed, 4),
                       "share_wrong_incl_superposed_of_passed": round(wrong_any / passed, 4)}
    if missing:
        raise SystemExit(f"flagged passing samples without a manual verdict: {missing}")
    tot_p = sum(h["tests_passed"] for h in head.values())
    tot_w = sum(h["wrong_strict"] for h in head.values())
    tot_wa = sum(h["wrong_incl_superposed_inputs"] for h in head.values())
    tot_d = sum(h["decided_and_in_scope"] for h in head.values())
    head["combined"] = {"tests_passed": tot_p, "wrong_strict": tot_w, "wrong_incl_superposed_inputs": tot_wa,
                        "decided_and_in_scope": tot_d,
                        "share_wrong_strict_of_passed": round(tot_w / tot_p, 4),
                        "share_wrong_incl_superposed_of_passed": round(tot_wa / tot_p, 4),
                        "share_wrong_incl_superposed_of_decided": round(tot_wa / tot_d, 4)}
    (RES / "manual_review.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    (RES / "headline.json").write_text(json.dumps(head, indent=1))
    print(json.dumps(head, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
