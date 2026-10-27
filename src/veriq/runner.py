"""Orchestrates all checks into a single Report."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from qiskit import QuantumCircuit

from . import checks
from .loader import BuildError, load_circuit
from .models import CheckResult, Report, Status, overall_verdict


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


MODES = ("unitary", "state")


def build_failure_report(target: str, exc: BuildError, reference: str | None = None,
                         seconds: float = 0.0) -> Report:
    """A candidate that does not build is a FAIL, not an input error."""
    c = CheckResult("Build", Status.FAIL, f"Does not build: {exc}",
                    {"error_type": exc.error_type, "exception": exc.exc_type, "message": str(exc)[:500]})
    return Report(target=target, reference=reference, verdict=Status.FAIL, checks=[c], metrics={},
                  seconds=seconds, versions=_versions())


def run_checks(target: str | QuantumCircuit, reference: str | QuantumCircuit | None = None,
               expect: str | dict | None = None, backend: str | None = None, shots: int = 4096,
               seed: int = 7, timeout: float = 30.0, mode: str = "unitary",
               allowed_gates: list[str] | None = None, function: str | None = None,
               reference_function: str | None = None, coupling: str | list | None = None,
               no_black_boxes: bool = False) -> Report:
    """Run all checks.

    mode="unitary": the candidate must equal the reference as a unitary (up to global phase).
    mode="state":   the candidate must prepare the same state from |0...0> (up to global phase).
    allowed_gates:  optional gate-set constraint; any other instruction is a FAIL.
    function / reference_function: builder names inside multi-function .py modules.
    coupling:       optional coupling map ('linear', 'ring', '0-1,1-2' or edge list), checked on the
                    circuit AS WRITTEN: any 2-qubit gate off an edge, or any 3+-qubit gate, is a FAIL.
    no_black_boxes: FAIL on UnitaryGate / Initialize / StatePreparation / PermutationGate / library blocks.
    A candidate whose code raises or returns no circuit yields a FAIL report ("does not build").
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    t0 = time.perf_counter()
    name = str(target if not isinstance(target, QuantumCircuit) else target.name)
    if function and not isinstance(target, QuantumCircuit):
        name = f"{name}::{function}"
    ref = None
    if reference is not None:
        ref = (load_circuit(reference, reference_function) if not isinstance(reference, QuantumCircuit)
               else reference)
    ref_name = None if reference is None else str(reference if not isinstance(reference, QuantumCircuit) else reference.name)
    try:
        cand = load_circuit(target, function) if not isinstance(target, QuantumCircuit) else target
    except BuildError as exc:
        return build_failure_report(name, exc, ref_name, time.perf_counter() - t0)
    exp = parse_expect(expect)

    ti, compiled = checks.transpile_integrity(cand, backend=backend, timeout=timeout, mode=mode)
    if mode == "state":
        re_ = checks.state_equivalence(cand, ref)
    else:
        re_ = checks.reference_equivalence(cand, ref, timeout=timeout)
    gs = checks.gate_set_check(cand, allowed_gates)
    cp = checks.coupling_check(cand, coupling)
    bb = checks.black_box_check(cand, no_black_boxes)
    st = checks.statistical_test(cand, exp, ref, shots=shots, seed=seed)
    mt, metrics = checks.metrics_check(cand, compiled)
    if ref is not None:
        metrics["reference"] = checks.circuit_metrics(ref)

    results = [ti, re_] + [c for c in (gs, cp, bb) if c.status != Status.SKIPPED] + [st, mt]
    return Report(
        target=name,
        reference=ref_name,
        verdict=overall_verdict([ti, re_, gs, cp, bb, st]),
        checks=results,
        metrics=metrics,
        circuit_text=_draw(cand),
        reference_text=_draw(ref) if ref is not None else "",
        seconds=time.perf_counter() - t0,
        versions=_versions(),
    )
