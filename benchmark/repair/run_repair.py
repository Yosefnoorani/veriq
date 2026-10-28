"""Repair-loop demo + localization accuracy on the hard-round mutation study.

Regenerates exactly the mutants of benchmark/hard (same operators, `random.Random(2026)`, same order; checked
against benchmark/hard/results/mutation.json), skips the ones that study proved equivalent, and for every
remaining single-gate mutant asks `veriq.repair_report.localize` where the bug is.

Localization hit (single-gate operators only):
* delete_gate at i  -> some region's gap range contains gap i (the place where the gate is missing);
* other operators at i (negate_angle, flip_cx, cp_to_crz, p_to_rz) -> some region contains gate i, or its
  gap range touches gap i or i+1 (just before / after the changed gate).
"pi_as_3.14" changes every angle at once; it is reported separately (no single location exists).

Then a repair-loop demo: `veriq.repair.repair_loop` with the offline `demo_fixer` on a deterministic sample
(up to --per-cell mutants per assistant x task x operator). The demo fixer knows this mutation vocabulary,
so its repair rate shows that the loop + report work end to end, NOT how well an LLM would fix real bugs.

    .venv/bin/python benchmark/repair/run_repair.py [--per-cell 3]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
HARD = ROOT / "benchmark" / "hard"

from veriq import checks  # noqa: E402
from veriq.loader import load_circuit  # noqa: E402
from veriq.repair import demo_fixer, repair_loop  # noqa: E402
from veriq.repair_report import localize  # noqa: E402

ASSISTANTS = ["chatgpt", "claude", "gemini", "perplexity"]
SINGLE = ("delete_gate", "negate_angle", "flip_cx", "cp_to_crz", "p_to_rz")


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def hit(op: str, i: int, regions: list[dict]) -> bool:
    for r in regions:
        if op == "delete_gate":
            if r["gap_start"] <= i <= r["gap_end"]:
                return True
        elif r["gate_start"] <= i <= r["gate_end"] or (r["gap_start"] <= i + 1 and i <= r["gap_end"]):
            return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cell", type=int, default=3)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--rerender", action="store_true", help="recompute summary + markdown from results.json")
    args = ap.parse_args(argv)
    if args.rerender:
        out = json.loads((HERE / "results.json").read_text())
        out["summary"] = summarize(out["mutants"], out["repair_demo"])
        (HERE / "results.json").write_text(json.dumps(out, indent=1, default=str))
        (HERE / "results.md").write_text(render_md(out))
        print(json.dumps({k: v for k, v in out["summary"].items() if not k.startswith("by_")}, indent=1))
        return 0
    R = _mod("veriq_hard_references", HARD / "references.py")
    H = _mod("veriq_hard_run", HARD / "run_hard.py")
    study = json.loads((HARD / "results" / "mutation.json").read_text())["mutants"]
    rng = random.Random(H.SEED)
    rows, k = [], 0
    t0 = time.perf_counter()
    for a in ASSISTANTS:
        for task, spec in R.TASKS.items():
            cand = load_circuit(HARD / "raw" / f"{a}.py", spec["fn"])
            ref = getattr(R, spec["fn"])()
            for op, desc, m in H.mutants(cand, rng):
                s = study[k]
                k += 1
                assert (s["assistant"], s["task"], s["mutation"]) == (a, task, desc), (s, a, task, desc)
                row = {"assistant": a, "task": task, "mode": spec["mode"], "operator": op, "mutation": desc,
                       "study_class": s["class"], "qubits": m.num_qubits, "gates": len(m.data)}
                if s["class"] == "equivalent_mutant":
                    row["skipped"] = "equivalent mutant"
                    rows.append(row)
                    continue
                if len(checks.unitary_part(m).data) != len(m.data):
                    row["skipped"] = "index mismatch after removing final measurements"
                    rows.append(row)
                    continue
                t = time.perf_counter()
                loc = localize(m, ref, spec["mode"])
                row["localize_seconds"] = round(time.perf_counter() - t, 3)
                row["available"] = loc.get("available", False)
                if not row["available"]:
                    row["reason"] = loc.get("reason")
                    rows.append(row)
                    continue
                regs = loc.get("regions", [])
                row["regions"] = [[r["gate_start"], r["gate_end"], r["gap_start"], r["gap_end"]] for r in regs]
                row["region_gates"] = sum(r["gap_end"] - r["gap_start"] + 1 for r in regs)
                row["min_support"] = loc.get("min_support_qubits")
                row["exact_fixes"] = len(loc.get("fixes", []))
                if op in SINGLE:
                    i = int(re.search(r"#(\d+)", desc).group(1))
                    row["index"] = i
                    row["hit"] = hit(op, i, regs)
                rows.append(row)
    print(f"localized {k} mutants in {time.perf_counter() - t0:.1f}s", flush=True)

    # repair-loop demo on a deterministic sample
    cells = defaultdict(list)
    for idx, r in enumerate(rows):
        if r.get("available"):
            cells[(r["assistant"], r["task"], r["operator"])].append(idx)
    sample = sorted(i for v in cells.values() for i in v[: args.per_cell])
    want = set(sample)
    rng = random.Random(H.SEED)
    k = 0
    demo = []
    for a in ASSISTANTS:
        for task, spec in R.TASKS.items():
            cand = load_circuit(HARD / "raw" / f"{a}.py", spec["fn"])
            ref = getattr(R, spec["fn"])()
            for op, desc, m in H.mutants(cand, rng):
                if k in want:
                    res = repair_loop(m, ref, demo_fixer, mode=spec["mode"], max_attempts=args.max_attempts,
                                      timeout=30.0)
                    demo.append({"assistant": a, "task": task, "operator": op, "mutation": desc,
                                 "verdict": res["verdict"], "stop_reason": res["stop_reason"],
                                 "attempts": res["attempts"], "fixes": [h.get("fix") for h in res["history"][1:]],
                                 "seconds": res["seconds"]})
                    print(f"  {a:10s} {task:12s} {desc[:40]:40s} -> {res['verdict']} ({res['stop_reason']}, "
                          f"{res['attempts']})", flush=True)
                k += 1
    out = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"),
           "seconds_total": round(time.perf_counter() - t0, 1), "summary": summarize(rows, demo),
           "mutants": rows, "repair_demo": demo}
    (HERE / "results.json").write_text(json.dumps(out, indent=1, default=str))
    (HERE / "results.md").write_text(render_md(out))
    print(json.dumps(out["summary"], indent=1))
    return 0


def summarize(rows, demo):
    s: dict = {"mutants": len(rows), "equivalent_skipped": sum(r.get("skipped") == "equivalent mutant" for r in rows),
               "not_localizable": {}, "by_operator": {}, "by_task": {}}
    for r in rows:
        if r.get("available") is False:
            key = re.sub(r"\d+", "N", r.get("reason") or "?")
            s["not_localizable"][key] = s["not_localizable"].get(key, 0) + 1
    for key, field in (("by_operator", "operator"), ("by_task", "task")):
        for r in rows:
            if not r.get("available"):
                continue
            d = s[key].setdefault(r[field], {"localized": 0, "hits": 0, "single_gate": 0, "region_gates_sum": 0,
                                             "with_exact_fix": 0})
            d["localized"] += 1
            d["region_gates_sum"] += r["region_gates"]
            d["with_exact_fix"] += r["exact_fixes"] > 0
            if "hit" in r:
                d["single_gate"] += 1
                d["hits"] += r["hit"]
    sg = [r for r in rows if "hit" in r]
    s["single_gate_localized"] = len(sg)
    s["localization_hits"] = sum(r["hit"] for r in sg)
    s["localization_accuracy"] = round(s["localization_hits"] / len(sg), 4) if sg else None
    s["miss_but_exact_fix_in_region"] = sum((not r["hit"]) and r["exact_fixes"] > 0 for r in sg)
    s["valid_location_rate"] = round((s["localization_hits"] + s["miss_but_exact_fix_in_region"]) / len(sg), 4) if sg else None
    s["mean_regions"] = round(sum(len(r["regions"]) for r in sg) / len(sg), 2) if sg else None
    s["mean_region_gates"] = round(sum(r["region_gates"] for r in sg) / len(sg), 2) if sg else None
    s["mean_circuit_gates"] = round(sum(r["gates"] for r in sg) / len(sg), 2) if sg else None
    s["repair_demo"] = {"cases": len(demo), "PASS": sum(d["verdict"] == "PASS" for d in demo),
                        "stop_reasons": {}}
    for d in demo:
        s["repair_demo"]["stop_reasons"][d["stop_reason"]] = s["repair_demo"]["stop_reasons"].get(d["stop_reason"], 0) + 1
    return s


def render_md(out) -> str:
    s = out["summary"]
    L = ["# Repair report: localization accuracy + repair-loop demo", "",
         f"Generated {out['generated']} by `benchmark/repair/run_repair.py` ({out['seconds_total']:g}s).", "",
         f"Mutants of the hard-round study: {s['mutants']} ({s['equivalent_skipped']} proved equivalent -> skipped).",
         ""]
    if s["not_localizable"]:
        L += ["Not localizable (outside the exact-localization limits):", ""]
        L += [f"* {v} - {k}" for k, v in s["not_localizable"].items()] + [""]
    L += [f"**Localization accuracy (single-gate mutants): {s['localization_hits']}/{s['single_gate_localized']} = "
          f"{100 * (s['localization_accuracy'] or 0):.1f}%**. On average {s['mean_regions']} region(s) covering "
          f"{s['mean_region_gates']} gaps in total are flagged, in circuits of {s['mean_circuit_gates']} gates.", "",
          f"Of the {s['single_gate_localized'] - s['localization_hits']} misses, {s['miss_but_exact_fix_in_region']} "
          "still come with an exact single-gate fix inside a flagged region (proven: applying it makes the circuit "
          "equal to the reference), i.e. the bug can equally be fixed there (e.g. a CX deleted in one SWAP of a swap "
          f"network). Counting those, the flagged region is a valid fix location in "
          f"**{100 * (s['valid_location_rate'] or 0):.1f}%** of single-gate mutants.", "",
          "A hit means the reported region contains the injected mutation (deletion: the gap where the gate is "
          "missing; other operators: the changed gate or the gap right next to it). Regions can be wide when the "
          "bug commutes with its neighbours: then every position in the region is an equally valid place to fix it.",
          "", "| operator | localized | single-gate hits | mean region (gaps) | with exact single-gate fix |",
          "|---|---:|---:|---:|---:|"]
    for op, d in s["by_operator"].items():
        hits = f"{d['hits']}/{d['single_gate']}" if d["single_gate"] else "n/a (multi-gate)"
        L.append(f"| {op} | {d['localized']} | {hits} | {d['region_gates_sum'] / d['localized']:.1f} | "
                 f"{d['with_exact_fix']} |")
    L += ["", "| task | localized | single-gate hits | mean region (gaps) | with exact fix |", "|---|---:|---:|---:|---:|"]
    for t, d in s["by_task"].items():
        L.append(f"| {t} | {d['localized']} | {d['hits']}/{d['single_gate']} | "
                 f"{d['region_gates_sum'] / d['localized']:.1f} | {d['with_exact_fix']} |")
    rd = s["repair_demo"]
    L += ["", "## Repair-loop demo (offline demo fixer)", "",
          f"{rd['PASS']}/{rd['cases']} sampled mutants repaired to a PASS verdict; stop reasons: {rd['stop_reasons']}.",
          "", "The demo fixer applies the report's exact single-gate fixes, else tries small edits (delete, negate, "
          "flip cx, crz->cp, rz->p, 3.14->pi) inside the localized region. It knows this mutation vocabulary, so "
          "this measures the plumbing (report -> fixer -> re-verify -> stop), not LLM repair skill.", "",
          "| assistant | task | mutation | verdict | stop | fixes |", "|---|---|---|---|---|---|"]
    for d in out["repair_demo"]:
        fx = "; ".join(f for f in d["fixes"] if f)[:90]
        L.append(f"| {d['assistant']} | {d['task']} | {d['mutation'][:50]} | {d['verdict']} | {d['stop_reason']} | {fx} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
