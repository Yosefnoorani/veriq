"""Qiskit HumanEval test-strength audit with Veriq mutants (the dataset ships no model generations).

For every task whose canonical solution returns a QuantumCircuit, we build small single-edit mutants of
that circuit (delete a gate, negate an angle, swap the qubits of a 2-qubit gate, pi written as 3.14),
hand the dataset's own `check(candidate)` a candidate that returns the mutant, and record whether the
test still passes. Veriq then decides whether each mutant is actually wrong (unitary / state from
|0...0>, up to global phase, final measurements stripped). A *surviving wrong mutant* is a circuit that
passes the dataset's test but is provably not equivalent to the canonical circuit.

Runs in a Qiskit 2.4.2 env matching the dataset's requirements.txt:

    /workspace/datasets/qhe/bin/python benchmark/real_bugs/humaneval_mutants.py \
        --dataset /workspace/datasets/qiskit-human-eval --out benchmark/real_bugs/raw/humaneval_mutants.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
MAX_PER_OPERATOR = 4


def _program(problem, exclude_prompt):
    prompt = "" if exclude_prompt else problem["prompt"]
    return prompt + "\n" + problem["canonical_solution"] + "\n" + problem["test"]


def _rebuild(qc, data):
    m = qc.copy_empty_like()
    for inst in data:
        m.append(inst)
    return m


def mutants(qc, rng):
    """Yield (operator, description, index, mutated instruction list) -- deterministic for a given qc."""
    items = [inst for inst in qc.data if inst.operation.name != "barrier" and inst.operation.name != "measure"]
    idx_all = [i for i, inst in enumerate(qc.data) if inst.operation.name not in ("barrier", "measure")]

    def pick(idxs):
        idxs = list(idxs)
        return idxs if len(idxs) <= MAX_PER_OPERATOR else sorted(rng.sample(idxs, MAX_PER_OPERATOR))

    data = list(qc.data)
    for i in pick(idx_all):
        yield "delete_gate", f"delete #{i} {data[i].operation.name}", data[:i] + data[i + 1:]
    par = [i for i in idx_all if data[i].operation.params
           and all(isinstance(p, (int, float)) and not isinstance(p, bool) for p in data[i].operation.params)
           and any(abs(float(p)) > 1e-9 for p in data[i].operation.params)]
    for i in pick(par):
        op = data[i].operation.copy()
        op.params = [-float(p) for p in op.params]
        yield "negate_angle", f"negate #{i} {op.name}", data[:i] + [data[i].replace(operation=op)] + data[i + 1:]
    if par:
        new = list(data)
        for i in par:
            op = new[i].operation.copy()
            op.params = [float(p) * 3.14 / math.pi for p in op.params]
            new[i] = new[i].replace(operation=op)
        yield "pi_as_3.14", f"pi as 3.14 in {len(par)} angles", new
    two = [i for i in idx_all if len(data[i].qubits) == 2 and data[i].operation.name not in ("swap", "cz", "cp", "rzz", "iswap")]
    for i in pick(two):
        yield "swap_qubits", f"swap qubits of #{i} {data[i].operation.name}", \
            data[:i] + [data[i].replace(qubits=tuple(data[i].qubits)[::-1])] + data[i + 1:]
    del items


def judge(orig, mut):
    from qiskit.quantum_info import Statevector
    import numpy as np
    from veriq import checks
    a, b = checks.unitary_part(orig), checks.unitary_part(mut)
    if checks.non_unitary_ops(a) or checks.non_unitary_ops(b) or a.parameters or b.parameters:
        return {"unitary": None, "state": None, "note": "non-unitary or parameterised"}
    if a.num_qubits > 12:
        return {"unitary": None, "state": None, "note": ">12 qubits"}
    v, ev = checks.prove_equivalence(a, b, timeout=30)
    fid = float(abs(np.vdot(Statevector(a).data, Statevector(b).data)) ** 2)
    return {"unitary": {"equivalent": True, "not_equivalent": False}.get(v), "unitary_method": ev.get("method"),
            "state": fid > 1 - 1e-8, "state_fidelity": round(fid, 8)}


def _child(problem, exclude_prompt, mode, q):
    """mode: None -> run canonical and report its first returned circuit; (op, k) -> run the k-th mutant."""
    import builtins
    import io
    import base64
    from qiskit import QuantumCircuit, qpy
    t0 = time.time()
    try:
        ns = {"__builtins__": dict(vars(builtins))}
        exec(_program(problem, exclude_prompt), ns)
        fn = ns[problem["entry_point"]]
        state = {"first": None, "mut": None, "applied": 0, "calls": 0}
        rng = random.Random(1234)

        def cand(*a, **k):
            out = fn(*a, **k)
            state["calls"] += 1
            if isinstance(out, QuantumCircuit):
                if state["first"] is None:
                    state["first"] = out.copy()
                if mode is not None:
                    muts = list(mutants(out, random.Random(1234)))
                    if mode < len(muts):
                        op, desc, data = muts[mode]
                        state["applied"] += 1
                        mut = _rebuild(out, data)
                        if state["mut"] is None:
                            state["mut"] = (op, desc, out.copy(), mut.copy())
                        return mut
            return out

        cand.__name__ = fn.__name__
        cand.__doc__ = fn.__doc__
        ok, err = True, None
        try:
            ns["check"](cand)
        except BaseException as exc:  # noqa: BLE001
            ok, err = False, repr(exc)[:300]
        res = {"passed": ok, "error": err, "calls": state["calls"], "applied": state["applied"],
               "seconds": round(time.time() - t0, 2)}
        if mode is None:
            qc = state["first"]
            res["returns_circuit"] = qc is not None
            if qc is not None:
                res["n_mutants"] = len(list(mutants(qc, rng)))
                res["qubits"] = qc.num_qubits
                res["ops"] = dict(qc.count_ops())
        elif state["mut"] is not None:
            op, desc, orig, mut = state["mut"]
            res.update(operator=op, description=desc, **judge(orig, mut))
            buf = io.BytesIO()
            qpy.dump([orig, mut], buf)
            res["qpy"] = base64.b64encode(buf.getvalue()).decode()
        q.put(res)
    except BaseException as exc:  # noqa: BLE001
        q.put({"passed": False, "error": "harness: " + repr(exc)[:300], "seconds": round(time.time() - t0, 2)})


def run(problem, exclude_prompt, mode, timeout):
    ctx = mp.get_context("fork")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(problem, exclude_prompt, mode, q))
    p.start()
    try:
        res = q.get(timeout=timeout)
    except Exception:  # noqa: BLE001
        res = {"passed": False, "error": f"timeout {timeout}s"}
    p.join(5)
    if p.is_alive():
        p.kill()
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=90)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    root = Path(a.dataset)
    skip = {l.strip() for l in (root / "scripts/skip_ci.txt").read_text().splitlines() if l.strip() and not l.startswith("#")}
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {(r["dataset"], r["task_id"]) for r in map(json.loads, out.read_text().splitlines())}
    only = set(filter(None, a.only.split(",")))
    for fname, excl in (("dataset_qiskit_test_human_eval.json", False), ("dataset_qiskit_test_human_eval_hard.json", True)):
        dname = "hard" if "hard" in fname else "normal"
        for prob in json.loads((root / "dataset" / fname).read_text()):
            tid = prob["task_id"]
            if (dname, tid) in done or (only and tid not in only):
                continue
            row = {"dataset": dname, "task_id": tid}
            if tid in skip:
                row["canonical"] = {"skipped": "listed in scripts/skip_ci.txt"}
            else:
                base = run(prob, excl, None, a.timeout)
                row["canonical"] = base
                row["mutants"] = []
                if base.get("passed") and base.get("returns_circuit"):
                    for k in range(base.get("n_mutants", 0)):
                        r = run(prob, excl, k, a.timeout)
                        r.pop("qpy", None) if r.get("passed") is False else None
                        row["mutants"].append({"k": k, **r})
            with out.open("a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            m = row.get("mutants") or []
            print(f"{dname}/{tid}: canonical={'PASS' if row['canonical'].get('passed') else 'fail'} "
                  f"circuit={row['canonical'].get('returns_circuit')} mutants={len(m)} "
                  f"survived={sum(1 for x in m if x.get('passed'))}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
