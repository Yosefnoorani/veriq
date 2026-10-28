"""Veriq Bench: score model-written circuits and bug detectors against a versioned benchmark.

Bench layout (see benchmark/veriqbench/SCHEMA.md): tasks/<task>.json, references.py, best_known.json,
corpus/mutants.jsonl, corpus/correct.jsonl.

* `run_bench(model_outputs)`: for every submission x task, correctness via proof (unitary equality or exact
  state equality), constraint compliance (gate set, coupling map, no black boxes), cost (CX/depth under the
  task's fixed cost model), and the gap to the best PROVEN-optimized CX (`veriq optimize`).
* `corpus_eval(detector)`: run a bug detector (built-in name or `module:function`) on every corpus mutant and
  on the correct circuits; recall on genuinely wrong mutants, false-positive rate on equivalent ones.
* `render_leaderboard(run, evals)`: static Markdown + self-contained HTML.

Submission code is executed in-process (like `veriq check`); run untrusted submissions in a container.
"""
from __future__ import annotations

import html
import importlib
import importlib.util
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import __version__

BUILTIN_DETECTORS = ("histogram", "zero-state", "all-basis", "proof", "veriq")
DETECTOR_HELP = {
    "histogram": "Aer sampling from |0...0> (4096 shots, two-sample test vs the reference)",
    "zero-state": "exact output distribution from |0...0> (infinite shots)",
    "all-basis": "exact output distribution from EVERY computational-basis input (truth table)",
    "proof": "formal equivalence proof (QCEC / operator; exact state equality in state mode)",
    "veriq": "the full `veriq check` suite against the reference (semantic checks, no constraints)",
}


# ----------------------------------------------------------------------------- bench data

def find_bench(path: str | Path | None = None) -> Path:
    cands = [Path(path)] if path else []
    if os.environ.get("VERIQ_BENCH"):
        cands.append(Path(os.environ["VERIQ_BENCH"]))
    cands += [Path(__file__).resolve().parents[2] / "benchmark" / "veriqbench" / "v0.1",
              Path.cwd() / "benchmark" / "veriqbench" / "v0.1"]
    for c in cands:
        if (c / "tasks").is_dir():
            return c.resolve()
    raise FileNotFoundError("Veriq Bench data not found; pass --bench DIR (the directory containing tasks/)")


def load_tasks(bench: Path) -> dict[str, dict]:
    tasks = [json.loads(p.read_text()) for p in sorted((bench / "tasks").glob("*.json"))]
    return {t["id"]: t for t in sorted(tasks, key=lambda t: t["order"])}


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_references(bench: Path, tasks: dict[str, dict]) -> dict[str, Any]:
    mod = _import(f"_veriqbench_refs_{abs(hash(str(bench)))}", bench / "references.py")
    return {t: getattr(mod, spec["reference"]["function"])() for t, spec in tasks.items()}


def load_corpus(bench: Path, negatives: bool = True) -> list[dict]:
    rows = [json.loads(l) for l in (bench / "corpus" / "mutants.jsonl").read_text().splitlines() if l.strip()]
    if negatives and (bench / "corpus" / "correct.jsonl").exists():
        for l in (bench / "corpus" / "correct.jsonl").read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                r.setdefault("mutation_class", "none")
                r.setdefault("study_class", "correct_original")
                rows.append(r)
    return rows


def qasm_circuit(text: str):
    from qiskit import qasm2
    return qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)


# ----------------------------------------------------------------------------- cost model

def cost(qc, cost_model: dict) -> dict:
    from qiskit import transpile
    n = qc.num_qubits
    kw = dict(basis_gates=cost_model["basis_gates"], optimization_level=cost_model["optimization_level"],
              seed_transpiler=cost_model["seed_transpiler"], qubits_initially_zero=cost_model["qubits_initially_zero"])
    if cost_model.get("coupling_map") == "linear":
        kw["coupling_map"] = [[i, i + 1] for i in range(n - 1)] + [[i + 1, i] for i in range(n - 1)]
    tq = transpile(qc, **kw)
    return {"cx": int(tq.count_ops().get("cx", 0)), "depth": tq.depth(), "size": tq.size()}


# ----------------------------------------------------------------------------- submissions

def discover_submissions(model_outputs: str | Path, tasks: dict[str, dict]) -> dict[str, dict[str, Path]]:
    """DIR/<model>.py (one file defining every task function) or DIR/<model>/<task>.py|.qasm
    (or DIR/<model>/solution.py defining every task function)."""
    root = Path(model_outputs)
    if not root.is_dir():
        raise FileNotFoundError(f"--model-outputs {root} is not a directory")
    subs: dict[str, dict[str, Path]] = {}
    for p in sorted(root.iterdir()):
        if p.is_file() and p.suffix == ".py" and not p.name.startswith("_"):
            subs[p.stem] = {t: p for t in tasks}
        elif p.is_dir() and not p.name.startswith((".", "_")):
            files: dict[str, Path] = {}
            sol = p / "solution.py"
            for t in tasks:
                for ext in (".py", ".qasm"):
                    if (p / f"{t}{ext}").exists():
                        files[t] = p / f"{t}{ext}"
                        break
                else:
                    if sol.exists():
                        files[t] = sol
            if files:
                subs[p.name] = files
    return subs


def _status(rep, *names) -> str | None:
    for c in rep.checks:
        if c.name in names or any(c.name.startswith(n) for n in names):
            return c.status.value
    return None


def score_submission(path: Path, task: dict, bench: Path, timeout: float = 30.0) -> tuple[dict, Any]:
    from .loader import load_circuit
    from .runner import run_checks
    fn = None
    if path.suffix == ".py":  # per-task files may use build()/circuit or the task's own function name
        fn = task["function"] if (path.stem != task["id"] or f"def {task['function']}(" in path.read_text()) else None
    row: dict[str, Any] = {"file": str(path)}
    try:
        qc = load_circuit(path, fn)
    except Exception as exc:  # noqa: BLE001 - anything a submission raises is a build error
        row.update(status="BUILD_ERROR", correct=False, compliant=False, error=f"{type(exc).__name__}: {exc}"[:300])
        return row, None
    c = task["constraints"]
    rep = run_checks(qc, reference=str(bench / task["reference"]["file"]),
                     reference_function=task["reference"]["function"], mode=task["mode"], timeout=timeout,
                     allowed_gates=c.get("allowed_gates"), coupling=c.get("coupling"),
                     no_black_boxes=c.get("no_black_boxes", False))
    proof = _status(rep, "Reference equivalence", "State equivalence")
    cons = {"gate_set": _status(rep, "Gate-set constraint"), "coupling": _status(rep, "Coupling-map constraint"),
            "no_black_boxes": _status(rep, "No black boxes"),
            "qubits": "PASS" if qc.num_qubits == task["qubits"] else "FAIL",
            "no_measurements": "PASS" if not any(i.operation.name in ("measure", "reset") for i in qc.data)
            and qc.num_clbits == 0 else "FAIL"}
    compliant = all(v in (None, "PASS") for v in cons.values())
    status = rep.verdict.value
    if status == "PASS" and not compliant:
        status = "FAIL"
    row.update(status=status, correct=proof == "PASS", proof=proof, constraints=cons, compliant=compliant,
               failing_checks={ch.name: ch.summary for ch in rep.checks if ch.status.value == "FAIL"},
               metrics={"qubits": qc.num_qubits, "cx_as_written": int(qc.count_ops().get("cx", 0)),
                        "depth_as_written": qc.depth(), "size_as_written": qc.size()})
    try:
        row["cost"] = cost(qc, task["cost_model"])
    except Exception as exc:  # noqa: BLE001
        row["cost"] = None
        row["cost_error"] = f"{type(exc).__name__}: {exc}"[:200]
    return row, qc


def run_bench(model_outputs: str | Path, bench: str | Path | None = None, optimize: bool = True,
              budget: float = 60.0, seeds: int = 4, timeout: float = 30.0, only_tasks: list[str] | None = None,
              only_models: list[str] | None = None, progress: Callable[[str], None] | None = None) -> dict:
    bench = find_bench(bench)
    tasks = load_tasks(bench)
    if only_tasks:
        tasks = {t: v for t, v in tasks.items() if t in only_tasks}
    best_known = json.loads((bench / "best_known.json").read_text())["tasks"]
    subs = discover_submissions(model_outputs, tasks)
    if only_models:
        subs = {m: v for m, v in subs.items() if m in only_models}
    prov_file = Path(model_outputs) / "provenance.json"
    provenance = json.loads(prov_file.read_text()) if prov_file.exists() else None
    t_all = time.perf_counter()
    rows = []
    for model, files in subs.items():
        for tid, task in tasks.items():
            t0 = time.perf_counter()
            if tid not in files:
                rows.append({"model": model, "task": tid, "status": "MISSING", "correct": False, "compliant": False})
                continue
            row, qc = score_submission(files[tid], task, bench, timeout)
            row = {"model": model, "task": tid, **row}
            if optimize and qc is not None and row["correct"]:
                from .optimize import optimize_circuit
                r = optimize_circuit(qc, mode=task["mode"], coupling=task["cost_model"].get("coupling_map"),
                                     seeds=seeds, timeout=timeout, budget=budget)
                b = r.get("best")
                row["optimized"] = ({"cx": b["cx"], "depth": b["depth"], "status": b["status"], "method": b["method"]}
                                    if b else None)
            row["seconds"] = round(time.perf_counter() - t0, 2)
            rows.append(row)
            if progress:
                c = row.get("cost") or {}
                progress(f"{row['status']:12s} {model:14s} {tid:12s} cx={c.get('cx', '-')}"
                         + (f" -> proven-optimized {row['optimized']['cx']}" if row.get("optimized") else ""))
    # best known: bundled table, improved by anything proven in this run
    best = {t: dict(v, source="best_known.json") for t, v in best_known.items() if t in tasks}
    for r in rows:
        o = r.get("optimized")
        if o and (r["task"] not in best or o["cx"] < best[r["task"]]["cx"]):
            best[r["task"]] = {"cx": o["cx"], "depth": o["depth"], "from": f"run/{r['model']}", "source": "this run"}
    for r in rows:
        b = best.get(r["task"])
        if b and r.get("status") == "PASS" and r.get("cost"):
            g = {"best_cx": b["cx"], "cx_gap": r["cost"]["cx"] - b["cx"],
                 "cx_ratio": round(r["cost"]["cx"] / b["cx"], 3) if b["cx"] else None}
            if r.get("optimized"):
                g["optimized_cx_gap"] = r["optimized"]["cx"] - b["cx"]
            r["gap"] = g
    return {"schema": "veriq.bench_run/1", "bench_version": json.loads((bench / "tasks" / f"{next(iter(tasks))}.json")
                                                                        .read_text())["version"] if tasks else None,
            "bench": str(bench), "model_outputs": str(model_outputs), "generated": _now(),
            "versions": _versions(), "settings": {"optimize": optimize, "budget_s": budget, "seeds": seeds,
                                                  "timeout_s": timeout},
            "provenance": provenance, "tasks": list(tasks), "best_known": best,
            "summary": summarize(rows, list(subs), list(tasks)), "results": rows,
            "seconds": round(time.perf_counter() - t_all, 1)}


def summarize(rows: list[dict], models: list[str], tasks: list[str]) -> dict:
    out = {}
    for m in models:
        rs = [r for r in rows if r["model"] == m]
        ok = [r for r in rs if r["status"] == "PASS"]
        ratios = [r["gap"]["cx_ratio"] for r in ok if r.get("gap") and r["gap"].get("cx_ratio")]
        out[m] = {"tasks": len(tasks), "pass": len(ok), "correct": sum(r["correct"] for r in rs),
                  "compliant": sum(bool(r.get("compliant")) for r in rs),
                  "cx_total_pass": sum(r["cost"]["cx"] for r in ok if r.get("cost")),
                  "best_cx_total_pass": sum(r["gap"]["best_cx"] for r in ok if r.get("gap")),
                  "cx_ratio_geomean": round(math.exp(sum(map(math.log, ratios)) / len(ratios)), 3) if ratios else None}
    return out


# ----------------------------------------------------------------------------- detectors

def _probs_cols(qc) -> np.ndarray:
    from qiskit.quantum_info import Operator
    return np.abs(Operator(qc).data) ** 2


def _zero_probs(qc) -> np.ndarray:
    from qiskit.quantum_info import Statevector
    return np.abs(Statevector(qc).data) ** 2


def det_histogram(cand, ref, mode, shots: int = 4096, seed: int = 7, **_):
    from . import checks
    s = checks.statistical_test(cand, None, ref, shots=shots, seed=seed).status.value
    return {"FAIL": True, "PASS": False}.get(s)


def det_zero_state(cand, ref, mode, **_):
    return bool(0.5 * np.abs(_zero_probs(cand) - _zero_probs(ref)).sum() > 1e-9)


def det_all_basis(cand, ref, mode, **_):
    if mode == "state":
        return det_zero_state(cand, ref, mode)
    return bool((0.5 * np.abs(_probs_cols(cand) - _probs_cols(ref)).sum(axis=0)).max() > 1e-9)


def det_proof(cand, ref, mode, timeout: float = 30.0, **_):
    from . import checks
    if mode == "state":
        return {"FAIL": True, "PASS": False}.get(checks.state_equivalence(cand, ref).status.value)
    v, _ = checks.prove_equivalence(cand, ref, timeout=timeout)
    return {"not_equivalent": True, "equivalent": False}.get(v)


def det_veriq(cand, ref, mode, timeout: float = 30.0, **_):
    from .runner import run_checks
    return {"FAIL": True, "PASS": False}.get(run_checks(cand, reference=ref, mode=mode, timeout=timeout).verdict.value)


DETECTORS: dict[str, Callable] = {"histogram": det_histogram, "zero-state": det_zero_state,
                                  "all-basis": det_all_basis, "proof": det_proof, "veriq": det_veriq}


def load_detector(spec: str) -> tuple[str, Callable]:
    """Built-in name, or `module:function` / `path/to/file.py:function`.
    A detector is `fn(candidate, reference, mode, **kw) -> True (bug) | False (no bug) | None (undecided)`."""
    if spec in DETECTORS:
        return spec, DETECTORS[spec]
    if ":" not in spec:
        raise ValueError(f"unknown detector '{spec}': use one of {', '.join(DETECTORS)} or module:function")
    mod_name, fn = spec.rsplit(":", 1)
    if mod_name.endswith(".py"):
        mod = _import(f"_veriqbench_det_{abs(hash(mod_name))}", Path(mod_name))
    else:
        sys.path.insert(0, os.getcwd())
        mod = importlib.import_module(mod_name)
    return spec, getattr(mod, fn)


def corpus_eval(detector: str, bench: str | Path | None = None, negatives: bool = True, limit: int | None = None,
                only_tasks: list[str] | None = None, shots: int = 4096, seed: int = 7, timeout: float = 30.0,
                progress: Callable[[str], None] | None = None) -> dict:
    bench = find_bench(bench)
    tasks = load_tasks(bench)
    refs = load_references(bench, tasks)
    name, fn = load_detector(detector)
    rows = load_corpus(bench, negatives)
    if only_tasks:
        rows = [r for r in rows if r["task"] in only_tasks]
    if limit:
        pos = [r for r in rows if not r["equivalent"]]
        neg = [r for r in rows if r["equivalent"]]
        step_p, step_n = max(1, len(pos) // limit), max(1, len(neg) // max(1, limit // 4))
        rows = pos[::step_p][:limit] + neg[::step_n][:max(1, limit // 4)]
    t_all = time.perf_counter()
    out = []
    for i, r in enumerate(rows):
        cand = qasm_circuit(r["qasm"])
        try:
            flag = fn(cand, refs[r["task"]], r["mode"], shots=shots, seed=seed, timeout=timeout)
            err = None
        except Exception as exc:  # noqa: BLE001
            flag, err = None, f"{type(exc).__name__}: {exc}"[:200]
        flag = None if flag is None else bool(flag)
        o = {"id": r["id"], "task": r["task"], "mutation_class": r["mutation_class"], "study_class": r["study_class"],
             "equivalent": r["equivalent"], "flagged": flag}
        if err:
            o["error"] = err
        rec = r.get("detected_by", {}).get({"histogram": "histogram", "zero-state": "zero_state_exact",
                                             "all-basis": "all_basis", "proof": "proof"}.get(name, ""))
        if rec is not None:
            o["recorded"] = rec
        out.append(o)
        if progress and (i + 1) % 100 == 0:
            progress(f"  {i + 1}/{len(rows)}")
    return {"schema": "veriq.corpus_eval/1", "detector": name, "description": DETECTOR_HELP.get(name, "user detector"),
            "bench": str(bench), "generated": _now(), "versions": _versions(),
            "settings": {"shots": shots, "seed": seed, "timeout_s": timeout, "negatives": negatives, "limit": limit},
            "summary": corpus_summary(out), "seconds": round(time.perf_counter() - t_all, 1), "results": out}


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def corpus_summary(rows: list[dict]) -> dict:
    pos = [r for r in rows if not r["equivalent"]]
    neg = [r for r in rows if r["equivalent"]]
    tp = sum(r["flagged"] is True for r in pos)
    fp = sum(r["flagged"] is True for r in neg)

    def group(key):
        g: dict[str, dict] = {}
        for r in pos:
            s = g.setdefault(r[key], {"n": 0, "detected": 0, "undecided": 0})
            s["n"] += 1
            s["detected"] += r["flagged"] is True
            s["undecided"] += r["flagged"] is None
        for s in g.values():
            s["recall"] = _rate(s["detected"], s["n"])
        return g

    rec = [r for r in rows if "recorded" in r]
    return {"wrong_mutants": len(pos), "detected": tp, "missed": sum(r["flagged"] is False for r in pos),
            "undecided_on_wrong": sum(r["flagged"] is None for r in pos), "recall": _rate(tp, len(pos)),
            "negatives": len(neg), "false_positives": fp, "undecided_on_negatives": sum(r["flagged"] is None for r in neg),
            "false_positive_rate": _rate(fp, len(neg)),
            "precision": _rate(tp, tp + fp),
            "errors": sum("error" in r for r in rows),
            "agreement_with_recorded_labels": _rate(sum(r["flagged"] == r["recorded"] for r in rec), len(rec)) if rec else None,
            "by_study_class": group("study_class"), "by_mutation_class": group("mutation_class"), "by_task": group("task")}


# ----------------------------------------------------------------------------- leaderboard

def _versions() -> dict:
    v = {"veriq": __version__, "python": sys.version.split()[0]}
    for mod in ("qiskit", "mqt.qcec", "qiskit_aer"):
        try:
            m = importlib.import_module(mod)
            v[mod] = getattr(m, "__version__", "?")
        except Exception:  # noqa: BLE001
            pass
    return v


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def leaderboard_tables(run: dict, evals: list[dict]) -> dict:
    """Plain data for both renderers: list of (title, header, rows, note)."""
    tasks, res = run["tasks"], run["results"]
    by = {(r["model"], r["task"]): r for r in res}
    models = list(run["summary"])
    order = sorted(models, key=lambda m: (-run["summary"][m]["pass"], run["summary"][m]["cx_ratio_geomean"] or 1e9))
    S = run["summary"]
    T = []
    T.append(("Overall", ["rank", "model", "pass (correct + compliant)", "correct (proof)", "compliant",
                          "CX total (passing tasks)", "best proven CX (same tasks)", "CX / best (geo-mean)"],
              [[str(i + 1), m, f"{S[m]['pass']}/{S[m]['tasks']}", f"{S[m]['correct']}/{S[m]['tasks']}",
                f"{S[m]['compliant']}/{S[m]['tasks']}", str(S[m]["cx_total_pass"]), str(S[m]["best_cx_total_pass"]),
                f"{S[m]['cx_ratio_geomean']:.2f}x" if S[m]["cx_ratio_geomean"] else "-"] for i, m in enumerate(order)],
              "Ranked by tasks passed, then CX geo-mean ratio to the best proven-optimized circuit (lower is better)."))
    T.append(("Correctness per task", ["model"] + tasks,
              [[m] + [by.get((m, t), {}).get("status", "-") for t in tasks] for m in order],
              "PASS = proven correct (unitary or exact state) AND every task constraint satisfied."))
    rows = []
    for m in order:
        cells = [m]
        for t in tasks:
            r = by.get((m, t), {})
            c, g = r.get("cost"), r.get("gap")
            cells.append(f"{c['cx']} (+{g['cx_gap']})" if c and g else (str(c["cx"]) if c else "-"))
        rows.append(cells)
    best = run["best_known"]
    rows.append(["**best proven**"] + [str(best[t]["cx"]) if t in best else "-" for t in tasks])
    T.append(("CX cost and gap to the best proven-optimized circuit", ["model"] + tasks, rows,
              "Cost = CX after Qiskit opt-level 1 (basis cx/rz/sx/x, seed 2026, linear chain where required). "
              "(+gap) = CX above the best circuit PROVEN equivalent to a correct submission (`veriq optimize`); "
              "the best is an upper bound on the optimum, not the optimum."))
    rows = []
    for m in order:
        cells = [m]
        for t in tasks:
            o = by.get((m, t), {}).get("optimized")
            cells.append(str(o["cx"]) if o else "-")
        opt = [by.get((m, t), {}).get("optimized") for t in tasks]
        cells.append(str(sum(o["cx"] for o in opt)) if all(opt) else "-")
        rows.append(cells)
    T.append(("Proven-optimized CX of each submission", ["model"] + tasks + ["total"], rows,
              "Cheapest compilation of that submission that the optimizer PROVED equivalent to it."))
    if evals:
        hdr = ["detector", "what it does", "recall (wrong mutants)", "false positives", "undecided"]
        classes = []
        for e in evals:
            for c in e["summary"]["by_study_class"]:
                if c not in classes:
                    classes.append(c)
        hdr += classes
        rows = []
        for e in evals:
            s = e["summary"]
            rows.append([e["detector"], e["description"], f"{s['detected']}/{s['wrong_mutants']} = {100 * (s['recall'] or 0):.1f}%",
                         f"{s['false_positives']}/{s['negatives']}", str(s["undecided_on_wrong"])]
                        + [f"{s['by_study_class'][c]['detected']}/{s['by_study_class'][c]['n']}"
                           if c in s["by_study_class"] else "-" for c in classes])
        T.append(("Bug detection on the corpus", hdr, rows,
                  "Recall on genuinely wrong mutants; false positives on equivalent mutants + the correct originals. "
                  "Columns per study class (assigned in the hard round) show detected/total."))
    return {"models": order, "tables": T}


def _provenance_lines(run: dict) -> list[str]:
    p = run.get("provenance")
    if not p:
        return ["No provenance.json was supplied with these model outputs."]
    L = [f"Round `{p.get('round')}`; prompt date {p.get('prompt_date')}; {p.get('how', '')}."]
    for m, v in (p.get("models") or {}).items():
        L.append(f"{m}: {v.get('label')} via {v.get('interface')}; model version: {v.get('model_version')}; "
                 f"date {v.get('date')}; attempts {v.get('attempts')}")
    return L


def render_leaderboard_md(run: dict, evals: list[dict]) -> str:
    d = leaderboard_tables(run, evals)
    L = [f"# Veriq Bench v{run.get('bench_version')} leaderboard", "",
         f"Generated {run['generated']} by `veriq bench leaderboard` from a `veriq bench run` of "
         f"`{Path(run['model_outputs']).name}` ({len(run['tasks'])} tasks). Versions: "
         + ", ".join(f"{k} {v}" for k, v in run["versions"].items()) + ".", ""]
    for title, hdr, rows, note in d["tables"]:
        L += [f"## {title}", "", "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        L += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows]
        L += ["", note, ""]
    L += ["## Provenance", ""] + [f"- {x}" for x in _provenance_lines(run)] + [""]
    return "\n".join(L)


def render_leaderboard_html(run: dict, evals: list[dict]) -> str:
    d = leaderboard_tables(run, evals)
    e = html.escape

    def cell(x: str) -> str:
        cls = {"PASS": "pass", "FAIL": "fail", "INCONCLUSIVE": "inc", "BUILD_ERROR": "fail", "MISSING": "fail"}.get(x, "")
        x2 = e(x).replace("**", "")
        return f'<td class="{cls}">{x2}</td>' if cls else f"<td>{x2}</td>"

    parts = [f"<h2>{e(t)}</h2><table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for h in hdr) + "</tr></thead><tbody>"
             + "".join("<tr>" + "".join(cell(c) for c in r) + "</tr>" for r in rows)
             + f"</tbody></table><p class=note>{e(note)}</p>" for t, hdr, rows, note in d["tables"]]
    prov = "".join(f"<li>{e(x)}</li>" for x in _provenance_lines(run))
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Veriq Bench v{e(str(run.get('bench_version')))} leaderboard</title>
<style>
body{{font:15px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#1d2330}}
h1{{font-size:1.6rem}} h2{{font-size:1.15rem;margin-top:2rem}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}} th,td{{border:1px solid #d5dae3;padding:.35rem .5rem;text-align:left}}
th{{background:#f1f4f9}} td.pass{{background:#e5f6ea;color:#14632d;font-weight:600}}
td.fail{{background:#fde8e8;color:#8f1d1d;font-weight:600}} td.inc{{background:#fff4d6}}
.note{{color:#556;font-size:.85rem}} .meta{{color:#556}}
</style></head><body>
<h1>Veriq Bench v{e(str(run.get('bench_version')))} leaderboard</h1>
<p class=meta>Generated {e(run['generated'])}. Versions: {e(', '.join(f'{k} {v}' for k, v in run['versions'].items()))}.
Correctness is decided by formal proof, not by sampling.</p>
{''.join(parts)}
<h2>Provenance</h2><ul>{prov}</ul>
</body></html>
"""
