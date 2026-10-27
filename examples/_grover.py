"""Shared 3-qubit Grover construction (helper, not an example itself)."""
from qiskit import QuantumCircuit


def ccz(qc: QuantumCircuit) -> None:
    qc.h(2)
    qc.ccx(0, 1, 2)
    qc.h(2)


def grover3(oracle, iterations: int = 2, name: str = "grover3") -> QuantumCircuit:
    qc = QuantumCircuit(3, name=name)
    qc.h(range(3))
    for _ in range(iterations):
        oracle(qc)
        # diffuser: 2|s><s| - I
        qc.h(range(3))
        qc.x(range(3))
        ccz(qc)
        qc.x(range(3))
        qc.h(range(3))
    qc.measure_all()
    return qc
