"""Trusted reference implementations for the Veriq week-2 LLM benchmark.

Each reference is independently verified against a mathematical specification in
`verify_references()` (explicit statevectors, the explicit DFT matrix, Qiskit's QFTGate /
CCXGate, and an exhaustive 32-row truth table for the adder). Run this file to verify.

Conventions: Qiskit little-endian (q0 is the least significant bit); no measurements.
"""
from __future__ import annotations

import math

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import CCXGate, DiagonalGate, QFTGate
from qiskit.quantum_info import Operator, Statevector


# ----------------------------------------------------------------------------- references

def build_ghz5() -> QuantumCircuit:
    qc = QuantumCircuit(5, name="ref_ghz5")
    qc.h(0)
    for q in range(1, 5):
        qc.cx(0, q)
    return qc


def build_w3() -> QuantumCircuit:
    qc = QuantumCircuit(3, name="ref_w3")
    qc.ry(2 * math.asin(1 / math.sqrt(3)), 2)   # q2 = 1 with prob 1/3
    qc.x(2)
    qc.ch(2, 1)                                  # if q2 = 0: q1 -> |+>
    qc.x(2)
    qc.x(0)                                      # q0 = NOT(q1 OR q2) (never both 1)
    qc.cx(1, 0)
    qc.cx(2, 0)
    return qc


def _qft_textbook(n: int) -> QuantumCircuit:
    qc = QuantumCircuit(n)
    for j in range(n - 1, -1, -1):
        qc.h(j)
        for k in range(j - 1, -1, -1):
            qc.cp(math.pi / 2 ** (j - k), k, j)
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc


def build_qft4() -> QuantumCircuit:
    qc = _qft_textbook(4)
    qc.name = "ref_qft4"
    return qc


def build_iqft3() -> QuantumCircuit:
    qc = _qft_textbook(3).inverse()
    qc.name = "ref_iqft3"
    return qc


def build_grover3() -> QuantumCircuit:
    qc = QuantumCircuit(3, name="ref_grover3")
    qc.h(range(3))
    oracle = [1.0] * 8
    oracle[0b101] = -1.0
    diffuse = [-1.0] * 8          # 2|0><0| - I in the H basis
    diffuse[0] = 1.0
    for _ in range(2):
        qc.append(DiagonalGate(oracle), range(3))
        qc.h(range(3))
        qc.append(DiagonalGate(diffuse), range(3))
        qc.h(range(3))
    return qc


def build_toffoli() -> QuantumCircuit:
    """Nielsen & Chuang Fig. 4.9: only h, t, tdg, cx."""
    qc = QuantumCircuit(3, name="ref_toffoli")
    qc.h(2)
    qc.cx(1, 2); qc.tdg(2)
    qc.cx(0, 2); qc.t(2)
    qc.cx(1, 2); qc.tdg(2)
    qc.cx(0, 2); qc.t(1); qc.t(2)
    qc.h(2)
    qc.cx(0, 1); qc.t(0); qc.tdg(1)
    qc.cx(0, 1)
    return qc


def build_adder2() -> QuantumCircuit:
    """carry = a1 b1 XOR a1 a0 b0 XOR b1 a0 b0 (computed from the original bits), then the sum."""
    qc = QuantumCircuit(5, name="ref_adder2")
    qc.ccx(1, 3, 4)
    qc.mcx([0, 1, 2], 4)
    qc.mcx([0, 2, 3], 4)
    qc.ccx(0, 2, 3)   # b1 ^= a0 b0
    qc.cx(1, 3)       # b1 ^= a1
    qc.cx(0, 2)       # b0 ^= a0
    return qc


# ----------------------------------------------------------------------------- task specs

TASKS = {
    # mode "state": compare prepared states from |0...0> up to global phase
    # mode "unitary": compare full unitaries up to global phase
    "ghz5": {"fn": "build_ghz5", "mode": "state", "qubits": 5},
    "w3": {"fn": "build_w3", "mode": "state", "qubits": 3},
    "qft4": {"fn": "build_qft4", "mode": "unitary", "qubits": 4},
    "iqft3": {"fn": "build_iqft3", "mode": "unitary", "qubits": 3},
    "grover3": {"fn": "build_grover3", "mode": "state", "qubits": 3},
    "toffoli": {"fn": "build_toffoli", "mode": "unitary", "qubits": 3,
                "allowed_gates": ["h", "t", "tdg", "s", "sdg", "cx"]},
    "adder2": {"fn": "build_adder2", "mode": "unitary", "qubits": 5},
}


# ----------------------------------------------------------------------------- independent verification

def _basis(n: int, idx: int) -> np.ndarray:
    v = np.zeros(2**n, dtype=complex)
    v[idx] = 1
    return v


def _same_up_to_phase(a: np.ndarray, b: np.ndarray, tol: float = 1e-9) -> bool:
    return abs(abs(np.vdot(a, b)) - np.linalg.norm(a) * np.linalg.norm(b)) < tol


def expected_ghz5() -> np.ndarray:
    return (_basis(5, 0) + _basis(5, 31)) / math.sqrt(2)


def expected_w3() -> np.ndarray:
    return (_basis(3, 0b001) + _basis(3, 0b010) + _basis(3, 0b100)) / math.sqrt(3)


def dft_matrix(n: int) -> np.ndarray:
    N = 2**n
    return np.array([[np.exp(2j * np.pi * x * k / N) for x in range(N)] for k in range(N)]) / math.sqrt(N)


def expected_grover3() -> np.ndarray:
    """Plain numpy: (D O)^2 H^3 |000> with O = I - 2|101><101|, D = 2|s><s| - I."""
    N = 8
    s = np.ones(N) / math.sqrt(N)
    O = np.eye(N); O[5, 5] = -1
    D = 2 * np.outer(s, s) - np.eye(N)
    return (D @ O) @ (D @ O) @ s


def adder_truth_table() -> dict[int, int]:
    """input index -> output index, bits (q4..q0) = (c, b1, b0, a1, a0)."""
    table = {}
    for idx in range(32):
        a = idx & 0b11
        b = (idx >> 2) & 0b11
        c = (idx >> 4) & 1
        s = a + b
        out = a | ((s % 4) << 2) | ((c ^ (s >> 2)) << 4)
        table[idx] = out
    return table


def verify_references() -> dict[str, str]:
    out = {}
    sv = Statevector(build_ghz5()).data
    assert _same_up_to_phase(sv, expected_ghz5()); out["ghz5"] = "statevector == (|00000>+|11111>)/sqrt2"

    sv = Statevector(build_w3()).data
    assert _same_up_to_phase(sv, expected_w3()); out["w3"] = "statevector == (|001>+|010>+|100>)/sqrt3"

    U = Operator(build_qft4()).data
    assert np.allclose(U, dft_matrix(4), atol=1e-9), "qft4 != DFT (exact, incl. phase)"
    qg = QuantumCircuit(4); qg.append(QFTGate(4), range(4))
    assert np.allclose(Operator(qg).data, dft_matrix(4), atol=1e-9), "QFTGate convention differs"
    out["qft4"] = "unitary == explicit DFT matrix e^{2pi i xk/16}/4 (exact) == QFTGate(4)"

    U = Operator(build_iqft3()).data
    assert np.allclose(U, dft_matrix(3).conj().T, atol=1e-9)
    qg = QuantumCircuit(3); qg.append(QFTGate(3).inverse(), range(3))
    assert np.allclose(Operator(qg).data, U, atol=1e-9)
    out["iqft3"] = "unitary == DFT(8)^dagger (exact) == QFTGate(3).inverse()"

    sv = Statevector(build_grover3()).data
    exp = expected_grover3()
    assert _same_up_to_phase(sv, exp)
    out["grover3"] = f"statevector == numpy (DO)^2 H|000>, P(|101>) = {abs(exp[5])**2:.6f}"

    tq = QuantumCircuit(3); tq.append(CCXGate(), [0, 1, 2])
    assert np.allclose(Operator(build_toffoli()).data, Operator(tq).data, atol=1e-9)
    assert set(build_toffoli().count_ops()) <= set(TASKS["toffoli"]["allowed_gates"])
    out["toffoli"] = "unitary == CCXGate (exact, incl. global phase); gates within {h,t,tdg,s,sdg,cx}"

    U = Operator(build_adder2()).data
    P = np.zeros((32, 32))
    for i, o in adder_truth_table().items():
        P[o, i] = 1
    assert np.allclose(U, P, atol=1e-9)
    out["adder2"] = "unitary == 32x32 permutation from exhaustive truth table (a, (a+b) mod 4, c XOR carry)"
    return out


if __name__ == "__main__":
    for k, v in verify_references().items():
        print(f"OK  {k:8s} {v}")
