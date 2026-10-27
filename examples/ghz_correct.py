"""3-qubit GHZ state (|000> + |111>)/sqrt(2). Correct."""
from qiskit import QuantumCircuit


def build(n: int = 3) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"ghz{n}")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    qc.measure_all()
    return qc
