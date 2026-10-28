"""Exact gate-by-gate conversion into Qiskit, with an explicit endianness swap and global-phase bookkeeping.

Cirq and TKET both write a k-qubit operation's matrix big-endian over its argument list (the first qubit is
the most significant bit). Qiskit's `Operator` is little-endian over the qargs (qargs[0] is the least
significant bit). `be_to_le` reorders a big-endian matrix into Qiskit's convention, and `append_exact`
appends a Qiskit gate only after checking that its matrix equals the source matrix up to a phase e^{iφ};
φ is added to `qc.global_phase`, so the converted circuit has *exactly* the source unitary (not just up
to global phase). A candidate gate that differs by more than a phase is rejected and the caller falls
back (decomposition or an explicit UnitaryGate).
"""

from __future__ import annotations

import cmath

import numpy as np

ATOL = 1e-9


def be_to_le(mat: np.ndarray) -> np.ndarray:
    """Big-endian matrix over (q_0..q_{k-1}) -> little-endian matrix over the same qubit list."""
    mat = np.asarray(mat, dtype=complex)
    k = int(round(np.log2(mat.shape[0])))
    if k <= 1:
        return mat
    t = mat.reshape([2] * (2 * k))
    rev = list(range(k))[::-1]
    t = t.transpose(rev + [k + i for i in rev])
    return t.reshape(2 ** k, 2 ** k)


def phase_between(mine: np.ndarray, target: np.ndarray) -> float | None:
    """φ with e^{iφ}·mine == target, or None if they differ by more than a global phase."""
    idx = np.unravel_index(np.argmax(np.abs(target)), target.shape)
    if abs(mine[idx]) < 1e-12:
        return None
    ph = cmath.phase(target[idx] / mine[idx])
    if np.allclose(mine * cmath.exp(1j * ph), target, atol=ATOL):
        return ph
    return None


def append_exact(qc, gate, qargs, target_be: np.ndarray, cache: dict | None = None) -> bool:
    """Append `gate` on `qargs` if it equals `target_be` (big-endian over qargs) up to a phase."""
    from qiskit.quantum_info import Operator

    target = be_to_le(target_be)
    key = None
    if cache is not None:
        key = (gate.name, tuple(float(p) for p in gate.params), target.tobytes())
        if key in cache:
            ph = cache[key]
            if ph is None:
                return False
            qc.append(gate, qargs)
            qc.global_phase += ph
            return True
    ph = phase_between(Operator(gate).data, target)
    if cache is not None:
        cache[key] = ph
    if ph is None:
        return False
    qc.append(gate, qargs)
    qc.global_phase += ph
    return True


def append_unitary(qc, qargs, target_be: np.ndarray, label: str) -> None:
    """Fallback: an explicit UnitaryGate holding the exact source matrix (reported as opaque)."""
    from qiskit.circuit.library import UnitaryGate

    qc.append(UnitaryGate(be_to_le(target_be), label=label[:40]), qargs)
