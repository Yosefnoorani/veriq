from qiskit import QuantumCircuit

# Qiskit 2.x gate API: [8]
# Only Qiskit is imported; numerical constants avoid other dependencies.
_PI = 3.141592653589793
_W_THETA = 1.9106332362490186  # 2 * acos(1 / sqrt(3))


def build_ghz5():
    """Prepare (|00000> + |11111>) / sqrt(2)."""
    qc = QuantumCircuit(5)
    qc.h(0)
    for target in range(1, 5):
        qc.cx(0, target)
    return qc


def build_w3():
    """Prepare (|001> + |010> + |100>) / sqrt(3)."""
    qc = QuantumCircuit(3)

    # Prepare sqrt(1/3)|000> + sqrt(2/3)|100>.
    qc.ry(_W_THETA, 2)

    # Controlled-RY(pi/2), decomposed into RY and CX gates.
    qc.ry(_PI / 4, 1)
    qc.cx(2, 1)
    qc.ry(-_PI / 4, 1)
    qc.cx(2, 1)

    # Convert |110> to |010>, leaving |100> unchanged.
    qc.cx(1, 2)

    # Convert the remaining |000> branch to |001>.
    qc.x(0)
    qc.cx(1, 0)
    qc.cx(2, 0)
    return qc


def build_qft4():
    """Implement the positive-exponent, little-endian QFT on four qubits."""
    qc = QuantumCircuit(4)

    for target in range(3, -1, -1):
        qc.h(target)
        for control in range(target - 1, -1, -1):
            qc.cp(_PI / (2 ** (target - control)), control, target)

    qc.swap(0, 3)
    qc.swap(1, 2)
    return qc


def build_iqft3():
    """Implement the inverse of the positive-exponent QFT on three qubits."""
    qc = QuantumCircuit(3)

    # Reverse the final swaps of the forward QFT first.
    qc.swap(0, 2)

    # Reverse gate order and negate every controlled-phase angle.
    for target in range(3):
        for control in range(target):
            qc.cp(-_PI / (2 ** (target - control)), control, target)
        qc.h(target)
    return qc


def build_grover3():
    """Apply uniform preparation and exactly two iterations marking |101>."""
    qc = QuantumCircuit(3)
    for qubit in range(3):
        qc.h(qubit)

    for _ in range(2):
        # Oracle: negate precisely |q2 q1 q0> = |101>.
        qc.x(1)
        qc.h(2)
        qc.ccx(0, 1, 2)
        qc.h(2)
        qc.x(1)

        # Diffusion: H^3 (2|000><000| - I) H^3.
        for qubit in range(3):
            qc.h(qubit)
            qc.x(qubit)

        qc.h(2)
        qc.ccx(0, 1, 2)
        qc.h(2)

        for qubit in range(3):
            qc.x(qubit)
            qc.h(qubit)

        # X^3 CCZ X^3 gives I - 2|000><000|; negate it.
        qc.global_phase += _PI

    return qc


def build_toffoli():
    """Exact CCX with controls q0, q1 and target q2, using H/T/TDG/CX."""
    qc = QuantumCircuit(3)

    qc.h(2)
    qc.cx(1, 2)
    qc.tdg(2)
    qc.cx(0, 2)
    qc.t(2)
    qc.cx(1, 2)
    qc.tdg(2)
    qc.cx(0, 2)
    qc.t(1)
    qc.t(2)
    qc.h(2)
    qc.cx(0, 1)
    qc.t(0)
    qc.tdg(1)
    qc.cx(0, 1)
    return qc


def build_adder2():
    """Map (a, b, c) to (a, (a+b) mod 4, c XOR carry_out(a+b))."""
    qc = QuantumCircuit(5)

    # Add 2*a1 to b, recording overflow in the arbitrary-input carry bit.
    qc.ccx(1, 3, 4)
    qc.cx(1, 3)

    # Add a0 to b. First toggle carry iff a0 AND b0 AND current_b1.
    # This four-CCX construction uses q1 as a borrowed, restored qubit.
    qc.ccx(0, 2, 1)
    qc.ccx(1, 3, 4)
    qc.ccx(0, 2, 1)
    qc.ccx(1, 3, 4)

    # Propagate the low-bit carry, then update the low sum bit.
    qc.ccx(0, 2, 3)
    qc.cx(0, 2)
    return qc
