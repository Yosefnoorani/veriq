"""3-qubit Grover search for the marked state |101> (Qiskit bit order), 2 iterations.

Ideal success probability: sin^2(5*asin(1/sqrt(8))) = 0.9453125. Correct.
"""
from _grover import ccz, grover3


def oracle_101(qc):
    qc.x(1)  # flip the 0-bit so CCZ fires on |101>
    ccz(qc)
    qc.x(1)


def build():
    return grover3(oracle_101, name="grover3_101")
