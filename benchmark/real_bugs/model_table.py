"""Model table for the real-bugs study: test pass rate vs. Veriq-confirmed pass rate, per published generation run.

Reads raw/*.veriq.jsonl (every sample, passed or not) and results/manual_review.json (the verdict for every flagged
passing sample) and writes results/model_table.json, results/model_table.md and results/task_index.jsonl (one row per task). Only the published generations that
ship with the datasets are used; no model was re-run.

  tests pass          the dataset's own unit tests pass (QuanBench harness semantics)
  Veriq-confirmed     tests pass AND the circuit is proved equivalent to the canonical, or matches the spec after
                      manual review (diagonal phases before measurement and similar don't-cares accepted)
  wrong but passed    tests pass, but the circuit is wrong (strict: wrong from the tested input itself;
                      +superposed: also wrong gates that only fail on superposed inputs)
  unverified          tests pass, but no verdict (no circuit returned, Veriq undecided, excluded task, qubit-order
                      convention, ambiguous spec, suspicious but unconfirmed)
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = {"QuanBench44": ("GPT-4.1 (T=0.8)", "quanbench44_gpt-4.1_T0.8"),
        "QuanBench117": ("GPT-4o", "quanbench117_gpt-4o")}


def main() -> int:
    review = json.loads((HERE / "results" / "manual_review.json").read_text())
    verdict = {(r["dataset"], r["task_id"], r["sample"]): r["verdict"] for r in review}
    table, index = [], []
    for ds, (model, stem) in RUNS.items():
        rows = [json.loads(l) for l in (HERE / "raw" / f"{stem}.veriq.jsonl").open()]
        canon_ok = {r["task_id"]: r["tests_passed"]
                    for r in map(json.loads, (HERE / "raw" / f"{ds.lower()}_canonical.veriq.jsonl").open())}
        c = Counter()
        tasks = {r["task_id"] for r in rows}
        per_task: dict = {t: Counter() for t in sorted(tasks)}
        for r in rows:
            c["samples"] += 1
            pt = per_task[r["task_id"]]
            pt["samples"] += 1
            if not r["tests_passed"]:
                continue
            c["tests_pass"] += 1
            pt["tests_pass"] += 1
            v = "proved" if r["class"] == "unitary_equivalent" else verdict.get((ds, r["task_id"], r["sample"]), "no_circuit")
            pt[v] += 1
            if v in ("proved", "ok_dont_care"):
                c["confirmed"] += 1
            elif v == "wrong":
                c["wrong_strict"] += 1
            elif v == "wrong_on_superposed_inputs":
                c["wrong_superposed_only"] += 1
            else:
                c["unverified"] += 1
        for t, pt in per_task.items():
            index.append({"dataset": ds, "task_id": t, "model": model,
                          "canonical_passes_own_tests": canon_ok.get(t), **dict(sorted(pt.items()))})
        n = c["samples"]
        table.append({"dataset": ds, "model": model, "tasks": len(tasks), "samples": n,
                      "samples_per_task": round(n / len(tasks), 2),
                      "tests_pass": c["tests_pass"], "tests_pass_rate": round(c["tests_pass"] / n, 4),
                      "veriq_confirmed": c["confirmed"], "veriq_confirmed_rate": round(c["confirmed"] / n, 4),
                      "wrong_but_passed_strict": c["wrong_strict"],
                      "wrong_but_passed_incl_superposed": c["wrong_strict"] + c["wrong_superposed_only"],
                      "unverified_passed": c["unverified"]})
    with (HERE / "results" / "task_index.jsonl").open("w") as f:
        for row in index:
            f.write(json.dumps(row) + "\n")
    (HERE / "results" / "model_table.json").write_text(json.dumps(table, indent=1) + "\n")
    md = ["| dataset | model (published generations) | tasks | samples | tests pass | Veriq-confirmed | wrong but passed (strict / +superposed) | unverified |",
          "|---|---|---|---|---|---|---|---|"]
    for t in table:
        md.append(f"| {t['dataset']} | {t['model']} | {t['tasks']} | {t['samples']} | {t['tests_pass']} ({t['tests_pass_rate']:.1%}) "
                  f"| {t['veriq_confirmed']} ({t['veriq_confirmed_rate']:.1%}) | {t['wrong_but_passed_strict']} / "
                  f"{t['wrong_but_passed_incl_superposed']} | {t['unverified_passed']} |")
    (HERE / "results" / "model_table.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
