"""Veriq week-2 benchmark: 4 assistants x 7 tasks = 28 LLM-written circuits.

Usage:  .venv/bin/python benchmark/run_llm.py
Inputs: benchmark/llm/raw/<assistant>.py (verbatim LLM output, never modified)
        benchmark/references.py (trusted, independently verified references)
Output: benchmark/results/results.json, results.md, reports/<assistant>_<task>.html|json
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from qiskit import QuantumCircuit  # noqa: E402

import references as R  # noqa: E402
from veriq import checks  # noqa: E402
from veriq.loader import BuildError, load_circuit  # noqa: E402
from veriq.models import Status  # noqa: E402
from veriq.report import render_html, render_json  # noqa: E402
from veriq.runner import run_checks  # noqa: E402

RAW = HERE / "llm" / "raw"
OUT = HERE / "results"
REPORTS = OUT / "reports"
ASSISTANTS = {
    "chatgpt": "ChatGPT (free, Think)",
    "claude": "Claude (Sonnet 5.5, free)",
    "gemini": "Gemini (Pro, free; errored twice, answered on 3rd try)",
    "perplexity": "Perplexity (default, free)",
}
STRICT_ADDER_GATES = ["x", "cx", "ccx"]


def histogram_only(cand: QuantumCircuit, ref: QuantumCircuit) -> str:
    """The naive test: run once from |0...0>, compare the histogram with the reference's ideal one."""
    return checks.statistical_test(cand, None, ref, shots=4096, seed=7).status.value


def chatgpt_adder_intent() -> dict:
    """Diagnosis for ChatGPT's adder: re-execute its source in a sandbox where a 4-argument
    ccx(c1, c2, c3, t) is read as the 3-control X it was obviously meant to be. The raw file
    is not modified; this only tells us whether the logic was right apart from the API misuse."""
    src = (RAW / "chatgpt.py").read_text()

    class Lenient(QuantumCircuit):
        def ccx(self, *args, **kw):  # noqa: D401
            if len(args) == 4 and all(isinstance(a, int) for a in args):
                return self.mcx(list(args[:3]), args[3])
            return super().ccx(*args, **kw)

    g = {"QuantumCircuit": Lenient, "__name__": "chatgpt_lenient"}
    exec(compile(src.replace("from qiskit import QuantumCircuit", ""), "chatgpt_lenient", "exec"), g)
    qc = g["build_adder2"]()
    verdict, _ = checks.prove_equivalence(QuantumCircuit(5).compose(qc), R.build_adder2())
    return {"lenient_ccx_as_mcx_equivalent_to_reference": verdict == "equivalent",
            "lenient_gate_counts": {k: int(v) for k, v in qc.count_ops().items()}}


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    print("Verifying references ...")
    ref_checks = R.verify_references()
    rows = []
    t_all = time.perf_counter()
    for a in ASSISTANTS:
        raw = RAW / f"{a}.py"
        for task, spec in R.TASKS.items():
            rep = run_checks(str(raw), reference=str(HERE / "references.py"), function=spec["fn"],
                             reference_function=spec["fn"], mode=spec["mode"],
                             allowed_gates=spec.get("allowed_gates"))
            stem = f"{a}_{task}"
            (REPORTS / f"{stem}.html").write_text(render_html(rep))
            (REPORTS / f"{stem}.json").write_text(render_json(rep))
            st = {c.name: c for c in rep.checks}
            row = {"assistant": a, "task": task, "mode": spec["mode"], "verdict": rep.verdict.value,
                   "seconds": round(rep.seconds, 3),
                   "checks": {c.name: c.status.value for c in rep.checks},
                   "report_html": f"reports/{stem}.html"}
            if "Build" in st:
                row["error_type"] = st["Build"].evidence["error_type"]
                row["build_error"] = st["Build"].evidence["message"]
                row["histogram_alone"] = "n/a (no circuit to run)"
                row["histogram_alone_would_catch"] = None
            else:
                cand = load_circuit(raw, spec["fn"])
                ref = load_circuit(HERE / "references.py", spec["fn"])
                h = histogram_only(cand, ref)
                row["histogram_alone"] = h
                row["histogram_alone_would_catch"] = (h == "FAIL") if rep.verdict == Status.FAIL else None
                eq = st.get("State equivalence (from |0...0>)") or st.get("Reference equivalence")
                if spec["mode"] == "state":
                    row["fidelity"] = eq.evidence.get("fidelity")
                if eq.evidence.get("counterexample"):
                    row["counterexample"] = eq.evidence["counterexample"]
                m = rep.metrics
                comp = next(iter(m["compiled"].values())) if m.get("compiled") else {}
                row["metrics"] = {
                    "size": m["source"]["size"], "depth": m["source"]["depth"],
                    "two_qubit_gates": m["source"]["two_qubit_gates"],
                    "multi_qubit_gates": m["source"]["multi_qubit_gates"],
                    "gate_counts": m["source"]["gate_counts"],
                    "compiled_cx": comp.get("gate_counts", {}).get("cx"),
                    "compiled_depth": comp.get("depth"),
                    "compiled_size": comp.get("size"),
                }
                if task == "adder2":
                    g = checks.gate_set_check(cand, STRICT_ADDER_GATES)
                    row["strict_gate_set_x_cx_ccx"] = {"status": g.status.value,
                                                       "violations": g.evidence["violations"]}
            rows.append(row)
            print(f"  {rep.verdict.value:5s} {a:11s} {task:8s} hist={row['histogram_alone']}")

    diagnostics = {"chatgpt/adder2": chatgpt_adder_intent()}

    root_causes = {
        ("chatgpt", "adder2"): (
            "build_adder2 calls qc.ccx(1, 0, 2, 4) and qc.ccx(3, 0, 2, 4) with four qubits, but Qiskit's ccx takes "
            "exactly two controls and a target, so the 4th argument is read as ctrl_state=4 and the call raises "
            "CircuitError('invalid control state specification'); no circuit is ever produced."),
    }
    for r in rows:
        if r["verdict"] == "FAIL":
            key = (r["assistant"], r["task"])
            if key not in root_causes:
                raise SystemExit(f"FAIL without a verified root cause: {key} -- inspect and add one")
            r["root_cause"] = root_causes[key]
    if diagnostics["chatgpt/adder2"]["lenient_ccx_as_mcx_equivalent_to_reference"]:
        rows_by = {(r["assistant"], r["task"]): r for r in rows}
        rows_by[("chatgpt", "adder2")]["root_cause"] += (
            " If those two calls are read as 3-control X gates (mcx), the adder logic is correct, "
            "so the bug is purely the API misuse.")

    score = {a: sum(1 for r in rows if r["assistant"] == a and r["verdict"] == "PASS") for a in ASSISTANTS}
    result = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt_date": "2026-10-27",
        "assistants": ASSISTANTS,
        "tasks": {k: {kk: vv for kk, vv in v.items() if kk != "fn"} | {"function": v["fn"]} for k, v in R.TASKS.items()},
        "reference_verification": ref_checks,
        "score": score,
        "total_pass": sum(score.values()), "total": len(rows),
        "seconds_total": round(time.perf_counter() - t_all, 2),
        "diagnostics": diagnostics,
        "results": rows,
    }
    (OUT / "results.json").write_text(json.dumps(result, indent=2))
    (OUT / "results.md").write_text(render_md(result))
    print(f"Score: {score}  total {result['total_pass']}/{result['total']}  ({result['seconds_total']}s)")
    return 0


def render_md(res: dict) -> str:
    rows = res["results"]
    tasks = list(res["tasks"])
    by = {(r["assistant"], r["task"]): r for r in rows}
    L = ["# Veriq week 2: 28 LLM-written circuits (4 assistants x 7 tasks)", "",
         f"Generated {res['generated']}. Prompts sent {res['prompt_date']} (free plans). "
         f"Total {res['total_pass']}/{res['total']} PASS in {res['seconds_total']} s.", "",
         "Note: Gemini Pro returned an error twice (no code) and answered on the third try.", "",
         "## Verdicts", "", "| assistant | " + " | ".join(tasks) + " | score |",
         "|---" * (len(tasks) + 2) + "|"]
    for a in res["assistants"]:
        L.append(f"| {a} | " + " | ".join(by[(a, t)]["verdict"] for t in tasks) + f" | {res['score'][a]}/7 |")
    L += ["", "Modes: state = prepared state from |0...0> up to global phase (ghz5, w3, grover3); "
          "unitary = full unitary up to global phase (qft4, iqft3, toffoli, adder2). "
          "toffoli also enforces the gate set {h,t,tdg,s,sdg,cx}.", "", "## Failures", ""]
    fails = [r for r in rows if r["verdict"] == "FAIL"]
    if not fails:
        L.append("None.")
    for r in fails:
        hist = r["histogram_alone"]
        L.append(f"- **{r['assistant']} / {r['task']}** ({r.get('error_type', 'wrong result')}): {r['root_cause']} "
                 f"Histogram-only test: {hist}.")
    L += ["", "## Quality of passing circuits (as written / after transpiling to rz,sx,x,cx + linear coupling, opt 3)", "",
          "| task | assistant | size | depth | 2q gates | 3q+ gates | gates | compiled cx | compiled depth |",
          "|---|---|---|---|---|---|---|---|---|"]
    for t in tasks:
        for a in res["assistants"]:
            r = by[(a, t)]
            if r["verdict"] != "PASS":
                continue
            m = r["metrics"]
            gc = ", ".join(f"{k}:{v}" for k, v in m["gate_counts"].items())
            L.append(f"| {t} | {a} | {m['size']} | {m['depth']} | {m['two_qubit_gates']} | {m['multi_qubit_gates']} "
                     f"| {gc} | {m['compiled_cx']} | {m['compiled_depth']} |")
    L += ["", "## Adder under a strict {x, cx, ccx} reading of the spec (informational, not scored)", ""]
    for a in res["assistants"]:
        r = by[(a, "adder2")]
        s = r.get("strict_gate_set_x_cx_ccx")
        L.append(f"- {a}: " + ("n/a (does not build)" if s is None else
                               f"{s['status']}" + (f" (uses {s['violations']})" if s["violations"] else "")))
    L += ["", "## Reference verification", ""] + [f"- {k}: {v}" for k, v in res["reference_verification"].items()]
    L += ["", "Per-circuit HTML reports: `results/reports/<assistant>_<task>.html`.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
