from itertools import combinations
from math import pi

from qiskit import QuantumCircuit

# Qiskit 2.x standard-gate API reference: [3]


def build_maj5_oracle():
    """Toggle q5 iff at least three of q0,...,q4 are one."""
    qc = QuantumCircuit(6)

    # Over GF(2), MAJ5 is the XOR of all degree-3 and degree-4
    # square-free monomials.
    for degree in (3, 4):
        for controls in combinations(range(5), degree):
            qc.mcx(list(controls), 5)

    return qc


def build_cmul7_mod15():
    """Controlled multiplication by 7 modulo 15, with 15 fixed."""
    qc = QuantumCircuit(5)
    permutation = [(7 * x) % 15 for x in range(15)] + [15]
    visited = set()

    for start in range(16):
        if start in visited:
            continue

        cycle = []
        current = start
        while current not in visited:
            visited.add(current)
            cycle.append(current)
            current = permutation[current]

        # Chronological swaps (c0,c1), (c0,c2), ... implement this cycle.
        for endpoint in cycle[1:]:
            first = cycle[0]

            # A Gray path connects the two computational basis states.
            path = [first]
            current = first
            for bit in range(4):
                if ((first ^ endpoint) >> bit) & 1:
                    current ^= 1 << bit
                    path.append(current)

            edges = list(zip(path[:-1], path[1:]))
            # Swap path endpoints while restoring every intermediate state.
            for left, right in edges + edges[-2::-1]:
                target = (left ^ right).bit_length() - 1
                other_bits = [bit for bit in range(4) if bit != target]
                zero_controls = [
                    bit for bit in other_bits if not ((left >> bit) & 1)
                ]

                for bit in zero_controls:
                    qc.x(bit)

                qc.mcx([4] + other_bits, target)

                for bit in reversed(zero_controls):
                    qc.x(bit)

    return qc


def build_qpe_t():
    """Three-bit QPE of T on |1>, yielding counting integer 1."""
    qc = QuantumCircuit(4)
    qc.x(3)

    for bit in range(3):
        qc.h(bit)

    # Counting bit j controls T^(2^j).
    for bit in range(3):
        qc.cp((pi / 4) * (1 << bit), bit, 3)

    # Explicit inverse QFT, including the bit-order reversal.
    qc.cx(0, 2)
    qc.cx(2, 0)
    qc.cx(0, 2)

    for target in range(3):
        for control in range(target):
            qc.cp(-pi / (1 << (target - control)), control, target)
        qc.h(target)

    return qc


def build_c3x_linear():
    """Exact C3X using only H, P, and nearest-neighbor CX gates."""
    qc = QuantumCircuit(4)
    qc.h(3)

    # 8*x0*x1*x2*x3 =
    # sum_{nonempty S} (-1)^(|S|-1) XOR_{j in S}(xj).
    # Thus parity phases of +/-pi/8 implement an exact CCCZ.
    for size in range(1, 5):
        angle = (pi / 8) * (-1 if size % 2 == 0 else 1)

        for subset in combinations(range(4), size):
            target = subset[-1]
            controls = list(subset[:-1])

            for stage in range(2):
                if stage == 1:
                    qc.p(angle, target)

                ordered_controls = (
                    controls if stage == 0 else list(reversed(controls))
                )

                for control in ordered_controls:
                    # This four-sweep nearest-neighbor network implements
                    # CX(control, target), restoring intermediate qubits.
                    for bit in range(control, target):
                        qc.cx(bit, bit + 1)
                    for bit in range(target - 2, control - 1, -1):
                        qc.cx(bit, bit + 1)
                    for bit in range(control + 1, target):
                        qc.cx(bit, bit + 1)
                    for bit in range(target - 2, control, -1):
                        qc.cx(bit, bit + 1)

    qc.h(3)
    return qc


def build_reverse6_nn():
    """Reverse six qubits using adjacent CX gates only."""
    qc = QuantumCircuit(6)

    # Adjacent swaps successively move each remaining leftmost wire
    # to the right end of the remaining interval.
    for end in range(5, 0, -1):
        for left in range(end):
            qc.cx(left, left + 1)
            qc.cx(left + 1, left)
            qc.cx(left, left + 1)

    return qc


def build_bv22():
    """Bernstein–Vazirani for secret 22, with ancilla returned to |0>."""
    qc = QuantumCircuit(6)

    qc.x(5)
    qc.h(5)
    for bit in range(5):
        qc.h(bit)

    for bit in range(5):
        if (22 >> bit) & 1:
            qc.cx(bit, 5)

    for bit in range(5):
        qc.h(bit)

    qc.h(5)
    qc.x(5)
    return qc


def build_add3():
    """Map (a,b) to (a,(a+b) mod 8), without ancillary qubits."""
    qc = QuantumCircuit(6)

    # Add each controlled power of two. Descending target order
    # makes every carry depend on the pre-increment lower bits.
    for bit in range(3):
        for target_bit in range(2, bit, -1):
            controls = [bit] + [
                3 + lower_bit for lower_bit in range(bit, target_bit)
            ]
            target = 3 + target_bit

            if len(controls) == 2:
                qc.ccx(controls[0], controls[1], target)
            else:
                qc.mcx(controls, target)

        qc.cx(bit, 3 + bit)

    return qc
