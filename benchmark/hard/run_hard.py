"""Veriq hard round: 4 assistants x 7 non-standard tasks = 28 LLM-written circuits, plus a mutation study.

Usage:  .venv/bin/python benchmark/hard/run_hard.py [--no-mutants]
Inputs: benchmark/hard/raw/<assistant>.py   verbatim LLM output, never modified
        benchmark/hard/references.py        trusted references, verified against truth tables / target states
Output: benchmark/hard/results/results.json, results.md, mutation.json, reports/<assistant>_<task>.html|json

Research question: are there bugs that a sampling test passes but the formal proof catches?
1. The 28 real LLM circuits: proof, counterexample search, Aer statistical test, constraints, metrics.
2. Mutation study: realistic small bugs injected into each LLM circuit (delete a gate, negate an angle,
   pi written as 3.14, flipped cx direction, cp -> crz, p -> rz). Each mutant is judged by
   (a) the formal proof, (b) the Aer histogram test from |0...0> (what people usually run), (c) the exact
   output distribution from |0...0> (sampling with infinitely many shots), and (d) the exact output
   distributions from EVERY computational-basis input (an exhaustive classical truth-table test).
   A mutant is "proof-only" when the proof fails but (d) sees nothing: no measurement-based test that
   prepares basis states and measures in the computational basis can ever detect it, at any shot count.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qiskit import QuantumCircuit, transpile  # noqa: E402
from qiskit.circuit.library import CRZGate, RZGate  # noqa: E402
from qiskit.quantum_info import Statevector  # noqa: E402

from veriq import checks  # noqa: E402
from veriq.loader import load_circuit  # noqa: E402
from veriq.report import render_html, render_json  # noqa: E402
from veriq.runner import run_checks  # noqa: E402


def _load_refs():
    spec = importlib.util.spec_from_file_location("veriq_hard_references", HERE / "references.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _load_refs()
RAW = HERE / "raw"
OUT = HERE / "results"
REPORTS = OUT / "reports"
ASSISTANTS = {
    "chatgpt": "ChatGPT (free, Think)",
    "claude": "Claude (free, default model)",
    "gemini": "Gemini (Pro)",
    "perplexity": "Perplexity (free, default)",
}
BASIS = ["cx", "rz", "sx", "x"]
LINEAR_TASKS = ("c3x_linear", "reverse6_nn")
MAX_PER_OPERATOR = 30
SEED = 2026


# ----------------------------------------------------------------------------- metrics

def cx_after_transpile(qc: QuantumCircuit, linear: bool, zero_init: bool = False) -> dict:
    """Standalone-block cost: qubits_initially_zero=False unless the task is a state preparation."""
    n = qc.num_qubits
    kw = dict(basis_gates=BASIS, optimization_level=1, seed_transpiler=SEED, qubits_initially_zero=zero_init)
    if linear:
        kw["coupling_map"] = [[i, i + 1] for i in range(n - 1)] + [[i + 1, i] for i in range(n - 1)]
    tq = transpile(qc, **kw)
    return {"cx": int(tq.count_ops().get("cx", 0)), "depth": tq.depth(), "size": tq.size()}


def qpe_iqft_block(qc: QuantumCircuit) -> QuantumCircuit:
    """Everything after the last instruction touching the eigenstate qubit q3, restricted to q0..q2."""
    last = max(i for i, inst in enumerate(qc.data) if any(qc.find_bit(q).index == 3 for q in inst.qubits))
    blk = QuantumCircuit(3)
    for inst in qc.data[last + 1:]:
        blk.append(inst.operation, [qc.find_bit(q).index for q in inst.qubits])
    return blk


# ----------------------------------------------------------------------------- mutation study

def _rebuild(qc: QuantumCircuit, data) -> QuantumCircuit:
    m = QuantumCircuit(qc.num_qubits, global_phase=qc.global_phase)
    for op, qs in data:
        m.append(op, qs)
    return m


def _items(qc: QuantumCircuit):
    return [(inst.operation, [qc.find_bit(q).index for q in inst.qubits]) for inst in qc.data]


def mutants(qc: QuantumCircuit, rng: random.Random):
    """Yield (operator, description, mutant circuit)."""
    items = _items(qc)

    def pick(idxs):
        idxs = list(idxs)
        return idxs if len(idxs) <= MAX_PER_OPERATOR else sorted(rng.sample(idxs, MAX_PER_OPERATOR))

    for i in pick(range(len(items))):
        op, qs = items[i]
        yield "delete_gate", f"delete #{i} {op.name}{tuple(qs)}", _rebuild(qc, items[:i] + items[i + 1:])
    par = [i for i, (op, _) in enumerate(items) if op.params and all(isinstance(p, float) for p in op.params)]
    for i in pick(par):
        op, qs = items[i]
        new = op.copy()
        new.params = [-p for p in op.params]
        yield "negate_angle", f"negate #{i} {op.name}({op.params[0]:.4f}){tuple(qs)}", \
            _rebuild(qc, items[:i] + [(new, qs)] + items[i + 1:])
    if par:
        data = []
        for op, qs in items:
            if op.params and all(isinstance(p, float) for p in op.params):
                op = op.copy()
                op.params = [p * 3.14 / math.pi for p in op.params]
            data.append((op, qs))
        yield "pi_as_3.14", f"pi written as 3.14 in all {len(par)} angles", _rebuild(qc, data)
    cxs = [i for i, (op, _) in enumerate(items) if op.name == "cx"]
    for i in pick(cxs):
        op, qs = items[i]
        yield "flip_cx", f"flip #{i} cx{tuple(qs)} -> cx{tuple(qs[::-1])}", \
            _rebuild(qc, items[:i] + [(op, qs[::-1])] + items[i + 1:])
    cps = [i for i, (op, _) in enumerate(items) if op.name == "cp"]
    for i in pick(cps):
        op, qs = items[i]
        yield "cp_to_crz", f"#{i} cp({op.params[0]:.4f}) -> crz (same angle){tuple(qs)}", \
            _rebuild(qc, items[:i] + [(CRZGate(op.params[0]), qs)] + items[i + 1:])
    ps = [i for i, (op, _) in enumerate(items) if op.name == "p"]
    for i in pick(ps):
        op, qs = items[i]
        yield "p_to_rz", f"#{i} p({op.params[0]:.4f}) -> rz (same angle){tuple(qs)}", \
            _rebuild(qc, items[:i] + [(RZGate(op.params[0]), qs)] + items[i + 1:])


def _probs(sv: Statevector) -> np.ndarray:
    return np.abs(sv.data) ** 2


def judge_mutant(m: QuantumCircuit, ref: QuantumCircuit, mode: str) -> dict:
    if mode == "state":
        proof = checks.state_equivalence(m, ref).status.value
    else:
        v, _ = checks.prove_equivalence(m, ref, timeout=30)
        proof = {"equivalent": "PASS", "not_equivalent": "FAIL"}.get(v, "INCONCLUSIVE")
    hist = checks.statistical_test(m, None, ref, shots=4096, seed=7).status.value
    n = m.num_qubits
    p0m, p0r = _probs(Statevector(m)), _probs(Statevector(ref))
    tvd0 = 0.5 * float(np.abs(p0m - p0r).sum())
    out = {"proof": proof, "aer_hist_from_zero": hist, "exact_tvd_from_zero": round(tvd0, 6)}
    if mode == "unitary":
        from qiskit.quantum_info import Operator
        Um, Ur = np.abs(Operator(m).data) ** 2, np.abs(Operator(ref).data) ** 2   # column x = output dist of |x>
        worst = float((0.5 * np.abs(Um - Ur).sum(axis=0)).max())
        out["exact_max_tvd_all_basis_inputs"] = round(worst, 6)
    return out


def classify(j: dict, mode: str) -> str:
    if j["proof"] == "PASS":
        return "equivalent_mutant"
    if j["proof"] != "FAIL":
        return "undecided"
    if j["aer_hist_from_zero"] == "FAIL":
        return "caught_by_histogram"
    if mode == "unitary" and j["exact_max_tvd_all_basis_inputs"] > 1e-9:
        return "missed_by_histogram_caught_by_truth_table"
    if j["exact_tvd_from_zero"] > 1e-9:
        return "proof_only_sampling_too_weak"      # visible in theory, below the statistical threshold
    return "proof_only_invisible_to_sampling"       # no basis-input sampling can ever see it


def mutation_study() -> dict:
    rng = random.Random(SEED)
    rows = []
    for a in ASSISTANTS:
        for task, spec in R.TASKS.items():
            cand = load_circuit(RAW / f"{a}.py", spec["fn"])
            ref = getattr(R, spec["fn"])()
            for op_name, desc, m in mutants(cand, rng):
                j = judge_mutant(m, ref, spec["mode"])
                rows.append({"assistant": a, "task": task, "mode": spec["mode"], "operator": op_name,
                             "mutation": desc, **j, "class": classify(j, spec["mode"])})
    summary: dict = {}
    for r in rows:
        s = summary.setdefault(r["operator"], {})
        s[r["class"]] = s.get(r["class"], 0) + 1
    by_task: dict = {}
    for r in rows:
        s = by_task.setdefault(r["task"], {})
        s[r["class"]] = s.get(r["class"], 0) + 1
    return {"seed": SEED, "max_per_operator_per_circuit": MAX_PER_OPERATOR, "total_mutants": len(rows),
            "by_operator": summary, "by_task": by_task, "mutants": rows}


# ----------------------------------------------------------------------------- main benchmark

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mutants", action="store_true")
    args = ap.parse_args(argv)
    REPORTS.mkdir(parents=True, exist_ok=True)
    print("Verifying references ...")
    ref_checks = R.verify_references()
    rows = []
    t_all = time.perf_counter()
    ref_path = str(HERE / "references.py")
    for a in ASSISTANTS:
        raw = RAW / f"{a}.py"
        for task, spec in R.TASKS.items():
            rep = run_checks(str(raw), reference=ref_path, function=spec["fn"], reference_function=spec["fn"],
                             mode=spec["mode"], allowed_gates=spec.get("allowed_gates"),
                             coupling=spec.get("coupling"), no_black_boxes=spec.get("no_black_boxes", False))
            stem = f"{a}_{task}"
            (REPORTS / f"{stem}.html").write_text(render_html(rep))
            (REPORTS / f"{stem}.json").write_text(render_json(rep))
            st = {c.name: c for c in rep.checks}
            row = {"assistant": a, "task": task, "mode": spec["mode"], "verdict": rep.verdict.value,
                   "seconds": round(rep.seconds, 3), "checks": {c.name: c.status.value for c in rep.checks},
                   "summaries": {c.name: c.summary for c in rep.checks if c.status.value != "PASS"},
                   "report_html": f"reports/{stem}.html"}
            if "Build" in st:
                row["build_error"] = st["Build"].evidence["message"]
            else:
                cand = load_circuit(raw, spec["fn"])
                ref = getattr(R, spec["fn"])()
                row["histogram_alone"] = checks.statistical_test(cand, None, ref, shots=4096, seed=7).status.value
                src = rep.metrics["source"]
                row["metrics"] = {
                    "size": src["size"], "depth": src["depth"], "gate_counts": src["gate_counts"],
                    "two_qubit_gates": src["two_qubit_gates"], "multi_qubit_gates": src["multi_qubit_gates"],
                    "cx_raw": src["gate_counts"].get("cx", 0),
                    "transpiled_all_to_all": cx_after_transpile(cand, linear=False, zero_init=spec["mode"] == "state"),
                }
                if task in LINEAR_TASKS:
                    row["metrics"]["transpiled_linear"] = cx_after_transpile(cand, linear=True)
                row["zero_init_hazard"] = st["Transpile integrity"].evidence.get("zero_init_hazard")
                if task == "qpe_t":
                    blk = qpe_iqft_block(cand)
                    from qiskit.circuit.library import QFTGate
                    iq = QuantumCircuit(3)
                    iq.append(QFTGate(3).inverse(), [0, 1, 2])
                    v, _ = checks.prove_equivalence(blk, iq)
                    row["iqft_block_equals_QFTGate3_inverse"] = v == "equivalent"
                if task == "c3x_linear":
                    from qiskit.quantum_info import Operator
                    U = Operator(cand).data
                    k = int(np.argmax(np.abs(R.expected_unitary(task).ravel())))
                    row["global_phase_vs_spec_rad"] = round(float(np.angle(U.ravel()[k])), 6)
            rows.append(row)
            print(f"  {rep.verdict.value:5s} {a:11s} {task:12s} hist={row.get('histogram_alone')}")

    score = {a: sum(1 for r in rows if r["assistant"] == a and r["verdict"] == "PASS") for a in ASSISTANTS}
    result = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt_date": "2026-10-27",
        "assistants": ASSISTANTS,
        "tasks": {k: {kk: vv for kk, vv in v.items() if kk != "fn"} | {"function": v["fn"]} for k, v in R.TASKS.items()},
        "reference_verification": ref_checks,
        "score": score, "total_pass": sum(score.values()), "total": len(rows),
        "seconds_total": round(time.perf_counter() - t_all, 2),
        "results": rows,
    }
    mut = None
    if not args.no_mutants:
        print("Mutation study ...")
        t = time.perf_counter()
        mut = mutation_study()
        mut["seconds"] = round(time.perf_counter() - t, 1)
        (OUT / "mutation.json").write_text(json.dumps(mut, indent=1))
        result["mutation_summary"] = {k: v for k, v in mut.items() if k != "mutants"}
        print(f"  {mut['total_mutants']} mutants in {mut['seconds']}s")
    elif (OUT / "mutation.json").exists():
        mut = json.loads((OUT / "mutation.json").read_text())
        result["mutation_summary"] = {k: v for k, v in mut.items() if k != "mutants"}
    (OUT / "results.json").write_text(json.dumps(result, indent=2))
    (OUT / "results.md").write_text(render_md(result, mut))
    print(f"Score: {score}  total {result['total_pass']}/{result['total']}")
    return 0


CLASSES = ["caught_by_histogram", "missed_by_histogram_caught_by_truth_table", "proof_only_sampling_too_weak",
           "proof_only_invisible_to_sampling", "equivalent_mutant", "undecided"]


def render_md(res: dict, mut: dict | None) -> str:
    rows = res["results"]
    tasks = list(res["tasks"])
    by = {(r["assistant"], r["task"]): r for r in rows}
    L = ["# Veriq hard round: 28 LLM-written circuits (4 assistants x 7 non-standard tasks)", "",
         f"Generated {res['generated']}. Prompt sent {res['prompt_date']}. "
         f"Total {res['total_pass']}/{res['total']} PASS.", "", "## Verdicts", "",
         "| assistant | " + " | ".join(tasks) + " | score |", "|---" * (len(tasks) + 2) + "|"]
    for a in res["assistants"]:
        L.append(f"| {a} | " + " | ".join(by[(a, t)]["verdict"] for t in tasks) + f" | {res['score'][a]}/7 |")
    L += ["", "Checks per task: proof (QCEC, matrix fallback) or exact state fidelity (qpe_t, bv22), "
          "counterexample search, Aer statistical test, no-black-boxes; c3x_linear and reverse6_nn also "
          "enforce the gate set and a linear coupling map on the circuit as written; add3 enforces {x,cx,ccx,mcx}.",
          "", "## Failures", ""]
    fails = [r for r in rows if r["verdict"] != "PASS"]
    L += [f"- **{r['assistant']} / {r['task']}**: {r['verdict']} — " + "; ".join(
        f"{k}: {v}" for k, v in r["summaries"].items()) for r in fails] or ["None."]
    L += ["", "## Cost (CX count) — as written / transpiled to {cx,rz,sx,x} opt 1 all-to-all / on a linear chain", "",
          "| task | " + " | ".join(res["assistants"]) + " | spread |", "|---" * (len(res["assistants"]) + 2) + "|"]
    for t in tasks:
        cells, vals = [], []
        for a in res["assistants"]:
            m = by[(a, t)].get("metrics")
            if not m:
                cells.append("n/a")
                continue
            c = m["transpiled_linear"]["cx"] if "transpiled_linear" in m else m["transpiled_all_to_all"]["cx"]
            vals.append(c)
            extra = f" / lin {m['transpiled_linear']['cx']}" if "transpiled_linear" in m else ""
            cells.append(f"{m['cx_raw']} / {m['transpiled_all_to_all']['cx']}{extra}")
        spread = f"{max(vals) / min(vals):.1f}x" if vals and min(vals) else "-"
        L.append(f"| {t} | " + " | ".join(cells) + f" | {spread} |")
    L += ["", "Spread = max/min of the transpiled CX count (linear chain for c3x_linear and reverse6_nn).", "",
          "## Diagnostics", ""]
    for a in res["assistants"]:
        r = by[(a, "qpe_t")]
        if "iqft_block_equals_QFTGate3_inverse" in r:
            L.append(f"- {a} qpe_t: inverse-QFT block alone equals QFTGate(3).inverse() as a unitary: "
                     f"{r['iqft_block_equals_QFTGate3_inverse']}")
    for a in res["assistants"]:
        r = by[(a, "c3x_linear")]
        if "global_phase_vs_spec_rad" in r:
            L.append(f"- {a} c3x_linear: global phase vs. exact C3X = {r['global_phase_vs_spec_rad']} rad "
                     f"(gates: {r['metrics']['gate_counts']})")
    hz = [k for k, r in by.items() if r.get("zero_init_hazard")]
    L += ["", "### Toolchain finding: `qubits_initially_zero` hazard", "",
          "Qiskit's default `transpile()` assumes every qubit starts in |0> and lets HighLevelSynthesis borrow "
          "still-untouched qubits as *clean* ancillas when it decomposes an `mcx`. The compiled circuit is then "
          "correct from |0...0> but NOT equal as a unitary, so `transpile(oracle).to_gate()` reused inside a larger "
          "algorithm would be silently wrong. A histogram from |0...0> can never see this; the unitary proof does. "
          "Veriq now compiles unitary-mode tasks with `qubits_initially_zero=False` and flags the hazard.", "",
          f"Circuits where the default compile is not unitary-equivalent ({len(hz)}/28): "
          + (", ".join(f"{a}/{t}" for a, t in sorted(hz)) or "none") + ". "
          "The LLM circuits themselves are correct."]
    if mut:
        L += ["", "## Mutation study: which injected bugs does sampling miss?", "",
              f"{mut['total_mutants']} mutants (seed {mut['seed']}, up to {mut['max_per_operator_per_circuit']} "
              "per operator per circuit).", "",
              "| operator | " + " | ".join(CLASSES) + " |", "|---" * (len(CLASSES) + 1) + "|"]
        for op, s in mut["by_operator"].items():
            L.append(f"| {op} | " + " | ".join(str(s.get(c, 0)) for c in CLASSES) + " |")
        tot = {c: sum(s.get(c, 0) for s in mut["by_operator"].values()) for c in CLASSES}
        L.append("| **total** | " + " | ".join(f"**{tot[c]}**" for c in CLASSES) + " |")
        L += ["", "| task | " + " | ".join(CLASSES) + " |", "|---" * (len(CLASSES) + 1) + "|"]
        for t, s in mut["by_task"].items():
            L.append(f"| {t} | " + " | ".join(str(s.get(c, 0)) for c in CLASSES) + " |")
        po = [m for m in mut["mutants"] if m["class"].startswith("proof_only")]
        real = mut["total_mutants"] - tot["equivalent_mutant"] - tot["undecided"]
        L += ["", f"**Headline:** of {real} genuinely wrong mutants, the standard Aer histogram from |0...0> "
              f"catches only {tot['caught_by_histogram']} ({100 * tot['caught_by_histogram'] / real:.0f}%). "
              f"{tot['missed_by_histogram_caught_by_truth_table']} more need an exhaustive basis-input sweep, and "
              f"{len(po)} ({100 * len(po) / real:.1f}%) are caught by the formal proof alone."]
        L += ["", "Classes: *caught_by_histogram* = the usual Aer test from |0...0> FAILs; "
              "*missed_by_histogram_caught_by_truth_table* = only an exhaustive basis-input sweep sees it; "
              "*proof_only_sampling_too_weak* = the |0...0> distribution differs but below the statistical "
              "threshold (4096 shots, TVD 0.05); *proof_only_invisible_to_sampling* = every basis input gives "
              "exactly the reference distribution, so no such sampling test can ever detect it.", "",
              f"### Examples of proof-only bugs ({len(po)} total)", ""]
        seen = set()
        for m in po:
            key = (m["task"], m["operator"])
            if key in seen:
                continue
            seen.add(key)
            L.append(f"- {m['assistant']}/{m['task']}: {m['mutation']} — proof FAIL, Aer histogram "
                     f"{m['aer_hist_from_zero']}, exact TVD from |0..0> {m['exact_tvd_from_zero']}"
                     + (f", worst TVD over all basis inputs {m['exact_max_tvd_all_basis_inputs']}"
                        if "exact_max_tvd_all_basis_inputs" in m else ""))
    L += ["", "## Reference verification", ""] + [f"- {k}: {v}" for k, v in res["reference_verification"].items()]
    L += ["", "Per-circuit HTML reports: `results/reports/<assistant>_<task>.html`. "
          "All mutants: `results/mutation.json`.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
