"""Step 2 of the QuanBench real-bugs study (runs in the Veriq venv, Qiskit 2.6).

Reads the *.capture.jsonl files written by quanbench_capture.py and, for every call where
the dataset test invoked BOTH the canonical solution and the model solution with the same
arguments and both returned a QuantumCircuit, decides with Veriq whether the two circuits
agree at three strengths (all up to global phase, final measurements stripped):

  dist     exact output distribution from |0...0> over the classical bits (what a
           histogram test can see, without shot noise)
  state    the prepared statevector from |0...0> (relative phases included)
  unitary  the full unitary (formal proof: MQT QCEC, dense Operator fallback)

Unbound parameters are bound to the same seeded random values (by name) on both sides.

    .venv/bin/python benchmark/real_bugs/quanbench_veriq.py   # -> raw/*.veriq.jsonl + summary.json
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit, qpy
from qiskit.quantum_info import Statevector

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent / "src"))
from veriq import checks  # noqa: E402

RAW = ROOT / "raw"
TOL = 1e-6


def load(entry) -> QuantumCircuit:
    return qpy.load(io.BytesIO(base64.b64decode(entry["qpy"])))[0]


def bind_pair(a: QuantumCircuit, b: QuantumCircuit, seed: int = 2026):
    pa, pb = {p.name for p in a.parameters}, {p.name for p in b.parameters}
    if not pa and not pb:
        return a, b, None
    if pa != pb:
        return None, None, f"parameter names differ: {sorted(pa)} vs {sorted(pb)}"
    rng = np.random.default_rng(seed)
    vals = {n: float(rng.uniform(-np.pi, np.pi)) for n in sorted(pa)}
    a = a.assign_parameters({p: vals[p.name] for p in a.parameters})
    b = b.assign_parameters({p: vals[p.name] for p in b.parameters})
    return a, b, None


def measured_map(qc: QuantumCircuit):
    """qubit index -> clbit index for the final measurements (None if no measurements)."""
    m = {}
    for inst in qc.data:
        if inst.operation.name == "measure":
            m[qc.find_bit(inst.qubits[0]).index] = qc.find_bit(inst.clbits[0]).index
    return m or None


def distribution(qc_u: QuantumCircuit, mmap, nclbits: int) -> dict[str, float]:
    probs = Statevector(qc_u).probabilities()
    n = qc_u.num_qubits
    out: dict[str, float] = {}
    for idx, p in enumerate(probs):
        if p < 1e-12:
            continue
        if mmap is None:
            key = format(idx, f"0{n}b")
        else:
            bits = ["0"] * nclbits
            for q, c in mmap.items():
                bits[nclbits - 1 - c] = "1" if (idx >> q) & 1 else "0"
            key = "".join(bits)
        out[key] = out.get(key, 0.0) + float(p)
    return out


def tvd(p, q):
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in set(p) | set(q))


def compare(ref: QuantumCircuit, cand: QuantumCircuit) -> dict:
    r: dict = {"ref_qubits": ref.num_qubits, "cand_qubits": cand.num_qubits,
               "ref_ops": dict(ref.count_ops()), "cand_ops": dict(cand.count_ops())}
    ref, cand, err = bind_pair(ref, cand)
    if err:
        return {**r, "status": "undecided", "reason": err}
    mr, mc = measured_map(ref), measured_map(cand)
    ru, cu = checks.unitary_part(ref), checks.unitary_part(cand)
    bad = checks.non_unitary_ops(ru) + checks.non_unitary_ops(cu)
    if bad:
        return {**r, "status": "undecided", "reason": f"mid-circuit non-unitary ops: {sorted(set(bad))}"}
    if ru.num_qubits > 16 or cu.num_qubits > 16:
        return {**r, "status": "undecided", "reason": "more than 16 qubits"}
    # distribution (only meaningful if both measure the same number of clbits, or neither measures)
    if (mr is None) != (mc is None) or (mr is not None and ref.num_clbits != cand.num_clbits):
        r["dist"] = None
        r["dist_note"] = f"measurement layout differs (ref clbits {ref.num_clbits}, cand clbits {cand.num_clbits})"
    elif mr is None and ru.num_qubits != cu.num_qubits:
        r["dist"] = None
        r["dist_note"] = "no measurements and different widths"
    else:
        dr, dc = distribution(ru, mr, ref.num_clbits), distribution(cu, mc, cand.num_clbits)
        d = tvd(dr, dc)
        r["dist_tvd"] = round(d, 6)
        r["dist"] = d < TOL
        r["ref_dist_top"] = checks._top(dr, 6)
        r["cand_dist_top"] = checks._top(dc, 6)
    if ru.num_qubits != cu.num_qubits:
        r.update(state=None, unitary=None, width_note="different qubit counts")
    else:
        sr, sc = Statevector(ru), Statevector(cu)
        fid = float(abs(np.vdot(sr.data, sc.data)) ** 2)
        r["state_fidelity"] = round(fid, 8)
        r["state"] = fid > 1 - 1e-8
        verdict, ev = checks.prove_equivalence(ru, cu, timeout=30)
        r["unitary"] = {"equivalent": True, "not_equivalent": False}.get(verdict)
        r["unitary_method"] = ev.get("method")
        if r["unitary"] is False and ru.num_qubits <= 12:
            r["counterexample"] = checks.find_counterexample(cu, ru)
    r["status"] = "decided"
    return r


def pair_calls(calls):
    sol = [c for c in calls if c["role"] == "solution"]
    gen = [c for c in calls if c["role"] == "generated"]
    used = set()
    pairs = []
    for g in gen:
        for i, s in enumerate(sol):
            if i not in used and s["args"] == g["args"] and s["kwargs"] == g["kwargs"]:
                used.add(i)
                pairs.append((s, g))
                break
    return pairs, len(sol), len(gen)


def flatten(out):
    if out["kind"] == "circuit":
        return [out]
    if out["kind"] == "sequence":
        return [x for x in out["items"] if x["kind"] == "circuit"]
    return []


def sample_verdict(row) -> dict:
    pairs, ns, ng = pair_calls(row["calls"])
    comps = []
    for s, g in pairs:
        cs, cg = flatten(s["out"]), flatten(g["out"])
        if not cs or not cg or len(cs) != len(cg):
            continue
        for a, b in zip(cs, cg):
            try:
                comps.append({"args": s["args"], **compare(load(a), load(b))})
            except Exception as exc:  # noqa: BLE001
                comps.append({"args": s["args"], "status": "undecided", "reason": repr(exc)[:300]})
    # dedupe identical-arg comparisons (setUp runs once per test method)
    seen, uniq = set(), []
    for c in comps:
        key = json.dumps({k: v for k, v in c.items() if k != "args"}, sort_keys=True, default=str) + c["args"]
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    decided = [c for c in uniq if c["status"] == "decided"]
    v = {"circuit_pairs": len(uniq), "decided_pairs": len(decided)}
    if not uniq:
        v["class"] = "no_circuit_pair"
    elif not decided:
        v["class"] = "undecided"
    elif any(c.get("dist") is False for c in decided):
        v["class"] = "output_distribution_differs"
    elif any(c.get("state") is False for c in decided):
        v["class"] = "same_distribution_state_differs"
    elif any(c.get("unitary") is False for c in decided):
        v["class"] = "same_state_unitary_differs"
    elif any(c.get("dist") is None and c.get("state") is None for c in decided):
        v["class"] = "incomparable_layout"
    elif len(decided) < len(uniq):
        v["class"] = "partially_undecided"
    elif all(c.get("unitary") is True for c in decided):
        v["class"] = "unitary_equivalent"
    else:
        v["class"] = "state_equivalent_unitary_unknown"
    return {"comparisons": uniq, **v}


def main() -> int:
    summary = {}
    for cap in sorted(RAW.glob("*.capture.jsonl")):
        rows = [json.loads(line) for line in cap.open()]
        out_path = cap.with_name(cap.name.replace(".capture.jsonl", ".veriq.jsonl"))
        counts: dict = {}
        with out_path.open("w") as f:
            for row in rows:
                v = sample_verdict(row)
                rec = {"task_id": row["task_id"], "sample": row["sample"], "tests_passed": row["passed"], **v}
                f.write(json.dumps(rec, default=str) + "\n")
                key = ("pass" if row["passed"] else "fail") + ":" + v["class"]
                counts[key] = counts.get(key, 0) + 1
        summary[cap.name.replace(".capture.jsonl", "")] = {"samples": len(rows),
                                                          "tests_passed": sum(r["passed"] for r in rows),
                                                          "by_class": dict(sorted(counts.items()))}
        print(cap.name, json.dumps(summary[cap.name.replace(".capture.jsonl", "")], indent=1))
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "quanbench_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
