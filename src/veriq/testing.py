"""Equivalence assertions for test suites.

    from veriq.testing import assert_equivalent
    assert_equivalent(my_circuit, reference)              # unitary equivalence, proved (QCEC / exact operator)
    assert_equivalent(my_circuit, reference, mode="state") # same state from |0...0>
    assert_equivalent(my_circuit, reference, mode="measured")  # same measured statistics for EVERY input state

All modes ignore global phase. Final measurements are stripped before the unitary/state comparison; "measured"
compares the outcome statistics of the measured qubits (phases right before a measurement are don't-cares).
An undecided comparison fails by default (a test should not pass on "we could not tell"); pass
``allow_unknown=True`` to accept it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Union

CircuitLike = Union["QuantumCircuit", str, Path]  # noqa: F821

MODES = ("unitary", "state", "measured")


class EquivalenceError(AssertionError):
    """Raised by assert_equivalent; carries the verdict and evidence."""

    def __init__(self, message: str, verdict: str, evidence: dict[str, Any]):
        super().__init__(message)
        self.verdict = verdict
        self.evidence = evidence


def _as_circuit(x: CircuitLike):
    from qiskit import QuantumCircuit

    if isinstance(x, QuantumCircuit):
        return x
    if isinstance(x, (str, Path)):
        s = str(x)
        if "OPENQASM" in s:  # QASM source text
            if "OPENQASM 3" in s:
                from qiskit import qasm3

                return qasm3.loads(s)
            from qiskit import qasm2

            return qasm2.loads(s, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
        from .loader import load_circuit

        return load_circuit(s)
    raise TypeError(f"expected a QuantumCircuit or a path to a circuit file, got {type(x).__name__}")


def _measured_qubits(qc) -> list[int]:
    return sorted({qc.find_bit(i.qubits[0]).index for i in qc.data if i.operation.name == "measure"})


def check_equivalent(a: CircuitLike, b: CircuitLike, mode: str = "unitary", timeout: float = 30.0) -> dict[str, Any]:
    """Return {"verdict": "equivalent" | "not_equivalent" | "unknown", "mode": ..., "evidence": {...}}."""
    import numpy as np

    from . import checks

    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    qa, qb = _as_circuit(a), _as_circuit(b)
    ua, ub = checks.unitary_part(qa), checks.unitary_part(qb)
    ev: dict[str, Any] = {"qubits": [qa.num_qubits, qb.num_qubits]}
    bad = sorted(set(checks.non_unitary_ops(ua) + checks.non_unitary_ops(ub)))
    if bad:
        ev["reason"] = f"mid-circuit non-unitary operations: {bad}"
        return {"verdict": "unknown", "mode": mode, "evidence": ev}
    if qa.num_qubits != qb.num_qubits:
        ev["reason"] = "different numbers of qubits"
        return {"verdict": "not_equivalent", "mode": mode, "evidence": ev}
    if mode == "unitary":
        verdict, e = checks.prove_equivalence(ua, ub, timeout=timeout)
        ev.update(method=e.get("method"))
        if verdict == "not_equivalent":
            ce = checks.find_counterexample(ua, ub)
            if ce:
                ev["counterexample"] = ce
        return {"verdict": verdict, "mode": mode, "evidence": ev}
    if mode == "state":
        eq = checks.zero_input_equal(ua, ub)
        return {"verdict": {True: "equivalent", False: "not_equivalent"}.get(eq, "unknown"), "mode": mode, "evidence": ev}
    # measured: Ua^dag P Ua == Ub^dag P Ub for every outcome projector P on the measured qubits
    ma, mb = _measured_qubits(qa), _measured_qubits(qb)
    if ma != mb:
        ev["reason"] = f"different measured qubits: {ma} vs {mb}"
        return {"verdict": "not_equivalent", "mode": mode, "evidence": ev}
    if not ma:
        ma = list(range(qa.num_qubits))
    if qa.num_qubits > 10:
        ev["reason"] = "mode='measured' is limited to 10 qubits"
        return {"verdict": "unknown", "mode": mode, "evidence": ev}
    from qiskit.quantum_info import Operator

    A, B = Operator(ua).data, Operator(ub).data
    n = qa.num_qubits
    idx = np.arange(2 ** n)
    for m in range(2 ** len(ma)):
        mask = np.ones(2 ** n, dtype=bool)
        for i, q in enumerate(ma):
            mask &= ((idx >> q) & 1) == ((m >> i) & 1)
        pa = A.conj().T @ (mask[:, None] * A)
        pb = B.conj().T @ (mask[:, None] * B)
        if np.abs(pa - pb).max() > 1e-8:
            # find an explicit input: an eigenvector of the difference
            w, v = np.linalg.eigh(pa - pb)
            k = int(np.argmax(np.abs(w)))
            ev["counterexample"] = {"outcome": format(m, f"0{len(ma)}b"), "probability_gap": round(float(abs(w[k])), 6),
                                    "note": "an input state on which the two circuits give different outcome probabilities"}
            return {"verdict": "not_equivalent", "mode": mode, "evidence": ev}
    ev["method"] = "exact projector comparison"
    return {"verdict": "equivalent", "mode": mode, "evidence": ev}


def assert_equivalent(a: CircuitLike, b: CircuitLike, mode: str = "unitary", timeout: float = 30.0,
                      allow_unknown: bool = False) -> dict[str, Any]:
    """Assert that two circuits are equivalent (up to global phase). Returns the verdict dict on success."""
    r = check_equivalent(a, b, mode=mode, timeout=timeout)
    v, ev = r["verdict"], r["evidence"]
    if v == "equivalent" or (v == "unknown" and allow_unknown):
        return r
    if v == "unknown":
        raise EquivalenceError(f"veriq could not decide {mode} equivalence ({ev.get('reason', 'timeout or too large')}); "
                               "pass allow_unknown=True to accept undecided results", v, ev)
    msg = f"circuits are NOT {mode}-equivalent"
    if "reason" in ev:
        msg += f": {ev['reason']}"
    ce = ev.get("counterexample")
    if ce:
        msg += f"\n  counterexample: {ce}"
    raise EquivalenceError(msg, v, ev)
