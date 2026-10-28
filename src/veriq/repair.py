"""Repair loop: verify -> repair report -> fixer -> re-verify, with bounded retries.

The loop never decides correctness itself: every attempt is judged by `run_checks` (the same checks as
`veriq check`), and the loop stops at the first PASS, at the first INCONCLUSIVE (a proof could not be
decided, so editing further would be blind), when the fixer gives up, or after `max_attempts` fixes.

A *fixer* is any callable

    fixer(request: FixRequest) -> QuantumCircuit | str | None

that receives the current circuit, its source text (if any), the machine-readable repair report
(`veriq.repair_report`) and the history of earlier attempts, and returns a new circuit, new source text
(Python defining `build()` / `circuit`, or OpenQASM 2/3), or None to give up. No API keys are needed:
Veriq ships `demo_fixer`, a deterministic fixer that applies the report's exact single-gate fixes and
otherwise searches small local edits inside the localized region. To use an LLM, write a fixer that sends
`request.source` + `request.report` to the model and returns the code it answers with (see docs/repair.md);
the loop calls no external service on its own.
"""
from __future__ import annotations

import importlib
import math
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector

from . import checks
from .loader import load_circuit
from .repair_report import apply_fix, build_repair_report
from .runner import run_checks

STOP_VERDICTS = {"PASS", "INCONCLUSIVE"}


@dataclass
class FixRequest:
    circuit: QuantumCircuit
    source: str | None
    report: dict[str, Any]
    reference: QuantumCircuit | None
    mode: str
    attempt: int
    history: list[dict[str, Any]] = field(default_factory=list)


Fixer = Callable[[FixRequest], "QuantumCircuit | str | None"]


# --------------------------------------------------------------------------- demo fixer

def _equal(a: QuantumCircuit, b: QuantumCircuit, mode: str) -> bool:
    a, b = checks.unitary_part(a), checks.unitary_part(b)
    if a.num_qubits != b.num_qubits or a.num_qubits > 10:
        return False
    if mode == "state":
        return abs(np.vdot(Statevector(a).data, Statevector(b).data)) ** 2 > 1 - 1e-9
    return Operator(a).equiv(Operator(b))


def _items(qc: QuantumCircuit):
    return [(inst.operation, [qc.find_bit(q).index for q in inst.qubits]) for inst in qc.data]


def _rebuild(qc: QuantumCircuit, items) -> QuantumCircuit:
    out = QuantumCircuit(qc.num_qubits, global_phase=qc.global_phase, name=qc.name)
    for op, qs in items:
        out.append(op, qs)
    return out


def local_edits(qc: QuantumCircuit, indices: list[int]):
    """Small edits at the given gate indices: delete, negate an angle, flip a cx, crz->cp, rz->p; plus one
    global edit (angles written with 3.14 instead of pi)."""
    from qiskit.circuit.library import CPhaseGate, PhaseGate

    items = _items(qc)
    for i in indices:
        op, qs = items[i]
        if op.name == "barrier":
            continue
        yield f"delete gate #{i} {op.name}{tuple(qs)}", _rebuild(qc, items[:i] + items[i + 1:])
        if op.name == "cx":
            yield f"flip gate #{i} cx{tuple(qs)} -> cx{tuple(qs[::-1])}", \
                _rebuild(qc, items[:i] + [(op, qs[::-1])] + items[i + 1:])
        if op.params and all(isinstance(p, (int, float)) for p in op.params):
            new = op.copy()
            new.params = [-float(p) for p in op.params]
            yield f"negate the angle of gate #{i} {op.name}", _rebuild(qc, items[:i] + [(new, qs)] + items[i + 1:])
            if op.name == "crz":
                yield f"gate #{i}: crz -> cp", _rebuild(qc, items[:i] + [(CPhaseGate(op.params[0]), qs)] + items[i + 1:])
            if op.name == "rz":
                yield f"gate #{i}: rz -> p", _rebuild(qc, items[:i] + [(PhaseGate(op.params[0]), qs)] + items[i + 1:])
    par = [(op, qs) for op, qs in items if op.params and all(isinstance(p, (int, float)) for p in op.params)]
    if par:
        data = []
        for op, qs in items:
            if op.params and all(isinstance(p, (int, float)) for p in op.params):
                op = op.copy()
                op.params = [float(p) * math.pi / 3.14 for p in op.params]
            data.append((op, qs))
        yield "rescale every angle by pi/3.14 (pi written as 3.14)", _rebuild(qc, data)


def demo_fixer(req: FixRequest) -> QuantumCircuit | None:
    """Deterministic, offline fixer for tests and demos.

    1. Apply the report's exact single-gate fixes (named gates first; a raw 2x2/4x4 matrix is synthesized
       into u/cx gates).
    2. Otherwise try small local edits (`local_edits`) on the gates inside the localized regions and keep
       the first one that makes the circuit exactly equal to the reference (n <= 10).
    It knows the vocabulary of typical slips (the same operators as the mutation study), so its success rate
    on injected mutations is NOT a measure of how well an LLM would repair real bugs."""
    loc = req.report.get("localization") or {}
    u = checks.unitary_part(req.circuit)
    tried = {h.get("fix") for h in req.history}
    for f in loc.get("fixes") or []:
        if f["text"] in tried:
            continue
        new = apply_fix(u, f)
        if f.get("gate", {}).get("name") == "unitary":
            from qiskit import transpile

            new = transpile(new, basis_gates=["u", "cx"], optimization_level=0, qubits_initially_zero=False)
        new.metadata = {"veriq_fix": f["text"]}
        return new
    if req.reference is None:
        return None
    idx: list[int] = []
    for r in loc.get("regions") or []:
        idx += list(range(r["gate_start"], r["gate_end"] + 1))
    idx = sorted(set(idx))[:60]
    for desc, cand in local_edits(u, idx):
        if desc not in tried and _equal(cand, req.reference, req.mode):
            cand.metadata = {"veriq_fix": desc}
            return cand
    return None


def load_fixer(spec: str) -> Fixer:
    """'demo' or 'package.module:function'."""
    if spec == "demo":
        return demo_fixer
    if ":" not in spec:
        raise ValueError("fixer must be 'demo' or 'module:function'")
    mod, fn = spec.split(":", 1)
    return getattr(importlib.import_module(mod), fn)


# --------------------------------------------------------------------------- loop

def _from_source(text: str) -> QuantumCircuit:
    suffix = ".qasm" if "OPENQASM" in text[:200] else ".py"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"fixed{suffix}"
        p.write_text(text)
        return load_circuit(p)


def to_qasm(qc: QuantumCircuit) -> str | None:
    try:
        from qiskit import qasm2

        return qasm2.dumps(qc)
    except Exception:
        try:
            from qiskit import qasm3

            return qasm3.dumps(qc)
        except Exception:
            return None


def repair_loop(candidate: QuantumCircuit, reference: QuantumCircuit | None, fixer: Fixer = demo_fixer,
                mode: str = "unitary", max_attempts: int = 5, source: str | None = None,
                allowed_gates: list[str] | None = None, coupling: str | None = None,
                no_black_boxes: bool = False, timeout: float = 30.0, shots: int = 2048) -> dict[str, Any]:
    t0 = time.perf_counter()
    history: list[dict[str, Any]] = []
    cur, src = candidate, source
    stop = "max_attempts"
    report: dict[str, Any] = {}
    for attempt in range(max_attempts + 1):
        rep = run_checks(cur, reference=reference, mode=mode, allowed_gates=allowed_gates, coupling=coupling,
                         no_black_boxes=no_black_boxes, timeout=timeout, shots=shots).to_dict()
        v = rep["verdict"]
        report = build_repair_report(cur, reference, mode, result=rep, localize_circuit=v == "FAIL")
        loc = report.get("localization") or {}
        entry = {"attempt": attempt, "verdict": v,
                 "failing_checks": [c["name"] for c in report["failing_checks"]],
                 "localized_regions": [[r["gate_start"], r["gate_end"]] for r in loc.get("regions", [])][:4],
                 "exact_fixes": [f["text"] for f in loc.get("fixes", [])][:4],
                 "fix": (cur.metadata or {}).get("veriq_fix") if attempt else None}
        history.append(entry)
        if v in STOP_VERDICTS:
            stop = v
            break
        if attempt == max_attempts:
            break
        out = fixer(FixRequest(cur, src, report, reference, mode, attempt + 1, history))
        if out is None:
            stop = "fixer_gave_up"
            break
        if isinstance(out, str):
            src = out
            try:
                cur = _from_source(out)
            except Exception as exc:
                history.append({"attempt": attempt + 1, "verdict": "FAIL", "failing_checks": ["Build"],
                                "error": f"{exc}"[:300]})
                stop = "build_error"
                break
        else:
            cur, src = out, None
    final = history[-1]["verdict"]
    return {"verdict": final, "stop_reason": stop, "attempts": len(history) - 1, "history": history,
            "final_qasm": to_qasm(checks.unitary_part(cur)), "final_circuit": cur, "last_report": report,
            "seconds": round(time.perf_counter() - t0, 3)}
