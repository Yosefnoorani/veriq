from qiskit import QuantumCircuit




def build_maj5_oracle():
    """Toggle q5 iff at least three of q0..q4 are 1."""
    qc = QuantumCircuit(6)


    # The ANF of MAJ5 contains every degree-3 and degree-4 monomial.
    # Each monomial is implemented as a multi-controlled X on q5.
    for mask in range(1 << 5):
        controls = [q for q in range(5) if mask & (1 << q)]
        if len(controls) in (3, 4):
            qc.mcx(controls, 5)


    return qc




def build_cmul7_mod15():
    """Controlled multiplication by 7 modulo 15; q4 is the control."""
    qc = QuantumCircuit(5)


    # Cycles of x -> 7*x mod 15, with x=15 fixed.
    cycles = (
        (1, 7, 4, 13),
        (2, 14, 8, 11),
        (3, 6, 12, 9),
    )


    # Convert each cycle into transpositions, then each transposition
    # into swaps of neighboring vertices in the 4-dimensional Boolean cube.
    primitive_swaps = []


    for cycle in cycles:
        for index in range(1, len(cycle)):
            u = cycle[0]
            v = cycle[index]


            path = [u]
            current = u


            # Construct a Gray-code path from u to v.
            for bit in range(4):
                if ((u ^ v) >> bit) & 1:
                    current ^= 1 << bit
                    path.append(current)


            # The forward path followed by the reverse path excluding
            # its last edge implements exactly the transposition (u v).
            for edge in range(len(path) - 1):
                primitive_swaps.append((path[edge], path[edge + 1]))


            for edge in range(len(path) - 3, -1, -1):
                primitive_swaps.append((path[edge], path[edge + 1]))


    # Swap two basis states that differ in one work bit.
    # q4 controls the swap, and the other three work bits select the pair.
    for u, v in primitive_swaps:
        target = (u ^ v).bit_length() - 1


        controls = [4] + [
            bit for bit in range(4) if bit != target
        ]


        # Turn zero-valued work controls into positive controls.
        zero_controls = [
            bit
            for bit in range(4)
            if bit != target and ((u >> bit) & 1) == 0
        ]


        for bit in zero_controls:
            qc.x(bit)


        qc.mcx(controls, target)


        for bit in reversed(zero_controls):
            qc.x(bit)


    return qc




def build_qpe_t():
    """Three-bit QPE for T, with counting qubits q0..q2 and eigenstate q3."""
    qc = QuantumCircuit(4)
    pi = 3.141592653589793


    # Prepare the eigenstate |1> of T.
    qc.x(3)


    # Prepare the counting register.
    for q in range(3):
        qc.h(q)


    # Controlled-T, controlled-T^2, and controlled-T^4.
    qc.cp(pi / 4, 0, 3)
    qc.cp(pi / 2, 1, 3)
    qc.cp(pi, 2, 3)


    # Inverse QFT for little-endian counting qubits.
    # This is the inverse of a QFT built from H and controlled-phase gates,
    # with the bit-reversal swaps performed at the end.
    for j in range(2, -1, -1):
        for k in range(2, j, -1):
            qc.cp(-pi / (2 ** (k - j)), k, j)
        qc.h(j)


    # Swap q0 and q2 using CX gates.
    qc.cx(0, 2)
    qc.cx(2, 0)
    qc.cx(0, 2)


    return qc




def build_c3x_linear():
    """Exact C3X: controls q0,q1,q2; target q3; nearest-neighbor CX only."""
    qc = QuantumCircuit(4)
    pi = 3.141592653589793


    # H(target) * C3Z * H(target) = C3X.
    # Implement C3Z as an exact phase polynomial:
    # x0*x1*x2*x3 = (1/8) *
    #   sum_{nonempty S} (-1)^(|S|-1) parity(S).
    qc.h(3)


    for mask in range(1, 1 << 4):
        indices = [q for q in range(4) if mask & (1 << q)]
        target = indices[-1]
        controls = indices[:-1]


        # Compute the parity of the selected subset into its highest qubit.
        # Each remote CX is synthesized with adjacent CX gates by temporarily
        # swapping the control value along the line and then restoring it.
        for control in controls:
            for k in range(control, target - 1):
                qc.cx(k, k + 1)
                qc.cx(k + 1, k)
                qc.cx(k, k + 1)


            qc.cx(target - 1, target)


            for k in range(target - 2, control - 1, -1):
                qc.cx(k, k + 1)
                qc.cx(k + 1, k)
                qc.cx(k, k + 1)


        angle = pi / 8 if len(indices) % 2 == 1 else -pi / 8
        qc.p(angle, target)


        # Uncompute the parity, reversing the remote-CX operations.
        for control in reversed(controls):
            for k in range(control, target - 1):
                qc.cx(k, k + 1)
                qc.cx(k + 1, k)
                qc.cx(k, k + 1)


            qc.cx(target - 1, target)


            for k in range(target - 2, control - 1, -1):
                qc.cx(k, k + 1)
                qc.cx(k + 1, k)
                qc.cx(k, k + 1)


    qc.h(3)


    return qc




def build_reverse6_nn():
    """Reverse the order of six qubits using adjacent CX gates only."""
    qc = QuantumCircuit(6)


    # Each adjacent SWAP is three CX gates.
    # This sequence of 15 adjacent swaps reverses the six wire values.
    for end in range(5, 0, -1):
        for left in range(end):
            qc.cx(left, left + 1)
            qc.cx(left + 1, left)
            qc.cx(left, left + 1)


    return qc




def build_bv22():
    """Bernstein-Vazirani for secret 22; return the ancilla to |0>."""
    qc = QuantumCircuit(6)


    # Prepare the phase-kickback ancilla in |- > and the input in |+>^5.
    qc.x(5)
    for q in range(6):
        qc.h(q)


    # 22 = 10110 in q4..q0 order, so q1, q2, and q4 are selected.
    for q in (1, 2, 4):
        qc.cx(q, 5)


    # Decode the secret into the input register.
    for q in range(5):
        qc.h(q)


    # Convert the ancilla |- > to |0>.
    qc.h(5)
    qc.x(5)


    return qc




def build_add3():
    """Add a=q0..q2 into b=q3..q5 modulo 8, preserving a."""
    qc = QuantumCircuit(6)


    # Controlled increment of b by 1 when a0=q0 is 1.
    # Apply carries from most significant to least significant, using
    # the original lower bits for the carry conditions.
    qc.mcx([0, 3, 4], 5)
    qc.ccx(0, 3, 4)
    qc.cx(0, 3)


    # Controlled increment of b by 2 when a1=q1 is 1.
    qc.ccx(1, 4, 5)
    qc.cx(1, 4)


    # Controlled increment of b by 4 when a2=q2 is 1.
    qc.cx(2, 5)


    return qc
