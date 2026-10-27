"""Trusted reference: Qiskit's library QFTGate on 4 qubits."""
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate

circuit = QuantumCircuit(4, name="qft4_reference")
circuit.append(QFTGate(4), range(4))
