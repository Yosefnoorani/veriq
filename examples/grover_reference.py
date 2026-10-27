"""Reference Grover oracle for |101> built from a diagonal phase oracle."""
from qiskit import QuantumCircuit
from qiskit.circuit.library import Diagonal

from _grover import grover3


def oracle_101_diag(qc: QuantumCircuit):
    diag = [1] * 8
    diag[0b101] = -1
    qc.append(Diagonal(diag), range(3))


def build():
    return grover3(oracle_101_diag, name="grover3_reference")
