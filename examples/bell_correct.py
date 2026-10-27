"""Bell state (|00> + |11>)/sqrt(2). Correct."""
from qiskit import QuantumCircuit

circuit = QuantumCircuit(2, name="bell")
circuit.h(0)
circuit.cx(0, 1)
circuit.measure_all()
