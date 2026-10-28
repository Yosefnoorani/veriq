"""Build Veriq Bench v0.1 (benchmark/veriqbench/v0.1/) from the hard round, deterministically.

Inputs (read only, never modified):
  benchmark/hard/prompt.md, references.py, raw/<assistant>.py, results/results.json, results/mutation.json
  benchmark/optimize/results.json   (proven-optimized CX of the 28 circuits -> best-known table)

Outputs (v0.1/):
  prompt.md, references.py                      verbatim copies
  tasks/<task>.json                             task spec: prompt line, reference, constraints, cost model
  corpus/mutants.jsonl                          one JSON object per mutant (1036), incl. the mutant as OpenQASM 2
  corpus/correct.jsonl                          the 28 original (correct) circuits, as negatives for detectors
  submissions/hard-round-2026-10-27/            the 4 assistants' raw files (copies) + provenance.json
  best_known.json                               best proven CX per task
  MANIFEST.json                                 sha256 of every file

The mutants are regenerated with the hard round's own generator (`run_hard.mutants`, random.Random(2026), same
order); each is checked against the description recorded in mutation.json, and its labels are taken from
mutation.json (they are the recorded hard-round judgements, not recomputed here). Each exported QASM is
checked to round-trip to the same unitary.

    .venv/bin/python benchmark/veriqbench/build_v0_1.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import re
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARD = ROOT / "benchmark" / "hard"
OUT = HERE / "v0.1"
sys.path.insert(0, str(ROOT / "src"))

from qiskit import qasm2  # noqa: E402
from qiskit.quantum_info import Operator  # noqa: E402

from veriq.loader import load_circuit  # noqa: E402

VERSION = "0.1"
ASSISTANTS = ["chatgpt", "claude", "gemini", "perplexity"]
ROUND = "hard-round-2026-10-27"
TASK_PROMPT_INDEX = {"maj5": 1, "cmul7": 2, "qpe_t": 3, "c3x_linear": 4, "reverse6_nn": 5, "bv22": 6, "add3": 7}
LINEAR_TASKS = ("c3x_linear", "reverse6_nn")
TASK_TITLES = {
    "maj5": "5-input majority oracle", "cmul7": "controlled multiply-by-7 mod 15", "qpe_t": "QPE of the T gate",
    "c3x_linear": "C3X on a linear chain, restricted gate set", "reverse6_nn": "6-qubit reversal with nearest-neighbour CX",
    "bv22": "Bernstein-Vazirani, s = 22", "add3": "3-bit in-place adder mod 8",
}


def _mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def prompt_parts(text: str) -> tuple[str, dict[int, str], str]:
    body = text.split("```")[1].strip("\n")
    lines = body.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("1. "))
    preamble = "\n".join(lines[:first]).strip()
    items, tail = {}, []
    for l in lines[first:]:
        m = re.match(r"(\d)\. (.*)", l)
        if m:
            items[int(m.group(1))] = m.group(2)
        elif l.strip():
            tail.append(l.strip())
    return preamble, items, " ".join(tail)


def to_qasm(qc) -> str:
    """OpenQASM 2 with deterministic names (Qiskit suffixes custom gate names with id(); replace them)."""
    s = qasm2.dumps(qc)
    seen: dict[str, str] = {}
    for m in re.finditer(r"\b([A-Za-z]\w*?)_(\d{6,})\b", s):
        seen.setdefault(m.group(0), f"{m.group(1)}_v{len(seen) + 1}")
    for old, new in seen.items():
        s = re.sub(rf"\b{old}\b", new, s)
    return s


def from_qasm(s: str):
    return qasm2.loads(s, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)


def same_unitary(a, b) -> bool:
    return Operator(a).equiv(Operator(b), atol=1e-9)


def location(qc_items, desc: str, op: str):
    m = re.search(r"#(\d+)", desc)
    if op == "pi_as_3.14" or not m:
        return None
    i = int(m.group(1))
    g, qs = qc_items[i]
    return {"gate_index": i, "gate": g.name, "qubits": list(qs),
            "params": [float(p) for p in g.params if isinstance(p, (int, float))]}


def detected_by(r: dict) -> dict:
    zero = r["exact_tvd_from_zero"] > 1e-9
    allb = r["exact_max_tvd_all_basis_inputs"] > 1e-9 if r["mode"] == "unitary" else zero
    return {"histogram": r["aer_hist_from_zero"] == "FAIL", "zero_state_exact": zero,
            "all_basis": allb, "proof": r["proof"] == "FAIL"}


def main() -> int:
    R = _mod("veriq_hard_references", HARD / "references.py")
    H = _mod("veriq_hard_run", HARD / "run_hard.py")
    mut = json.loads((HARD / "results" / "mutation.json").read_text())
    hard = json.loads((HARD / "results" / "results.json").read_text())
    opt = json.loads((ROOT / "benchmark" / "optimize" / "results.json").read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("tasks", "corpus", f"submissions/{ROUND}"):
        (OUT / d).mkdir(parents=True, exist_ok=True)

    shutil.copy(HARD / "prompt.md", OUT / "prompt.md")
    shutil.copy(HARD / "references.py", OUT / "references.py")
    preamble, items, tail = prompt_parts((HARD / "prompt.md").read_text())

    # ---- tasks
    for order, (task, spec) in enumerate(R.TASKS.items(), 1):
        ref = getattr(R, spec["fn"])()
        linear = task in LINEAR_TASKS
        doc = {
            "id": task, "version": VERSION, "order": order, "title": TASK_TITLES[task],
            "function": spec["fn"], "qubits": spec["qubits"], "mode": spec["mode"],
            "prompt": {"shared_preamble": preamble, "task": f"{TASK_PROMPT_INDEX[task]}. {items[TASK_PROMPT_INDEX[task]]}",
                       "shared_suffix": tail, "full_prompt_file": "prompt.md"},
            "reference": {"file": "references.py", "function": spec["fn"],
                          "verified_against": R.verify_references()[task],
                          "qasm": to_qasm(ref) if task != "qpe_t" else None,
                          "note": "references may use library gates (they are trusted, not graded)"},
            "constraints": {"no_black_boxes": spec.get("no_black_boxes", False),
                            "allowed_gates": spec.get("allowed_gates"), "coupling": spec.get("coupling"),
                            "no_measurements": True, "no_extra_qubits": True},
            "correctness": ("unitary equality up to global phase, every input (formal proof)"
                            if spec["mode"] == "unitary" else
                            "prepared state from |0...0> equal up to global phase (exact statevector)"),
            "cost_model": {"basis_gates": H.BASIS, "optimization_level": 1, "seed_transpiler": H.SEED,
                           "qubits_initially_zero": spec["mode"] == "state",
                           "coupling_map": "linear" if linear else None, "metric": "cx count, then depth"},
        }
        (OUT / "tasks" / f"{task}.json").write_text(json.dumps(doc, indent=1) + "\n")

    # ---- submissions (copies) + provenance
    sub = OUT / "submissions" / ROUND
    prov = {"round": ROUND, "prompt_file": "../../prompt.md", "prompt_date": hard["prompt_date"],
            "how": "same prompt pasted once into a new chat of each web assistant; first answer kept verbatim; "
                   "no retries, no edits",
            "models": {}}
    for a in ASSISTANTS:
        shutil.copy(HARD / "raw" / f"{a}.py", sub / f"{a}.py")
        assert sha256(sub / f"{a}.py") == sha256(HARD / "raw" / f"{a}.py")
        prov["models"][a] = {"label": hard["assistants"][a], "interface": "public web chat",
                             "model_version": "unknown (not shown/recorded by the web UI at the time)",
                             "date": hard["prompt_date"], "attempts": 1,
                             "source_sha256": sha256(HARD / "raw" / f"{a}.py")}
    (sub / "provenance.json").write_text(json.dumps(prov, indent=1) + "\n")

    # ---- best known
    best = {}
    for r in opt["rows"]:
        if r.get("after") and r.get("hard_verdict") == "PASS":
            t = r["task"]
            if t not in best or (r["after"]["cx"], r["after"]["depth"]) < (best[t]["cx"], best[t]["depth"]):
                best[t] = {"cx": r["after"]["cx"], "depth": r["after"]["depth"], "from": f"{ROUND}/{r['assistant']}",
                           "method": r["after"]["method"], "status": r["after"]["status"],
                           "coupling": r.get("coupling")}
    (OUT / "best_known.json").write_text(json.dumps(
        {"version": VERSION, "source": "benchmark/optimize/results.json (generated " + opt["generated"] + ")",
         "definition": "lowest CX (then depth) of a circuit PROVEN equivalent to a verified-correct submission, "
                       "found by `veriq optimize` (linear coupling for c3x_linear and reverse6_nn); an upper "
                       "bound on the optimum, not the optimum",
         "tasks": best}, indent=1) + "\n")

    # ---- corpus
    rng = random.Random(mut["seed"])
    rows = mut["mutants"]
    k = 0
    n_rt = 0
    with open(OUT / "corpus" / "mutants.jsonl", "w") as f, open(OUT / "corpus" / "correct.jsonl", "w") as g:
        for a in ASSISTANTS:
            for task, spec in R.TASKS.items():
                cand = load_circuit(HARD / "raw" / f"{a}.py", spec["fn"])
                g.write(json.dumps({"id": f"ok-{a}-{task}", "task": task, "source_assistant": a, "mode": spec["mode"],
                                    "equivalent": True, "qasm": to_qasm(cand)}) + "\n")
                its = H._items(cand)
                for op_name, desc, m in H.mutants(cand, rng):
                    r = rows[k]
                    assert (r["assistant"], r["task"], r["operator"], r["mutation"]) == (a, task, op_name, desc), (k, desc)
                    q = to_qasm(m)
                    if not same_unitary(from_qasm(q), m):
                        raise SystemExit(f"QASM round-trip changed mutant {k}")
                    n_rt += 1
                    k += 1
                    f.write(json.dumps({
                        "id": f"vb01-{k:04d}", "task": task, "source_assistant": a, "mode": spec["mode"],
                        "mutation_class": op_name, "description": desc, "location": location(its, desc, op_name),
                        "equivalent": r["proof"] == "PASS", "study_class": r["class"],
                        "detected_by": detected_by(r),
                        "recorded": {k2: r[k2] for k2 in ("proof", "aer_hist_from_zero", "exact_tvd_from_zero",
                                                         "exact_max_tvd_all_basis_inputs") if k2 in r},
                        "qasm": q}) + "\n")
    assert k == len(rows) == mut["total_mutants"], (k, len(rows))

    (OUT / "corpus" / "README.md").write_text(CORPUS_README.format(n=k, seed=mut["seed"]))
    manifest = {"version": VERSION, "files": {str(p.relative_to(OUT)): sha256(p)
                                              for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "MANIFEST.json"}}
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"v{VERSION}: 7 tasks, {k} mutants ({n_rt} QASM round-trips verified), 28 correct circuits, "
          f"best-known for {len(best)} tasks -> {OUT}")
    return 0


CORPUS_README = """# Veriq Bench v0.1 bug corpus

`mutants.jsonl`: {n} mutants, one JSON object per line, of the 28 hard-round circuits (seed {seed}).
`correct.jsonl`: the 28 original circuits (all verified correct), usable as negatives.
Field definitions: [../SCHEMA.md](../SCHEMA.md). Score a detector with `veriq bench corpus-eval --detector X`.
"""

if __name__ == "__main__":
    raise SystemExit(main())
