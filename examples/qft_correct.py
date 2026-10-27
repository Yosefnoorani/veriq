"""Hand-written 4-qubit QFT (textbook construction). Correct."""
from math import pi

from qiskit import QuantumCircuit


def build(n: int = 4) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"qft{n}")
    for j in reversed(range(n)):
        qc.h(j)
        for k in reversed(range(j)):
            qc.cp(pi / 2 ** (j - k), k, j)
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc
