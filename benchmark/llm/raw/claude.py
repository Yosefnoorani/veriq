# Claude (Sonnet 5.5 Medium)
from math import pi, acos, sqrt

from qiskit import QuantumCircuit


def build_ghz5() -> QuantumCircuit:
    qc = QuantumCircuit(5)
    qc.h(0)
    for i in range(4):
        qc.cx(i, i + 1)
    return qc


def build_w3() -> QuantumCircuit:
    # Prepares (|001> + |010> + |100>)/sqrt(3), little-endian.
    qc = QuantumCircuit(3)
    # Rotate q0 so that amplitude on |1> is sqrt(1/3).
    theta0 = 2 * acos(sqrt(1 / 3))  # cos(theta/2) = sqrt(1/3) on |0>?? see below
    # We want q0 = |1> with prob 1/3: RY(theta) gives cos(t/2)|0> + sin(t/2)|1>
    # so sin^2(t/2) = 1/3  ->  t = 2*asin(sqrt(1/3)).
    from math import asin
    qc.ry(2 * asin(sqrt(1 / 3)), 0)
    # If q0 == 0 (amplitude sqrt(2/3)), split between q1 and q2 equally:
    # controlled on q0 = 0, rotate q1 by 2*asin(sqrt(1/2)) = pi/2 -> use X-conjugation.
    qc.x(0)
    # Controlled-RY(pi/2) from q0 (control) to q1, built from basic gates:
    # CRY(t) = RY(t/2) on target; CX; RY(-t/2) on target; CX
    t = pi / 2
    qc.ry(t / 2, 1)
    qc.cx(0, 1)
    qc.ry(-t / 2, 1)
    qc.cx(0, 1)

    qc.x(0)
    # Now state: sqrt(1/3)|q0=1,q1=0> + sqrt(2/3)|q0=0>(cos(pi/4)|q1=0> + sin(pi/4)|q1=1>)
    # Branch q0=0,q1=0 must go to q2=1:  CX(q1->q2) style fix via flipping.
    # Move amplitude: states with (q0=0,q1=0) and (q0=1,q1=0) need q2 handling.
    # Currently components: |q2=0> ⊗ [ sqrt(1/3)|q1q0=01> + sqrt(1/3)|10> + sqrt(1/3)|00> ].
    # Target: |001>,|010>,|100> => the |00> (q2q1q0 = 000) component must become q2=1.
    # Flip q2 when q0=0 and q1=0.
    qc.x(0)
    qc.x(1)
    _ccx(qc, 0, 1, 2)
    qc.x(1)
    qc.x(0)
    return qc


def _ccx(qc: QuantumCircuit, c1: int, c2: int, t: int) -> None:
    """Toffoli from h, t, tdg, cx."""
    qc.h(t)
    qc.cx(c2, t)
    qc.tdg(t)
    qc.cx(c1, t)
    qc.t(t)
    qc.cx(c2, t)
    qc.tdg(t)
    qc.cx(c1, t)
    qc.t(c2)
    qc.t(t)
    qc.h(t)
    qc.cx(c1, c2)
    qc.t(c1)
    qc.tdg(c2)
    qc.cx(c1, c2)



def _cphase(qc: QuantumCircuit, angle: float, a: int, b: int) -> None:
    """Controlled-phase(angle) between qubits a and b from basic gates."""
    qc.p(angle / 2, a)
    qc.cx(a, b)
    qc.p(-angle / 2, b)
    qc.cx(a, b)
    qc.p(angle / 2, b)


def build_qft4() -> QuantumCircuit:
    n = 4
    qc = QuantumCircuit(n)
    for j in range(n - 1, -1, -1):
        qc.h(j)
        for k in range(j - 1, -1, -1):
            _cphase(qc, pi / 2 ** (j - k), k, j)
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc


def build_iqft3() -> QuantumCircuit:
    n = 3
    qc = QuantumCircuit(n)
    # Inverse of: [H/cphase ladder] then swaps  ->  swaps first, then reversed ladder with negated angles.
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    for j in range(n):
        for k in range(j):
            _cphase(qc, -pi / 2 ** (j - k), k, j)

        qc.h(j)
    return qc


def _ccz(qc: QuantumCircuit, a: int, b: int, c: int) -> None:
    qc.h(c)
    qc.ccx(a, b, c)
    qc.h(c)


def build_grover3() -> QuantumCircuit:
    qc = QuantumCircuit(3)
    qc.h([0, 1, 2])
    for _ in range(2):
        # Oracle marking |101> (q0=1, q1=0, q2=1): flip q1 so target becomes |111>.
        qc.x(1)
        _ccz(qc, 0, 1, 2)
        qc.x(1)
        # Diffusion: H X (CCZ) X H
        qc.h([0, 1, 2])
        qc.x([0, 1, 2])
        _ccz(qc, 0, 1, 2)
        qc.x([0, 1, 2])
        qc.h([0, 1, 2])
    return qc


def build_toffoli() -> QuantumCircuit:
    qc = QuantumCircuit(3)
    _ccx(qc, 0, 1, 2)
    return qc



def build_adder2() -> QuantumCircuit:
    # a0=q0, a1=q1, b0=q2, b1=q3, carry-out register c=q4.
    qc = QuantumCircuit(5)
    # Carry out of bit 1 = MAJ(a1, b1, c0) where c0 = a0 AND b0.
    # Compute carry_out = a1&b1 XOR (a1 XOR b1)&c0, without ancilla, in order:
    # Step 1: carry_out ^= (a1 XOR b1) & (a0 & b0) and a1&b1, using b1 as scratch.
    # Use b1 <- b1 XOR a1 so that b1' = a1 XOR b1.
    qc.cx(1, 3)          # b1' = a1 ^ b1
    # carry_out ^= a1 & b1  == a1 & (b1' ^ a1) = a1&b1' ^ a1  -> do as: ccx(a1,b1,..) before changing b1.
    # Reorder cleanly: undo and use direct formulation.
    qc.cx(1, 3)          # restore b1
    # carry_out ^= a1 & b1
    qc.ccx(1, 3, 4)
    # carry_out ^= (a1 ^ b1) & a0 & b0 : needs 3-control; use b1' trick with the
    # identity (a1^b1)&c0 where c0 = a0&b0, implemented by temporarily putting
    # c0 into b0's partner is impossible without ancilla, so use q4 reversible decomposition:
    # (a1^b1)&a0&b0 = a1&a0&b0 ^ b1&a0&b0 -> two 3-control Toffolis, each built from ccx + phase-free trick below.
    _toffoli3(qc, 1, 0, 2, 4)  # a1 & a0 & b0 -> carry_out
    _toffoli3(qc, 3, 0, 2, 4)  # b1 & a0 & b0 -> carry_out
    # Now compute sum: b <- (a + b) mod 4
    # bit0: b0 ^= a0 (after carry usage); bit1: b1 ^= a1 ^ (a0 & b0_old)
    qc.ccx(0, 2, 3)      # b1 ^= a0 & b0_old
    qc.cx(1, 3)          # b1 ^= a1
    qc.cx(0, 2)          # b0 ^= a0
    return qc


def _toffoli3(qc: QuantumCircuit, c1: int, c2: int, c3: int, target: int) -> None:
    """3-controlled X using a relative-phase-free decomposition with no ancilla.

    Implemented via the standard C3X = H-conjugated C3Z built from

    controlled-phase rotations of angle pi/4 (basic p/cx gates).
    """
    qc.h(target)
    # C3Z via phase decomposition over subsets of {c1, c2, c3, target}
    qs = [c1, c2, c3, target]
    angle = pi / 4
    # Phase polynomial for multi-controlled Z on 4 qubits:
    # exp(i*pi * x1 x2 x3 x4) = prod over non-empty subsets S of exp(i*pi/8 * (-1)^(|S|+1) * parity(S))
    # with parity(S) = XOR of bits in S.
    from itertools import combinations
    theta = pi / 8
    for size in range(1, 5):
        sign = 1 if size % 2 == 1 else -1
        for subset in combinations(qs, size):
            _parity_phase(qc, list(subset), sign * theta)
    qc.h(target)


def _parity_phase(qc: QuantumCircuit, subset: list, angle: float) -> None:
    """Apply exp(i*angle*parity(subset)) i.e. phase 'angle' when XOR of bits is 1."""
    tgt = subset[-1]
    for q in subset[:-1]:
        qc.cx(q, tgt)
    qc.p(angle, tgt)
    for q in reversed(subset[:-1]):
        qc.cx(q, tgt)
