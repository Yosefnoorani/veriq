"""Trusted reference circuits for the Veriq hard round (7 non-standard tasks).

Each reference is checked against an INDEPENDENT mathematical spec in `verify_references()`:
explicit permutation matrices built from truth tables (maj5, cmul7, c3x, reverse6, add3) and explicit
target basis states (qpe_t -> index 9, bv22 -> index 22). References may use library gates (they are
trusted, not graded); the graded candidates may not.

Conventions: Qiskit little-endian (q0 is the least significant bit); no measurements.
Run this file to verify:  .venv/bin/python benchmark/hard/references.py
"""
from __future__ import annotations

import math

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Operator, Statevector

LINEAR_GATES = ["cx", "h", "x", "s", "sdg", "t", "tdg", "rz", "p"]
ADD3_GATES = ["x", "cx", "ccx", "mcx"]


# ----------------------------------------------------------------------------- references

def build_maj5_oracle() -> QuantumCircuit:
    """One flip of q5 per input pattern with >= 3 ones (16 patterns), via X-conjugated 5-control MCX."""
    qc = QuantumCircuit(6, name="ref_maj5")
    for pattern in range(32):
        if bin(pattern).count("1") >= 3:
            zeros = [q for q in range(5) if not (pattern >> q) & 1]
            if zeros:
                qc.x(zeros)
            qc.mcx(list(range(5)), 5)
            if zeros:
                qc.x(zeros)
    return qc


def build_cmul7_mod15() -> QuantumCircuit:
    """Textbook Shor block for a=7 (controlled rotate-left + NOT) followed by a controlled swap of
    |0000> and |1111>, which the textbook block exchanges (it is only specified on 1..14)."""
    qc = QuantumCircuit(5, name="ref_cmul7")
    c = 4
    # textbook: swap(0,1), swap(1,2), swap(2,3) (rotate bits up), x on all -> x -> 7x mod 15 on 1..14
    qc.cswap(c, 0, 1)
    qc.cswap(c, 1, 2)
    qc.cswap(c, 2, 3)
    for q in range(4):
        qc.cx(c, q)
    # the block maps 0 <-> 15; undo that: controlled swap of |0000> and |1111> = flip all four bits
    # iff they are all equal (two controlled-X fans around a 4-control MCX on q0)
    for q in (1, 2, 3):
        qc.cx(0, q)          # q1..q3 now hold q0 XOR qi
    qc.x([1, 2, 3])
    qc.mcx([c, 1, 2, 3], 0)  # flip q0 iff control and all equal
    qc.x([1, 2, 3])
    for q in (1, 2, 3):
        qc.cx(0, q)
    return qc


def build_qpe_t() -> QuantumCircuit:
    """QPE of T on |1>, inverse QFT from Qiskit's library (trusted)."""
    qc = QuantumCircuit(4, name="ref_qpe_t")
    qc.x(3)
    qc.h([0, 1, 2])
    for j in range(3):
        qc.cp(math.pi / 4 * 2**j, j, 3)
    qc.append(QFTGate(3).inverse(), [0, 1, 2])
    return qc


def build_c3x_linear() -> QuantumCircuit:
    qc = QuantumCircuit(4, name="ref_c3x")
    qc.mcx([0, 1, 2], 3)
    return qc


def build_reverse6_nn() -> QuantumCircuit:
    qc = QuantumCircuit(6, name="ref_reverse6")
    qc.swap(0, 5)
    qc.swap(1, 4)
    qc.swap(2, 3)
    return qc


def build_bv22() -> QuantumCircuit:
    qc = QuantumCircuit(6, name="ref_bv22")
    qc.x([1, 2, 4])          # |22> = |0 10110>, ancilla q5 = 0
    return qc


def build_add3() -> QuantumCircuit:
    """b += a (mod 8) as three controlled increments, MSB-first inside each increment."""
    qc = QuantumCircuit(6, name="ref_add3")
    a, b = [0, 1, 2], [3, 4, 5]
    for i in range(3):               # add a_i * 2^i
        for t in range(2, i - 1, -1):
            ctrls = [a[i]] + b[i:t]
            qc.mcx(ctrls, b[t]) if len(ctrls) > 1 else qc.cx(ctrls[0], b[t])
    return qc


# ----------------------------------------------------------------------------- task specs

TASKS = {
    "maj5": {"fn": "build_maj5_oracle", "mode": "unitary", "qubits": 6, "no_black_boxes": True},
    "cmul7": {"fn": "build_cmul7_mod15", "mode": "unitary", "qubits": 5, "no_black_boxes": True},
    "qpe_t": {"fn": "build_qpe_t", "mode": "state", "qubits": 4, "no_black_boxes": True},
    "c3x_linear": {"fn": "build_c3x_linear", "mode": "unitary", "qubits": 4, "no_black_boxes": True,
                   "allowed_gates": LINEAR_GATES, "coupling": "linear"},
    "reverse6_nn": {"fn": "build_reverse6_nn", "mode": "unitary", "qubits": 6, "no_black_boxes": True,
                    "allowed_gates": ["cx"], "coupling": "linear"},
    "bv22": {"fn": "build_bv22", "mode": "state", "qubits": 6, "no_black_boxes": True},
    "add3": {"fn": "build_add3", "mode": "unitary", "qubits": 6, "no_black_boxes": True,
             "allowed_gates": ADD3_GATES},
}


# ----------------------------------------------------------------------------- independent specs

def permutation_matrix(n: int, f) -> np.ndarray:
    P = np.zeros((2**n, 2**n))
    for i in range(2**n):
        P[f(i), i] = 1
    return P


def spec_maj5(i: int) -> int:
    return i ^ ((bin(i & 31).count("1") >= 3) << 5)


def spec_cmul7(i: int) -> int:
    c, x = i >> 4, i & 15
    if c and x < 15:
        x = (7 * x) % 15
    return x | (c << 4)


def spec_c3x(i: int) -> int:
    return i ^ (8 if (i & 7) == 7 else 0)


def spec_reverse6(i: int) -> int:
    return int(format(i, "06b")[::-1], 2)


def spec_add3(i: int) -> int:
    a, b = i & 7, i >> 3
    return a | (((a + b) % 8) << 3)


SPECS = {"maj5": (6, spec_maj5), "cmul7": (5, spec_cmul7), "c3x_linear": (4, spec_c3x),
         "reverse6_nn": (6, spec_reverse6), "add3": (6, spec_add3)}
TARGET_STATE = {"qpe_t": (4, 9), "bv22": (6, 22)}


def expected_unitary(task: str) -> np.ndarray:
    n, f = SPECS[task]
    return permutation_matrix(n, f)


def expected_state(task: str) -> np.ndarray:
    n, idx = TARGET_STATE[task]
    v = np.zeros(2**n, dtype=complex)
    v[idx] = 1
    return v


def equal_up_to_global_phase(U: np.ndarray, V: np.ndarray, tol: float = 1e-9) -> bool:
    k = int(np.argmax(np.abs(V.ravel())))
    ph = U.ravel()[k] / V.ravel()[k]
    return abs(abs(ph) - 1) < tol and np.allclose(U, ph * V, atol=tol)


def verify_references() -> dict[str, str]:
    out = {}
    g = globals()
    for task, (n, _) in SPECS.items():
        U = Operator(g[TASKS[task]["fn"]]()).data
        assert np.allclose(U, expected_unitary(task), atol=1e-9), f"{task} reference != spec permutation"
        out[task] = f"unitary == {2**n}x{2**n} permutation from the exhaustive truth table (exact, incl. phase)"
    # sanity on the specs themselves
    assert sorted(spec_cmul7(i) for i in range(32)) == list(range(32))
    assert [spec_cmul7(16 + x) - 16 for x in (1, 7, 4, 13)] == [7, 4, 13, 1]
    for task, (n, idx) in TARGET_STATE.items():
        sv = Statevector(g[TASKS[task]["fn"]]()).data
        assert equal_up_to_global_phase(sv, expected_state(task)), f"{task} reference != |{idx}>"
        out[task] = f"statevector == |{idx}> (basis index {idx}, up to global phase)"
    return out


if __name__ == "__main__":
    for k, v in verify_references().items():
        print(f"OK  {k:12s} {v}")
