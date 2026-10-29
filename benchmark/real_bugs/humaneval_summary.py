"""Summarise raw/humaneval_mutants.jsonl -> results/humaneval_mutants_summary.json.

A mutant "survives" when the task's own check() still passes with the mutated circuit. A surviving mutant that Veriq
proves NOT equivalent to the canonical circuit (unitary or, for state-type tasks, prepared state) is a concrete
input on which the dataset's tests are too weak. Surviving mutants that are equivalent (e.g. negating rz(pi)) are
harmless and are reported separately.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    rows = [json.loads(l) for l in (HERE / "raw" / "humaneval_mutants.jsonl").open()]
    out = {}
    weak_tasks = defaultdict(list)
    for ds in ("normal", "hard"):
        rs = [r for r in rows if r["dataset"] == ds]
        c = Counter()
        for r in rs:
            can = r["canonical"]
            if "skipped" in can:
                c["skipped_skip_ci"] += 1
                continue
            c["tasks_run"] += 1
            if not can.get("passed"):
                c["canonical_fails"] += 1
                continue
            if not can.get("returns_circuit"):
                c["no_circuit_returned"] += 1
                continue
            muts = [m for m in r.get("mutants", []) if m.get("applied", 1)]
            if not muts:
                c["circuit_but_no_applicable_mutant"] += 1
                continue
            c["tasks_with_mutants"] += 1
            killed_all = True
            for m in muts:
                c["mutants"] += 1
                if not m["passed"]:
                    c["mutants_killed_by_tests"] += 1
                    continue
                killed_all = False
                c["mutants_survived"] += 1
                if m.get("unitary") is True or (m.get("unitary") is None and m.get("state") is True):
                    c["survived_equivalent"] += 1
                elif m.get("unitary") is False and m.get("state") is True:
                    c["survived_same_state_diff_unitary"] += 1
                    weak_tasks[(ds, r["task_id"])].append({"mutation": m["description"], "kind": "same |0> state, different unitary",
                                                           "state_fidelity": m.get("state_fidelity")})
                elif m.get("unitary") is False or m.get("state") is False:
                    c["survived_not_equivalent"] += 1
                    weak_tasks[(ds, r["task_id"])].append({"mutation": m["description"], "kind": "different output state",
                                                           "state_fidelity": m.get("state_fidelity")})
                else:
                    c["survived_undecided"] += 1
            c["tasks_all_mutants_killed"] += killed_all
        strong = {k for k in weak_tasks if k[0] == ds and any(x["kind"] == "different output state" for x in weak_tasks[k])}
        c["tasks_with_surviving_state_changing_mutant"] = len(strong)
        c["tasks_with_any_surviving_non_equivalent_mutant"] = len([k for k in weak_tasks if k[0] == ds])
        out[ds] = dict(sorted(c.items()))
    out["weak_tasks"] = [{"dataset": k[0], "task_id": k[1], "survivors": v} for k, v in sorted(weak_tasks.items())]
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "humaneval_mutants_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "weak_tasks"}, indent=1))
    update_readme(out, total_tasks={ds: len([r for r in rows if r["dataset"] == ds]) for ds in ("normal", "hard")})
    return 0


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def render_table(out: dict, total_tasks: dict) -> str:
    """Markdown table for benchmark/real_bugs/README.md, built only from the summary counts."""
    rows = [("Tasks in the run (of 151 per split)", lambda d, ds: f"{total_tasks[ds]}"),
            ("Canonical returns a circuit and gets mutants", lambda d, ds: f"{d.get('tasks_with_mutants', 0)}"),
            ("Mutants made", lambda d, ds: f"{d.get('mutants', 0)}"),
            ("Killed by the dataset's own tests", lambda d, ds: f"{d.get('mutants_killed_by_tests', 0)} ({_pct(d.get('mutants_killed_by_tests', 0), d.get('mutants', 0))})"),
            ("**Survived the tests**", lambda d, ds: f"**{d.get('mutants_survived', 0)}** ({_pct(d.get('mutants_survived', 0), d.get('mutants', 0))})"),
            ("of which Veriq: equivalent (harmless)", lambda d, ds: f"{d.get('survived_equivalent', 0)}"),
            ("of which Veriq: **different output state** (wrong)", lambda d, ds: f"**{d.get('survived_not_equivalent', 0)}**"),
            ("of which Veriq: same \\|0…0⟩ state, different unitary", lambda d, ds: f"{d.get('survived_same_state_diff_unitary', 0)}"),
            ("of which undecided (>12 qubits, parameterised, non-unitary)", lambda d, ds: f"{d.get('survived_undecided', 0)}"),
            ("Tasks with a surviving state-changing mutant", lambda d, ds: f"{d.get('tasks_with_surviving_state_changing_mutant', 0)} of {d.get('tasks_with_mutants', 0)}"),
            ("Tasks with any surviving non-equivalent mutant", lambda d, ds: f"{d.get('tasks_with_any_surviving_non_equivalent_mutant', 0)} of {d.get('tasks_with_mutants', 0)}")]
    lines = ["| | normal | hard |", "|---|---|---|"]
    for label, f in rows:
        lines.append(f"| {label} | {f(out['normal'], 'normal')} | {f(out['hard'], 'hard')} |")
    done = all(total_tasks[ds] >= 151 for ds in ("normal", "hard"))
    if not done:
        lines.append("")
        lines.append(f"*Partial run: {total_tasks['normal']} of 151 normal and {total_tasks['hard']} of 151 hard tasks so far.*")
    return "\n".join(lines)


def update_readme(out: dict, total_tasks: dict) -> None:
    readme = HERE / "README.md"
    if not readme.exists():
        return
    text = readme.read_text()
    start, end = "<!-- HUMANEVAL_TABLE -->", "<!-- /HUMANEVAL_TABLE -->"
    if start not in text or end not in text:
        return
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    readme.write_text(head + start + "\n" + render_table(out, total_tasks) + "\n" + end + tail)


if __name__ == "__main__":
    raise SystemExit(main())
