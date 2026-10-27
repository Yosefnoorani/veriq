"""3-qubit GHZ as an LLM might write it -- with a subtle bug.

The last CNOT has control and target swapped (cx(2, 1) instead of cx(1, 2)).
Because qubit 2 is still |0>, that gate does nothing and the state becomes
(|000> + |011>)/sqrt(2) instead of GHZ.
"""
from qiskit import QuantumCircuit


def build() -> QuantumCircuit:
    qc = QuantumCircuit(3, name="ghz3_buggy")
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(2, 1)  # BUG: should be cx(1, 2)
    qc.measure_all()
    return qc
