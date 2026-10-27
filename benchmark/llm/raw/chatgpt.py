# ChatGPT (Think, Free plan)
from qiskit import QuantumCircuit


PI = 3.141592653589793


def build_ghz5():
    """Prepare (|00000> + |11111>) / sqrt(2)."""
    qc = QuantumCircuit(5)

    qc.h(0)
    for qubit in range(1, 5):
        qc.cx(0, qubit)

    return qc


def build_w3():
    """Prepare (|001> + |010> + |100>) / sqrt(3), with q0 as LSB."""
    qc = QuantumCircuit(3)

    # Separate the q2=1 component, with amplitude 1/sqrt(3).
    qc.ry(1.2309594173407747, 2)

    # When the original q2 is zero, prepare the W state on q1 and q0.
    # X on q2 turns the zero-control condition into a positive control.
    qc.x(2)
    qc.cx(2, 0)
    qc.cry(PI / 2, 2, 1)
    qc.ccx(2, 1, 0)
    qc.x(2)

    return qc


def build_qft4():
    """Prepare the standard four-qubit QFT, including final reversal swaps."""
    qc = QuantumCircuit(4)

    # Process the most significant qubit first.
    # Qiskit's qubit 0 is the least significant bit.
    for i in range(3, -1, -1):
        qc.h(i)
        for j in range(i - 1, -1, -1):
            qc.cp(PI / (2 ** (i - j)), i, j)

    # Reverse the qubit order to obtain the standard QFT output.
    qc.swap(0, 3)
    qc.swap(1, 2)

    return qc


def build_iqft3():
    """Prepare the inverse three-qubit QFT, including reversal swaps."""
    qc = QuantumCircuit(3)

    # Swaps are self-inverse and occur first in the inverse circuit.
    qc.swap(0, 2)

    # Apply inverse controlled-phase gates in reverse circuit order.
    for i in range(3):
        for j in range(i):
            qc.cp(-PI / (2 ** (i - j)), i, j)
        qc.h(i)

    return qc


def build_grover3():
    """Start from |000> and perform exactly two Grover iterations for |101>."""
    qc = QuantumCircuit(3)

    # Prepare the uniform superposition.
    for qubit in range(3):
        qc.h(qubit)

    for _ in range(2):
        # Oracle: phase-flip |101> (q0=1, q1=0, q2=1).
        qc.x(1)
        qc.h(2)
        qc.ccx(0, 1, 2)
        qc.h(2)
        qc.x(1)

        # Diffusion operator, up to its conventional global phase.
        for qubit in range(3):
            qc.h(qubit)
            qc.x(qubit)

        qc.h(2)
        qc.ccx(0, 1, 2)
        qc.h(2)

        for qubit in range(3):
            qc.x(qubit)
            qc.h(qubit)

    return qc


def build_toffoli():
    """Implement CCX(q0, q1, q2) using only H, T, Tdg, and CX gates."""
    qc = QuantumCircuit(3)

    # H(target) * CCZ(controls, target) * H(target).
    qc.h(2)

    # CCZ phase polynomial:
    # 4*a*b*c = a + b + c
    #            - (a XOR b) - (a XOR c) - (b XOR c)
    #            + (a XOR b XOR c).
    # T and Tdg implement the corresponding +/- pi/4 phases.

    # Individual-bit phases.
    qc.t(0)
    qc.t(1)
    qc.t(2)

    # - (a XOR b).
    qc.cx(0, 1)
    qc.tdg(1)
    qc.cx(0, 1)

    # - (a XOR c).
    qc.cx(0, 2)
    qc.tdg(2)
    qc.cx(0, 2)

    # - (b XOR c).
    qc.cx(1, 2)
    qc.tdg(2)
    qc.cx(1, 2)

    # + (a XOR b XOR c).
    qc.cx(0, 2)
    qc.cx(1, 2)
    qc.t(2)
    qc.cx(1, 2)
    qc.cx(0, 2)

    qc.h(2)

    return qc


def build_adder2():
    """
    Add two 2-bit registers modulo 4.

    a = q0 + 2*q1
    b = q2 + 2*q3

    Output:
        a unchanged
        b = (a + b) mod 4
        q4 = q4 XOR carry_out(a + b)

    No ancilla qubits are used.
    """
    qc = QuantumCircuit(5)

    # Compute carry_out into q4 using the ORIGINAL a and b bits.
    #
    # carry_out = (a1 AND b1)
    #             XOR (a1 AND a0 AND b0)
    #             XOR (b1 AND a0 AND b0).
    qc.ccx(1, 3, 4)
    qc.ccx(1, 0, 2, 4)
    qc.ccx(3, 0, 2, 4)

    # Add the least significant bits:
    # b0 <- b0 XOR a0.
    # The carry into bit 1 is a0 AND b0, using the original b0.
    qc.ccx(0, 2, 3)

    # Add the most significant bits, including the carry into bit 1.
    qc.cx(1, 3)

    # Finish updating the least significant bit.
    qc.cx(0, 2)

    return qc
