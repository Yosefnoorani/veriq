"""3-qubit Grover for |101> with a buggy oracle.

The LLM forgot to un-compute the X on qubit 1 after the phase flip, so the
oracle is not self-inverse and the amplitude amplification goes to the wrong
state.
"""
from _grover import ccz, grover3


def oracle_101_buggy(qc):
    qc.x(1)
    ccz(qc)
    # BUG: missing qc.x(1)


def build():
    return grover3(oracle_101_buggy, name="grover3_101_buggy")
