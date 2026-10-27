"""The source block: a 3-controlled X on a 5-qubit register (q4 is not touched).

This is the smallest shape that triggers the hazard: an MCX with >= 3 controls and at
least one qubit the block leaves idle. Veriq CLI convention: exposes `build()`.
"""
from qiskit import QuantumCircuit

N = 5
CONTROLS = [0, 1, 2]
TARGET = 3


def build() -> QuantumCircuit:
    qc = QuantumCircuit(N, name="c3x_block")
    qc.mcx(CONTROLS, TARGET)
    return qc
