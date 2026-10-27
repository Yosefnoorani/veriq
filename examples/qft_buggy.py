"""Hand-written 4-qubit QFT with a subtle off-by-one in the rotation angle.

`pi / 2 ** (j - k + 1)` instead of `pi / 2 ** (j - k)`: every controlled-phase is
halved. On |0000> the output is still the uniform superposition, so naive
"run it and look at the histogram" testing passes -- only an equivalence proof
(or the right input state) exposes it.
"""
from math import pi

from qiskit import QuantumCircuit


def build(n: int = 4) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"qft{n}_buggy")
    for j in reversed(range(n)):
        qc.h(j)
        for k in reversed(range(j)):
            qc.cp(pi / 2 ** (j - k + 1), k, j)  # BUG: exponent off by one
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc
