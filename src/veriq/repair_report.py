"""Structured, machine-readable repair feedback for a failing circuit.

`build_repair_report(candidate, reference, mode)` explains a FAIL so that a person or an LLM can fix it:

* counterexample: an input on which the candidate and the reference differ, with the expected (reference)
  and actual (candidate) output distributions;
* localization: WHERE in the candidate the bug is, by "gap correction support" (see below);
* hardware violations: failing gate-set / coupling-map / black-box checks;
* metric deltas: candidate vs reference cost metrics;
* hints: short natural-language suggestions, including an exact fix when one is found.

Localization (exact, small circuits). Let the candidate's gates be G_0..G_{m-1} with U_c = G_{m-1}...G_0 and
let P_g = G_{g-1}...G_0 be the first g gates. Inserting the operator D_g = P_g U_c^dagger U_r P_g^dagger in the
gap just before gate g turns the candidate into the reference exactly (unitary mode). If the candidate is
correct except for one wrong / missing / extra gate on qubits Q, then D_g acts only on Q for the gaps next
to the bug, while further away it is spread by the surrounding gates. Veriq computes the set of qubits D_g
acts on non-trivially (its "support") for every gap, and reports the gaps with the smallest support as the
suspected region. In state mode the same is done with states: a local fix on qubits Q exists at gap g iff
P_g|0> and P_g U_c^dagger |r> have equal reduced density matrices on the other qubits (subsets |Q| <= 2).
When the minimal support is 1 or 2 qubits, D_g is extracted and matched to a named gate, which gives an
exact fix ("insert cx(2,1) before gate #7", "delete gate #7", "replace gate #7 by p(pi/4)").

Gate indices refer to the circuit with final measurements removed (`checks.unitary_part`), counting every
instruction in `circuit.data` (barriers included).
"""
from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector, partial_trace

from . import checks

SCHEMA = "veriq.repair_report/1"
UNITARY_LOCALIZE_MAX_QUBITS = 10
STATE_LOCALIZE_MAX_QUBITS = 10
MAX_GATES = 2000
TOL = 1e-7
HW_CHECKS = ("Gate-set constraint", "Coupling-map constraint", "No black boxes")
SKIP = {"barrier", "delay"}


# --------------------------------------------------------------------------- operator helpers

def _tensor(d: np.ndarray, n: int) -> np.ndarray:
    return d.reshape((2,) * (2 * n))


def _row_ax(q: int, n: int) -> int:  # little-endian: qubit q is the (n-1-q)-th row axis
    return n - 1 - q


def _trivial_on(t: np.ndarray, q: int, n: int, scale: float) -> bool:
    """True iff the operator (as a 2n-axis tensor) is A (x) I on qubit q."""
    r, c = _row_ax(q, n), 2 * n - 1 - q
    off01 = np.take(np.take(t, 0, axis=r), 1, axis=c - 1)
    off10 = np.take(np.take(t, 1, axis=r), 0, axis=c - 1)
    d0 = np.take(np.take(t, 0, axis=r), 0, axis=c - 1)
    d1 = np.take(np.take(t, 1, axis=r), 1, axis=c - 1)
    tol = TOL * max(scale, 1.0) * 10
    return (np.abs(off01).max() < tol and np.abs(off10).max() < tol and np.abs(d0 - d1).max() < tol)


def operator_support(d: np.ndarray, n: int) -> list[int]:
    t = _tensor(d, n)
    scale = math.sqrt(d.shape[0])
    return [q for q in range(n) if not _trivial_on(t, q, n, scale)]


def _local_block(d: np.ndarray, n: int, qubits: list[int]) -> np.ndarray:
    """Return A where d = A (x) I_rest, A on `qubits` (little-endian order: qubits[0] is A's bit 0)."""
    t = _tensor(d, n)
    rest = [q for q in range(n) if q not in qubits]
    # slice row/col index 0 on every trivial qubit (highest axes first so positions stay valid)
    axes = sorted([_row_ax(q, n) for q in rest] + [2 * n - 1 - q for q in rest], reverse=True)
    for ax in axes:
        t = np.take(t, 0, axis=ax)
    k = len(qubits)
    # remaining row axes are qubits in descending order; reorder to the order of `qubits` (desc for matrix)
    order_desc = sorted(qubits, reverse=True)
    want = list(reversed(qubits))  # matrix row axes for A: A's highest bit first
    perm_r = [order_desc.index(q) for q in want]
    t = np.transpose(t, perm_r + [k + p for p in perm_r])
    return t.reshape(2 ** k, 2 ** k)


def _phase_equal(a: np.ndarray, b: np.ndarray, tol: float = 1e-6) -> bool:
    if a.shape != b.shape:
        return False
    k = int(np.argmax(np.abs(b)))
    if abs(b.flat[k]) < 1e-9:
        return False
    ph = a.flat[k] / b.flat[k]
    if abs(abs(ph) - 1) > 1e-6:
        return False
    return bool(np.abs(a - ph * b).max() < tol)


def _named_candidates(k: int) -> list[tuple[str, list[float], list[int], QuantumCircuit]]:
    from qiskit.circuit.library import (CXGate, CZGate, HGate, SdgGate, SGate, SwapGate, SXdgGate, SXGate,
                                        TdgGate, TGate, XGate, YGate, ZGate)
    out = []
    if k == 1:
        for g in (XGate(), YGate(), ZGate(), HGate(), SGate(), SdgGate(), TGate(), TdgGate(), SXGate(), SXdgGate()):
            out.append((g.name, [], [0], g))
    else:
        out += [("cx", [], [0, 1], CXGate()), ("cx", [], [1, 0], CXGate()), ("cz", [], [0, 1], CZGate()),
                ("swap", [], [0, 1], SwapGate())]
    return out


def identify_gate(a: np.ndarray) -> dict[str, Any] | None:
    """Match a 2x2 or 4x4 unitary (up to global phase) to a named gate; qubits are local indices."""
    k = int(round(math.log2(a.shape[0])))
    for name, params, qs, g in _named_candidates(k):
        qc = QuantumCircuit(k)
        qc.append(g, qs)
        if _phase_equal(a, Operator(qc).data):
            return {"name": name, "params": params, "local_qubits": qs}
    if np.abs(a - np.diag(np.diag(a))).max() < 1e-7:  # diagonal: p(theta) / cp(theta) up to phase
        dg = np.diag(a) / np.diag(a)[0]
        if k == 1:
            return {"name": "p", "params": [float(np.angle(dg[1]))], "local_qubits": [0]}
        if np.allclose(dg[:3], 1, atol=1e-7):
            return {"name": "cp", "params": [float(np.angle(dg[3]))], "local_qubits": [0, 1]}
    if k == 1:
        return {"name": "unitary", "params": [], "local_qubits": [0], "matrix": _mat_json(a)}
    return {"name": "unitary", "params": [], "local_qubits": list(range(k)), "matrix": _mat_json(a)}


def _mat_json(a: np.ndarray) -> list:
    return [[[round(float(z.real), 8), round(float(z.imag), 8)] for z in row] for row in a]


def _fmt_angle(x: float) -> str:
    for den in (1, 2, 3, 4, 6, 8, 16):
        num = x * den / math.pi
        if abs(num - round(num)) < 1e-6 and round(num) != 0:
            n = int(round(num))
            s = ("-" if n < 0 else "") + (f"{abs(n)}*" if abs(n) != 1 else "") + "pi"
            return s if den == 1 else f"{s}/{den}"
    return f"{x:.6g}"


def _gate_str(g: dict[str, Any]) -> str:
    p = f"({', '.join(_fmt_angle(x) for x in g.get('params', []))})" if g.get("params") else ""
    return f"{g['name']}{p}({', '.join(str(q) for q in g['qubits'])})"


# --------------------------------------------------------------------------- localization

def _gates(u: QuantumCircuit) -> list[dict[str, Any]]:
    out = []
    for i, inst in enumerate(u.data):
        op = inst.operation
        params = []
        for p in op.params:
            try:
                params.append(float(p))
            except (TypeError, ValueError):
                params.append(str(p))
        out.append({"index": i, "name": op.name, "qubits": [u.find_bit(q).index for q in inst.qubits],
                    "params": params})
    return out


def _regions(sizes: list[int], best: int) -> list[tuple[int, int]]:
    out, start = [], None
    for g, s in enumerate(sizes + [None]):
        if s == best and start is None:
            start = g
        elif s != best and start is not None:
            out.append((start, g - 1))
            start = None
    return out


def _region_dict(r: tuple[int, int], gates: list[dict[str, Any]]) -> dict[str, Any]:
    g0, g1 = r
    lo, hi = max(g0 - 1, 0), min(g1, len(gates) - 1)
    return {"gap_start": g0, "gap_end": g1, "gate_start": lo, "gate_end": hi,
            "gates": [dict(gates[i], text=_gate_str(gates[i])) for i in range(lo, hi + 1)][:40]}


def localize_unitary(cand: QuantumCircuit, ref: QuantumCircuit) -> dict[str, Any]:
    n, m = cand.num_qubits, len(cand.data)
    uc, ur = Operator(cand).data, Operator(ref).data
    d = Operator(uc.conj().T @ ur)
    gates = _gates(cand)
    sizes, supports, ds = [], [], []
    for g in range(m + 1):
        sup = operator_support(d.data, n)
        sizes.append(len(sup))
        supports.append(sup)
        ds.append(d.data if len(sup) <= 2 else None)
        if g == m:
            break
        inst = cand.data[g]
        if inst.operation.name in SKIP:
            continue
        qs = [cand.find_bit(q).index for q in inst.qubits]
        go = Operator(inst.operation)
        d = d.compose(go, qargs=qs).dot(go.adjoint(), qargs=qs)
    best = min(sizes)
    out: dict[str, Any] = {"available": True, "method": "gap correction support (exact, unitary)",
                           "num_gates": m, "min_support_qubits": best,
                           "support_size_per_gap": sizes if m <= 400 else None}
    if best == 0:
        out.update(equivalent=True, regions=[])
        return out
    # tie-break among the smallest-support gaps: a correction that is a named gate (cx, p(theta), h, ...)
    # is more likely to sit exactly where the bug is than one conjugated by neighbouring gates
    score = [2 * s for s in sizes]
    if best <= 2:
        for g, s in enumerate(sizes):
            if s == best and identify_gate(_local_block(ds[g], n, supports[g]))["name"] != "unitary":
                score[g] -= 1
    sizes_rank = score
    regs = _regions(sizes_rank, min(sizes_rank))
    out["regions"] = [dict(_region_dict(r, gates), support=supports[r[0]]) for r in regs][:8]
    out["single_gate_fix_possible"] = best <= 2
    if best <= 2:
        out["fixes"] = _fixes(regs, supports, ds, gates, cand)
    return out


def _fixes(regs, supports, ds, gates, cand) -> list[dict[str, Any]]:
    """Exact single-gate edits that make the candidate equal to the reference (unitary mode)."""
    n = cand.num_qubits
    fixes: list[dict[str, Any]] = []
    for g0, g1 in regs[:4]:
        span = list(range(g0, g1 + 1))
        if len(span) > 64:
            span = span[:32] + span[-32:]
        for g in span:
            sup = supports[g]
            a = _local_block(ds[g], n, sup)
            ident = identify_gate(a)
            ins = {"name": ident["name"], "params": ident["params"],
                   "qubits": [sup[i] for i in ident["local_qubits"]]}
            if "matrix" in ident:
                ins["matrix"] = ident["matrix"]
            if g in (g0, g1):  # inserting anywhere inside the region works; report its two ends
                fixes.append({"action": "insert", "gap": g, "before_gate": g if g < len(gates) else None,
                              "gate": ins, "text": f"insert {_gate_str(ins)} before gate #{g}" if g < len(gates)
                              else f"append {_gate_str(ins)} at the end"})
            # the gate just before the gap may be the culprit: delete or replace it
            for j in (g - 1, g):
                if 0 <= j < len(gates) and set(gates[j]["qubits"]) >= set(sup) and gates[j]["name"] not in SKIP:
                    gj = gates[j]
                    gq = gj["qubits"]
                    go = Operator(cand.data[j].operation).data
                    k = len(gq)
                    if k > 3:
                        continue
                    # correction lifted to the gate's qubits
                    full = _local_block(ds[g], n, gq) if set(sup) <= set(gq) else None
                    if full is None:
                        continue
                    new = full @ go if j == g - 1 else go @ full  # D after gate j-1.. : new gate = D*G or G*D
                    if _phase_equal(new, np.eye(2 ** k)):
                        fixes.append({"action": "delete", "gate_index": j,
                                      "text": f"delete gate #{j} {_gate_str(gj)}"})
                    elif k <= 2:
                        idg = identify_gate(new)
                        if idg["name"] != "unitary":
                            rep = {"name": idg["name"], "params": idg["params"],
                                   "qubits": [gq[i] for i in idg["local_qubits"]]}
                            fixes.append({"action": "replace", "gate_index": j, "gate": rep,
                                          "text": f"replace gate #{j} {_gate_str(gj)} by {_gate_str(rep)}"})
    seen, uniq = set(), []
    for f in fixes:
        if f["text"] not in seen:
            seen.add(f["text"])
            uniq.append(f)
    order = {"delete": 0, "replace": 1, "insert": 2}
    uniq.sort(key=lambda f: (order[f["action"]], "matrix" in f.get("gate", {})))
    return uniq[:8]


def _state_support(a: Statevector, b: Statevector, n: int) -> tuple[int, list[int]]:
    if abs(np.vdot(a.data, b.data)) ** 2 > 1 - 1e-8:
        return 0, []
    for k in (1, 2):
        for qs in itertools.combinations(range(n), k):
            rest = list(qs)
            ra, rb = partial_trace(a, rest).data, partial_trace(b, rest).data
            if np.abs(ra - rb).max() < 1e-7:
                return k, list(qs)
    return 3, []


def localize_state(cand: QuantumCircuit, ref: QuantumCircuit) -> dict[str, Any]:
    n, m = cand.num_qubits, len(cand.data)
    gates = _gates(cand)
    a = Statevector.from_label("0" * n)
    b = Statevector(ref).evolve(cand.inverse())
    sizes, supports = [], []
    for g in range(m + 1):
        s, sup = _state_support(a, b, n)
        sizes.append(s)
        supports.append(sup)
        if g == m:
            break
        inst = cand.data[g]
        if inst.operation.name in SKIP:
            continue
        qs = [cand.find_bit(q).index for q in inst.qubits]
        a = a.evolve(inst.operation, qargs=qs)
        b = b.evolve(inst.operation, qargs=qs)
    best = min(sizes)
    out: dict[str, Any] = {"available": True, "method": "gap correction support (exact, state from |0...0>)",
                           "num_gates": m, "min_support_qubits": best if best <= 2 else ">2",
                           "support_size_per_gap": sizes if m <= 400 else None}
    if best == 0:
        out.update(equivalent=True, regions=[])
        return out
    regs = _regions(sizes, best)
    out["regions"] = [dict(_region_dict(r, gates), support=supports[r[0]]) for r in regs][:8]
    out["single_gate_fix_possible"] = best <= 2
    return out


def localize(cand: QuantumCircuit, ref: QuantumCircuit, mode: str = "unitary") -> dict[str, Any]:
    u, r = checks.unitary_part(cand), checks.unitary_part(ref)
    if u.num_qubits != r.num_qubits:
        return {"available": False, "reason": f"different widths {u.num_qubits} vs {r.num_qubits}"}
    nu = checks.non_unitary_ops(u) + checks.non_unitary_ops(r)
    if nu:
        return {"available": False, "reason": f"mid-circuit non-unitary operations {sorted(set(nu))}"}
    if len(u.data) > MAX_GATES:
        return {"available": False, "reason": f"{len(u.data)} gates > {MAX_GATES}"}
    limit = UNITARY_LOCALIZE_MAX_QUBITS if mode == "unitary" else STATE_LOCALIZE_MAX_QUBITS
    if u.num_qubits > limit:
        return {"available": False, "reason": f"{u.num_qubits} qubits > {limit} (exact localization limit)"}
    try:
        return localize_unitary(u, r) if mode == "unitary" else localize_state(u, r)
    except Exception as exc:  # e.g. a gate without a matrix
        return {"available": False, "reason": f"localization failed: {exc!r}"[:300]}


# --------------------------------------------------------------------------- report

def _counterexample(cand: QuantumCircuit, ref: QuantumCircuit, mode: str,
                    result: dict[str, Any] | None) -> dict[str, Any] | None:
    cex = None
    for c in (result or {}).get("checks", []):
        cex = cex or (c.get("evidence") or {}).get("counterexample")
    cex = cex or (result or {}).get("counterexample")
    u, r = checks.unitary_part(cand), checks.unitary_part(ref)
    if u.num_qubits != r.num_qubits or checks.non_unitary_ops(u) or checks.non_unitary_ops(r):
        return cex
    if mode == "state":
        if u.num_qubits > 16:
            return cex
        sa, sb = Statevector(u), Statevector(r)
        fid = float(abs(np.vdot(sa.data, sb.data)) ** 2)
        if fid > 1 - 1e-8:
            return None
        return {"input_state": "|" + "0" * u.num_qubits + ">", "fidelity": round(fid, 6),
                "expected_output_top": checks._top(sb.probabilities_dict(), 6),
                "actual_output_top": checks._top(sa.probabilities_dict(), 6)}
    if cex is None:
        cex = checks.find_counterexample(u, r)
    if not cex:
        return None
    out = {"input_state": cex.get("input_state"), "fidelity": cex.get("fidelity"),
           "expected_output_top": cex.get("reference_output_top", {}),
           "actual_output_top": cex.get("candidate_output_top", {})}
    if cex.get("note"):
        out["note"] = cex["note"]
    return out


def _metric_deltas(cand: QuantumCircuit, ref: QuantumCircuit | None) -> dict[str, Any]:
    mc = checks.circuit_metrics(cand)
    if ref is None:
        return {k: {"candidate": mc[k]} for k in ("qubits", "depth", "size", "two_qubit_gates", "multi_qubit_gates")}
    mr = checks.circuit_metrics(ref)
    out = {k: {"candidate": mc[k], "reference": mr[k], "delta": mc[k] - mr[k]}
           for k in ("qubits", "depth", "size", "two_qubit_gates", "multi_qubit_gates")}
    out["cx"] = {"candidate": mc["gate_counts"].get("cx", 0), "reference": mr["gate_counts"].get("cx", 0),
                 "delta": mc["gate_counts"].get("cx", 0) - mr["gate_counts"].get("cx", 0)}
    return out


def _hints(rep: dict[str, Any]) -> list[str]:
    h: list[str] = []
    cex = rep.get("counterexample")
    if cex:
        exp = ", ".join(f"{k}:{v:.3g}" for k, v in list(cex["expected_output_top"].items())[:3])
        act = ", ".join(f"{k}:{v:.3g}" for k, v in list(cex["actual_output_top"].items())[:3])
        h.append(f"On input {cex['input_state']} the reference gives {{{exp}}} but the candidate gives {{{act}}} "
                 f"(overlap {cex['fidelity']:.4f}). Bitstrings are little-endian: qubit 0 is the rightmost bit.")
        if cex.get("note"):
            h.append("All computational-basis inputs agree up to phase: look for a wrong phase / rotation angle "
                     "(p vs rz, a sign, pi written as 3.14) rather than a wrong CX.")
    loc = rep.get("localization") or {}
    if loc.get("available") and loc.get("regions"):
        r = loc["regions"][0]
        k = loc.get("min_support_qubits")
        where = f"gates #{r['gate_start']}..#{r['gate_end']}" if r["gate_end"] > r["gate_start"] \
            else f"gate #{r['gate_start']}"
        h.append(f"The first suspected region is {where} (" + ", ".join(g["text"] for g in r["gates"][:6]) +
                 (", ..." if len(r["gates"]) > 6 else "") + f"): a correction acting on qubits {r['support']} there "
                 f"fixes the circuit." if k in (1, 2) else
                 f"No single 1- or 2-qubit fix exists anywhere (minimum support {k} qubits): the error is spread "
                 f"over several gates or the construction is wrong; start with {where}.")
        for f in (loc.get("fixes") or [])[:2]:
            h.append(f"Exact fix found: {f['text']}.")
    elif loc and not loc.get("available"):
        h.append(f"Localization not available: {loc.get('reason')}.")
    for v in rep.get("hardware_violations", []):
        h.append(f"Hardware constraint violated ({v['check']}): {v['summary']}")
    return h


def build_repair_report(candidate: QuantumCircuit, reference: QuantumCircuit | None = None, mode: str = "unitary",
                        result: dict[str, Any] | None = None, localize_circuit: bool = True) -> dict[str, Any]:
    """Repair report for a candidate. `result` is a `Report.to_dict()` (or verify_circuit tool result); the
    hardware violations and failing checks are read from it."""
    checks_in = (result or {}).get("checks", [])
    rep: dict[str, Any] = {
        "schema": SCHEMA, "verdict": (result or {}).get("verdict"), "mode": mode,
        "failing_checks": [{"name": c["name"], "summary": c["summary"]} for c in checks_in if c["status"] == "FAIL"],
        "hardware_violations": [{"check": c["name"], "summary": c["summary"],
                                 "evidence": {k: v for k, v in (c.get("evidence") or {}).items()
                                              if k in ("violations", "black_boxes", "off_edge_two_qubit_gates", "multi_qubit_gates", "first_violations")}}
                                for c in checks_in if c["name"] in HW_CHECKS and c["status"] == "FAIL"],
        "counterexample": None, "localization": None,
        "metric_deltas": _metric_deltas(checks.unitary_part(candidate),
                                        checks.unitary_part(reference) if reference is not None else None),
    }
    if reference is not None:
        rep["counterexample"] = _counterexample(candidate, reference, mode, result)
        if localize_circuit and (rep["counterexample"] is not None or result is None
                                 or any(c["name"] in ("Reference equivalence", "State equivalence (from |0...0>)")
                                        and c["status"] == "FAIL" for c in checks_in)):
            rep["localization"] = localize(candidate, reference, mode)
    else:
        rep["localization"] = {"available": False, "reason": "no reference circuit"}
    rep["hints"] = _hints(rep)
    return rep


def apply_fix(circuit: QuantumCircuit, fix: dict[str, Any]) -> QuantumCircuit:
    """Apply one `localization.fixes` entry to (the unitary part of) a circuit and return the new circuit."""
    from qiskit.circuit.library import UnitaryGate, get_standard_gate_name_mapping

    u = checks.unitary_part(circuit)
    items = [(inst.operation, [u.find_bit(q).index for q in inst.qubits]) for inst in u.data]

    def make(g: dict[str, Any]):
        if g["name"] == "unitary":
            m = np.array([[complex(re, im) for re, im in row] for row in g["matrix"]])
            return UnitaryGate(m, check_input=False)
        std = get_standard_gate_name_mapping()[g["name"]]
        return type(std)(*g.get("params", [])) if g.get("params") else type(std)()

    if fix["action"] == "delete":
        items = items[:fix["gate_index"]] + items[fix["gate_index"] + 1:]
    elif fix["action"] == "replace":
        j = fix["gate_index"]
        items = items[:j] + [(make(fix["gate"]), fix["gate"]["qubits"])] + items[j + 1:]
    elif fix["action"] == "insert":
        g = fix["gap"]
        items = items[:g] + [(make(fix["gate"]), fix["gate"]["qubits"])] + items[g:]
    else:
        raise ValueError(f"unknown fix action {fix['action']!r}")
    out = QuantumCircuit(u.num_qubits, global_phase=u.global_phase, name=u.name)
    for op, qs in items:
        out.append(op, qs)
    return out
