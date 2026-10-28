import math
import itertools
from qiskit import QuantumCircuit

def build_maj5_oracle():
    """
    6 qubits. q5 ^= MAJ(q0..q4).
    Uses the Algebraic Normal Form (ANF) of the 5-bit majority function.
    MAJ5 is the XOR sum of all 3-bit ANDs and all 4-bit ANDs.
    """
    qc = QuantumCircuit(6)
    
    # Add all combinations of size 3
    for comb in itertools.combinations(range(5), 3):
        qc.mcx(list(comb), 5)
        
    # Add all combinations of size 4
    for comb in itertools.combinations(range(5), 4):
        qc.mcx(list(comb), 5)
        
    return qc

def build_cmul7_mod15():
    """
    5 qubits. Control q4. Work x = q0..q3.
    Maps x -> 7x mod 15 for x < 15, and 15 -> 15.
    7x mod 15 is equivalent to a cyclic right shift by 1, followed by a bitwise NOT,
    except the all-zeros (0) and all-ones (15) states map to themselves.
    """
    qc = QuantumCircuit(5)
    
    # 1. Controlled cyclic right shift (q0->q3, q1->q0, q2->q1, q3->q2)
    qc.cswap(4, 0, 1)
    qc.cswap(4, 1, 2)
    qc.cswap(4, 2, 3)

    # 2. Controlled bitwise NOT
    for i in range(4):
        qc.cx(4, i)

    # 3. Controlled swap of state |0000> and |1111> to fix the edge cases
    # We do this by flipping q0 iff q0=q1=q2=q3 and the control q4 is 1.
    
    # Compute parity differences into q1, q2, q3
    qc.cx(0, 1)
    qc.cx(0, 2)
    qc.cx(0, 3)

    # If q1=q2=q3=0, all original bits were equal. Apply MCX conditionally.
    qc.x(1)
    qc.x(2)
    qc.x(3)
    qc.mcx([4, 1, 2, 3], 0)
    qc.x(1)
    qc.x(2)
    qc.x(3)

    # Undo parity differences
    qc.cx(0, 3)
    qc.cx(0, 2)
    qc.cx(0, 1)
    
    return qc

def build_qpe_t():
    """
    4 qubits. QPE of the T gate.
    """
    qc = QuantumCircuit(4)
    
    # Prepare the eigenstate |1>
    qc.x(3) 
    
    # Create superposition for counting register
    qc.h([0, 1, 2])

    # Controlled-T^(2^k) operations
    qc.cp(math.pi / 4, 0, 3)  # T
    qc.cp(math.pi / 2, 1, 3)  # S
    qc.cp(math.pi, 2, 3)      # Z

    # Inverse QFT on the counting register
    qc.swap(0, 2)
    qc.h(0)
    qc.cp(-math.pi / 2, 0, 1)
    qc.h(1)
    qc.cp(-math.pi / 4, 0, 2)
    qc.cp(-math.pi / 2, 1, 2)
    qc.h(2)
    
    return qc

def build_c3x_linear():
    """
    4 qubits. Exact 3-controlled X with target q3, using only linearly connected CX gates.
    Implemented by synthesizing C3Z using a phase polynomial network of parities,
    wrapped in H gates on the target.
    """
    qc = QuantumCircuit(4)
    qc.h(3) # Convert C3Z to C3X

    def adj_cx(a, b):
        """Helper to perform CX(a, b) using only adjacent CX gates via SWAP networks."""
        if a == b: return
        step = 1 if a < b else -1
        path = list(range(a, b, step))
        # Swap 'a' next to 'b'
        for i in range(len(path)-1):
            qc.cx(path[i], path[i+1])
            qc.cx(path[i+1], path[i])
            qc.cx(path[i], path[i+1])
        # Apply the adjacent CX
        qc.cx(b-step, b)
        # Swap 'a' back to its original position
        for i in range(len(path)-2, -1, -1):
            qc.cx(path[i], path[i+1])
            qc.cx(path[i+1], path[i])
            qc.cx(path[i], path[i+1])

    # Iterate over all 15 non-empty subsets of the 4 qubits
    for i in range(1, 16):
        S = [j for j in range(4) if (i & (1 << j))]
        t = max(S)
        controls = [c for c in S if c != t]
        
        # Compute parity into t
        for c in controls:
            adj_cx(c, t)
            
        # Apply Rz based on the weight of the parity to match C3Z eigenvalues
        angle = math.pi / 8 if len(S) % 2 != 0 else -math.pi / 8
        qc.rz(angle, t)
        
        # Uncompute parity
        for c in reversed(controls):
            adj_cx(c, t)

    qc.h(3)
    return qc

def build_reverse6_nn():
    """
    6 qubits. Reverses the order of qubits using only adjacent CX gates.
    """
    qc = QuantumCircuit(6)
    
    # Bubble sort style swap network
    for i in range(6):
        for j in range(5 - i):
            # SWAP(j, j+1) using 3 CX gates
            qc.cx(j, j+1)
            qc.cx(j+1, j)
            qc.cx(j, j+1)
            
    return qc

def build_bv22():
    """
    6 qubits. Bernstein-Vazirani for secret s = 22 (10110 in binary).
    """
    qc = QuantumCircuit(6)
    
    # Prepare ancilla in |-> but ensure it ends in |0>
    qc.x(5)
    qc.h(5)
    
    # Superposition
    qc.h([0, 1, 2, 3, 4])

    # Oracle for s = 22 = 16 + 4 + 2 = 10110_2
    # Bits 1, 2, and 4 are high
    qc.cx(1, 5)
    qc.cx(2, 5)
    qc.cx(4, 5)

    # Interference
    qc.h([0, 1, 2, 3, 4])
    
    # Restore ancilla strictly to |0>
    qc.h(5)
    qc.x(5)
    
    return qc

def build_add3():
    """
    6 qubits. In-place addition |a>|b> -> |a>|(a+b) mod 8>.
    Computes from MSB to LSB algebraically to avoid requiring ancilla.
    """
    qc = QuantumCircuit(6)
    
    # Bit 2 (MSB: q5)
    # b2 ^= a2 ^ c2, where carry c2 = (a1 & b1) ^ (a1 & c1) ^ (b1 & c1)
    # and c1 = a0 & b0.
    qc.cx(2, 5)
    qc.ccx(1, 4, 5)
    qc.mcx([1, 0, 3], 5)
    qc.mcx([4, 0, 3], 5)

    # Bit 1 (q4)
    # b1 ^= a1 ^ c1, where c1 = a0 & b0
    qc.cx(1, 4)
    qc.ccx(0, 3, 4)

    # Bit 0 (LSB: q3)
    # b0 ^= a0
    qc.cx(0, 3)
    
    return qc
