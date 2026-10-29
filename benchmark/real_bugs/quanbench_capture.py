"""Step 1 of the QuanBench real-bugs study: run every published model solution against the
dataset's OWN unit tests (QuanBench harness semantics) and capture every circuit that the
reference and the candidate return during those tests.

Runs in a Qiskit 0.46 environment (the version QuanBench targets), NOT in the Veriq venv:

    uv venv -p 3.10 qb046 && VIRTUAL_ENV=qb046 uv pip install -r requirements-quanbench.txt
    qb046/bin/python benchmark/real_bugs/quanbench_capture.py --quanbench /path/to/Quanbench \
        --problems QuanBench44.jsonl --samples Quanbench_eval/generated/quanbench44/results_gpt-4.1_T0.8.jsonl \
        --out benchmark/real_bugs/raw/quanbench44_gpt-4.1.capture.jsonl

The test program is assembled exactly like Quanbench_eval.execution.build_check_program
(canonical solution, `cir_solution`, completion, `cir_generated`, test), except that
`cir_solution` / `cir_generated` are wrapped in recorders. Every returned QuantumCircuit is
copied at return time and serialised with QPY; the arguments are recorded by repr.
"""
from __future__ import annotations

import argparse
import base64
import builtins
import cmath
import contextlib
import io
import json
import multiprocessing
import os
import sys
import tempfile
import time
import traceback
import types
import unittest


def _read_jsonl(path):
    with open(path, encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def _serialise(obj):
    from qiskit import QuantumCircuit, qpy

    def one(c):
        buf = io.BytesIO()
        qpy.dump(c.copy(), buf)
        return {"kind": "circuit", "qpy": base64.b64encode(buf.getvalue()).decode(),
                "num_qubits": c.num_qubits, "num_clbits": c.num_clbits, "ops": dict(c.count_ops())}

    if isinstance(obj, QuantumCircuit):
        try:
            return one(obj)
        except Exception as exc:  # noqa: BLE001
            return {"kind": "circuit_unserialisable", "error": repr(exc)[:300]}
    if isinstance(obj, (tuple, list)) and obj and any(isinstance(x, QuantumCircuit) for x in obj):
        return {"kind": "sequence", "items": [_serialise(x) for x in obj]}
    return {"kind": type(obj).__name__, "repr": repr(obj)[:200]}


def _wrap(role, fn, log):
    def rec(*args, **kwargs):
        out = fn(*args, **kwargs)
        try:
            entry = {"role": role, "args": repr(args)[:500], "kwargs": repr(kwargs)[:500], "out": _serialise(out)}
        except Exception as exc:  # noqa: BLE001
            entry = {"role": role, "args": "?", "kwargs": "?", "out": {"kind": "error", "error": repr(exc)[:300]}}
        log.append(entry)
        return out
    rec.__wrapped__ = fn
    rec.__name__ = getattr(fn, "__name__", "rec")
    return rec


class _Sink(io.StringIO):
    def readable(self):
        return False


def _child(qb_root, problem, completion, timeout, q):
    sys.path.insert(0, qb_root)
    from Quanbench_eval import test_matrix as tm
    import numpy as np

    log: list = []
    details = {}
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        mod = types.ModuleType("__quanbench_eval__")
        mod.__dict__.update({
            "__builtins__": builtins, "__file__": "__quanbench_eval__.py", "sys": sys, "os": os, "np": np,
            "cmath": cmath, "environ": os.environ, "__veriq_wrap": _wrap, "__veriq_log": log,
            **{k: getattr(tm, k) for k in ("run_circuit", "compute_KL", "compare_depth_gatecount",
                                           "unitary_equivalent", "compute_matrix_similarity",
                                           "compute_KL_noexecute", "check_phase", "is_gate_count_subset")},
        })
        ep = problem["entry_point"]
        program = "\n".join([
            problem["canonical_solution"],
            f"cir_solution = __veriq_wrap('solution', {ep}, __veriq_log)",
            completion,
            f"cir_generated = __veriq_wrap('generated', {ep}, __veriq_log)",
            problem["test"],
        ])
        try:
            sink = _Sink()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                exec(program, mod.__dict__)
                suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
                res = unittest.TestResult()
                suite.run(res)
            for test, trace in res.failures + res.errors:
                details[test.id().split(".")[-1]] = trace[-1500:]
        except BaseException:  # noqa: BLE001
            details["All"] = traceback.format_exc()[-1500:]
    q.put({"passed": not details, "details": details, "calls": log})


def run_one(qb_root, problem, completion, timeout):
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    p = ctx.Process(target=_child, args=(qb_root, problem, completion, timeout, q))
    t0 = time.time()
    p.start()
    try:
        out = q.get(timeout=timeout)
    except Exception:  # noqa: BLE001
        out = {"passed": False, "details": {"All": "timed out"}, "calls": []}
    p.join(5)
    if p.is_alive():
        p.kill()
    out["seconds"] = round(time.time() - t0, 2)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--quanbench", required=True)
    ap.add_argument("--problems", required=True)
    ap.add_argument("--samples", default="", help="model solutions jsonl; omit with --canonical")
    ap.add_argument("--canonical", action="store_true", help="use each canonical solution as the candidate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--only", default="", help="comma-separated task ids")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.quanbench)
    probs = {p["task_id"]: p for p in _read_jsonl(os.path.join(root, a.problems))}
    samples = ([{"task_id": t, "solution": p["canonical_solution"]} for t, p in probs.items()] if a.canonical
               else _read_jsonl(os.path.join(root, a.samples)))
    only = set(filter(None, a.only.split(",")))
    seen: dict = {}
    done = set()
    if os.path.exists(a.out):
        done = {(r["task_id"], r["sample"]) for r in _read_jsonl(a.out)}
    with open(a.out, "a") as f:
        for s in samples:
            tid = s["task_id"]
            k = seen[tid] = seen.get(tid, -1) + 1
            if (only and tid not in only) or (tid, k) in done:
                continue
            r = run_one(root, probs[tid], s["solution"], a.timeout)
            row = {"task_id": tid, "sample": k, "entry_point": probs[tid]["entry_point"], **r}
            f.write(json.dumps(row) + "\n")
            f.flush()
            print(f"{tid}#{k}: {'PASS' if r['passed'] else 'fail'} ({r['seconds']} s, {len(r['calls'])} calls)",
                  flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
