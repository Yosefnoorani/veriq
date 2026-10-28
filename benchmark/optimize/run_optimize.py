"""Verified CX optimization of the 28 hard-round circuits (4 assistants x 7 tasks).

Reads benchmark/hard/raw/*.py (never modified), optimizes each circuit with `veriq.optimize.optimize_circuit`
in the task's mode (state tasks: same state from |0..0>; linear-coupling tasks: routed on a line, proof up to
the routed layout), and writes results.json + results.md next to this file.

"before" = the hard-round cost metric (Qiskit opt=1, seed 2026, qubits_initially_zero=False, all-to-all or
linear as in the task) and the plain opt=0 baseline. "after" = the cheapest PROVEN-equivalent candidate.
The optimized circuit is equivalent to the assistant's circuit, not necessarily to the reference: a wrong
circuit stays wrong (its hard-round verdict is shown).

    .venv/bin/python benchmark/optimize/run_optimize.py [--budget 120] [--seeds 4]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
HARD = ROOT / "benchmark" / "hard"

from veriq.loader import load_circuit  # noqa: E402
from veriq.optimize import optimize_circuit  # noqa: E402

ASSISTANTS = ["chatgpt", "claude", "gemini", "perplexity"]
LINEAR_TASKS = ("c3x_linear", "reverse6_nn")


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=120.0)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--only", help="assistant/task filter, e.g. claude or claude/maj5")
    args = ap.parse_args(argv)
    R = _mod("veriq_hard_references", HARD / "references.py")
    H = _mod("veriq_hard_run", HARD / "run_hard.py")
    hard = {(r["assistant"], r["task"]): r for r in json.loads((HARD / "results" / "results.json").read_text())["results"]}
    rows = []
    t_all = time.perf_counter()
    for a in ASSISTANTS:
        for task, spec in R.TASKS.items():
            if args.only and args.only not in (a, f"{a}/{task}"):
                continue
            row = {"assistant": a, "task": task, "mode": spec["mode"],
                   "hard_verdict": hard.get((a, task), {}).get("verdict")}
            try:
                qc = load_circuit(HARD / "raw" / f"{a}.py", spec["fn"])
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {exc}"[:300]
                rows.append(row)
                continue
            linear = task in LINEAR_TASKS
            row["coupling"] = "linear" if linear else None
            row["before_opt1"] = H.cx_after_transpile(qc, linear)
            r = optimize_circuit(qc, mode=spec["mode"], coupling="linear" if linear else None,
                                 seeds=args.seeds, timeout=30.0, budget=args.budget)
            row["baseline_opt0"] = {k: r["baseline"][k] for k in ("cx", "depth")}
            row["qiskit_level3"] = r["qiskit_level3"]
            row["counts"] = r["counts"]
            row["tried"] = r["tried"]
            row["seconds"] = r["seconds"]
            row["proof_scope"] = r["proof_scope"]
            b = r["best"]
            if b:
                row["after"] = {"cx": b["cx"], "depth": b["depth"], "size": b["size"], "config": b["config"],
                                "status": b["status"], "method": b["method"]}
                row["cx_saved_vs_opt1"] = row["before_opt1"]["cx"] - b["cx"]
            else:
                row["after"] = None
            print(f"{a:10s} {task:12s} opt1 cx={row['before_opt1']['cx']:4d}  ->  "
                  f"{(b['cx'] if b else '-')!s:>4} ({b['method'] if b else 'NOT PROVEN'})  {r['seconds']:.1f}s",
                  flush=True)
            rows.append(row)
    res = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"),
           "budget_s": args.budget, "seeds": args.seeds, "seconds_total": round(time.perf_counter() - t_all, 1),
           "rows": rows}
    if not args.only:
        (HERE / "results.json").write_text(json.dumps(res, indent=1, default=str))
        (HERE / "results.md").write_text(render_md(res))
    return 0


def render_md(res) -> str:
    rows = res["rows"]
    ok = [r for r in rows if r.get("after")]
    L = ["# Verified CX optimization of the hard-round circuits", "",
         f"Generated {res['generated']} by `benchmark/optimize/run_optimize.py` (budget {res['budget_s']:g}s per "
         f"circuit, {res['seeds']} seeds; total {res['seconds_total']:g}s).", "",
         "* **before** = the hard-round cost metric: Qiskit `optimization_level=1`, seed 2026, "
         "`qubits_initially_zero=False`, basis cx/rz/sx/x, linear coupling for c3x_linear and reverse6_nn.",
         "* **after** = cheapest candidate (CX, then depth) that `decide_equivalence` PROVED equivalent to the "
         "assistant's own circuit. Unproven candidates are never used.",
         "* The optimizer preserves what the circuit does; a circuit that FAILed the hard round is still wrong after "
         "optimization.", "",
         f"Proven result for **{len(ok)}/{len(rows)}** circuits; CX before {sum(r['before_opt1']['cx'] for r in ok)} "
         f"-> after {sum(r['after']['cx'] for r in ok)} on those.", "",
         "| assistant | task | mode | hard verdict | CX before (opt1) | CX after | saved | depth after | proof | winning config |",
         "|---|---|---|---|---:|---:|---:|---:|---|---|"]
    for r in rows:
        if r.get("error"):
            L.append(f"| {r['assistant']} | {r['task']} | {r['mode']} | {r['hard_verdict']} | - | - | - | - | build error | |")
            continue
        b = r.get("after")
        if not b:
            L.append(f"| {r['assistant']} | {r['task']} | {r['mode']} | {r['hard_verdict']} | {r['before_opt1']['cx']} "
                     f"| - | - | - | **not proven** (nothing returned) | |")
            continue
        c = b["config"]
        cfg = f"opt{c['optimization_level']} seed {c['seed']}" + (" zero-init" if c.get("qubits_initially_zero") else "") \
            + (f" +{c['variant']}" if c.get("variant") else "") + (" +extra round" if c.get("extra") else "")
        L.append(f"| {r['assistant']} | {r['task']} | {r['mode']} | {r['hard_verdict']} | {r['before_opt1']['cx']} | "
                 f"{b['cx']} | {r['cx_saved_vs_opt1']} | {b['depth']} | {b['method']} | {cfg} |")
    L += ["", "## Totals per assistant (circuits with a proven result)", "",
          "| assistant | circuits | CX before | CX after | saved |", "|---|---:|---:|---:|---:|"]
    for a in ASSISTANTS:
        rs = [r for r in ok if r["assistant"] == a]
        bef, aft = sum(r["before_opt1"]["cx"] for r in rs), sum(r["after"]["cx"] for r in rs)
        L.append(f"| {a} | {len(rs)} | {bef} | {aft} | {bef - aft} ({(bef - aft) / bef * 100 if bef else 0:.0f}%) |")
    L += ["", "## Totals per task", "", "| task | circuits | CX before | CX after | saved |", "|---|---:|---:|---:|---:|"]
    for t in dict.fromkeys(r["task"] for r in rows):
        rs = [r for r in ok if r["task"] == t]
        bef, aft = sum(r["before_opt1"]["cx"] for r in rs), sum(r["after"]["cx"] for r in rs)
        L.append(f"| {t} | {len(rs)} | {bef} | {aft} | {bef - aft} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
