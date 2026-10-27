"""Orchestrates all checks into a single Report."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from qiskit import QuantumCircuit

from . import checks
from .loader import load_circuit
from .models import Report, overall_verdict


def parse_expect(expect: str | dict | None) -> dict[str, Any] | None:
    """--expect accepts inline JSON or a path to a JSON file."""
    if expect is None or isinstance(expect, dict):
        return expect
    p = Path(expect)
    text = p.read_text() if p.exists() else expect
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("--expect must be a JSON object")
    return data


def _versions() -> dict[str, str]:
    from importlib.metadata import version

    out = {}
    for pkg in ("veriq", "qiskit", "qiskit-aer", "mqt.qcec"):
        try:
            out[pkg] = version(pkg)
        except Exception:
            out[pkg] = "?"
    return out


def _draw(qc: QuantumCircuit) -> str:
    try:
        return str(qc.draw(output="text", fold=110))
    except Exception:
        return repr(qc)


def run_checks(target: str | QuantumCircuit, reference: str | QuantumCircuit | None = None,
               expect: str | dict | None = None, backend: str | None = None, shots: int = 4096,
               seed: int = 7, timeout: float = 30.0) -> Report:
    t0 = time.perf_counter()
    cand = load_circuit(target) if not isinstance(target, QuantumCircuit) else target
    ref = None
    if reference is not None:
        ref = load_circuit(reference) if not isinstance(reference, QuantumCircuit) else reference
    exp = parse_expect(expect)

    ti, compiled = checks.transpile_integrity(cand, backend=backend, timeout=timeout)
    re_ = checks.reference_equivalence(cand, ref, timeout=timeout)
    st = checks.statistical_test(cand, exp, ref, shots=shots, seed=seed)
    mt, metrics = checks.metrics_check(cand, compiled)
    if ref is not None:
        metrics["reference"] = checks.circuit_metrics(ref)

    results = [ti, re_, st, mt]
    return Report(
        target=str(target if not isinstance(target, QuantumCircuit) else target.name),
        reference=None if reference is None else str(reference if not isinstance(reference, QuantumCircuit) else reference.name),
        verdict=overall_verdict([ti, re_, st]),
        checks=results,
        metrics=metrics,
        circuit_text=_draw(cand),
        reference_text=_draw(ref) if ref is not None else "",
        seconds=time.perf_counter() - t0,
        versions=_versions(),
    )
