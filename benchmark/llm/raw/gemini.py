import math
from qiskit import QuantumCircuit

def build_ghz5():
    """1. 5-qubit GHZ state"""
    qc = QuantumCircuit(5)
    qc.h(0)
    for i in range(4):
        qc.cx(i, i + 1)
    return qc

def build_w3():
    """2. 3-qubit W state"""
    qc = QuantumCircuit(3)
    
    # Rotate q2 so it has probability 1/3 of being |1>
    qc.ry(2 * math.asin(1 / math.sqrt(3)), 2)
    
    # Controlled-H on q1 when q2 is |0>
    qc.x(2)
    qc.ch(2, 1)
    qc.x(2)
    
    # Set q0 to |1> only when both q2 and q1 are |0>
    qc.cx(2, 0)
    qc.cx(1, 0)
    qc.x(0)
    
    return qc

def build_qft4():
    """3. 4-qubit Quantum Fourier Transform"""
    qc = QuantumCircuit(4)
    
    # Apply Hadamards and controlled phases
    for i in range(3, -1, -1):
        qc.h(i)
        for j in range(i - 1, -1, -1):
            qc.cp(math.pi / (2 ** (i - j)), j, i)
            
    # Qubit-reversal swaps for little-endian convention
    qc.swap(0, 3)
    qc.swap(1, 2)
    
    return qc

def build_iqft3():
    """4. 3-qubit Inverse Quantum Fourier Transform"""
    qc = QuantumCircuit(3)
    
    # Inverse swaps
    qc.swap(0, 2)
    
    # Inverse QFT operations (reverse order, negative phases)
    for i in range(3):
        for j in range(i):
            qc.cp(-math.pi / (2 ** (i - j)), j, i)
        qc.h(i)
        
    return qc

def build_grover3():
    """5. 3-qubit Grover for |101>"""
    qc = QuantumCircuit(3)
    
    # Initial superposition
    qc.h([0, 1, 2])
    
    for _ in range(2):
        # --- Oracle for |101> (q2=1, q1=0, q0=1) ---
        qc.x(1)
        qc.h(2)
        qc.ccx(0, 1, 2)
        qc.h(2)
        qc.x(1)
        
        # --- Diffusion Operator ---
        qc.h([0, 1, 2])
        qc.x([0, 1, 2])
        # CCZ implemented using CCX
        qc.h(2)
        qc.ccx(0, 1, 2)
        qc.h(2)
        qc.x([0, 1, 2])
        qc.h([0, 1, 2])
        
    return qc

def build_toffoli():
    """6. Toffoli using only basic Clifford+T gates"""
    qc = QuantumCircuit(3)
    
    # Nielsen & Chuang standard decomposition
    # Controls: q0, q1. Target: q2.
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
    qc.cx(0, 1)
    qc.t(0)
    qc.tdg(1)
    qc.cx(0, 1)
    qc.h(2)
    
    return qc

def build_adder2():
    """
    7. 2-bit quantum ripple-carry adder (in-place) without ancilla.
    q0=a0, q1=a1, q2=b0, q3=b1, q4=carry.
    Computes a + b in-place, leaving 'a' unchanged.
    """
    qc = QuantumCircuit(5)
    
    # Forward pass: computing carry and intermediate sums
    qc.ccx(0, 2, 3)    # q3 = b1 ^ (a0 * b0)
    qc.ccx(0, 2, 1)    # q1 = a1 ^ (a0 * b0)
    qc.cx(0, 2)        # q2 = a0 ^ b0 (Sum 0)
    
    # Carry-out calculation into q4
    qc.ccx(1, 3, 4)    # q4 ^= a1 * b1 (intermediate)
    qc.x(2)            # q2 = ~(a0 ^ b0)
    qc.ccx(0, 2, 4)    # q4 ^= carry_out finalization
    
    # Reverse intermediate steps & compute final sums
    qc.ccx(0, 2, 1)    # Restore q1 -> a1
    qc.cx(1, 3)        # q3 = a1 ^ b1 ^ (a0 * b0) (Sum 1)
    qc.x(2)            # Restore q2 -> Sum 0
    
    return qc
