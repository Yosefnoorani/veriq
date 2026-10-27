"""Circuit families for the scaling benchmark: (candidate, reference, mode) at a given total width n.

Every family has a correct candidate and an injected-bug candidate. The candidate is always written
differently from the reference (by hand vs. library, or source vs. compiled), so equivalence is never trivial.
"""

from __future__ import annotations

import random
from math import pi

from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import CDKMRippleCarryAdder, QFTGate, SdgGate
from qiskit.synthesis import synth_qft_full


# ----------------------------------------------------------------------------- GHZ (state preparation)

def ghz_chain(n: int, bug: bool = False) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"ghz{n}_chain")
    qc.h(0)
    for i in range(n - 1):
        if bug and i == n // 2:
            qc.cx(i + 1, i)  # control/target slip in the middle of the chain
        else:
            qc.cx(i, i + 1)
    return qc


def ghz_tree(n: int) -> QuantumCircuit:
    """Reference: log-depth fan-out tree (different unitary, same state from |0...0>)."""
    qc = QuantumCircuit(n, name=f"ghz{n}_tree")
    qc.h(0)
    have = 1
    while have < n:
        for i in range(min(have, n - have)):
            qc.cx(i, have + i)
        have *= 2
    return qc


# ----------------------------------------------------------------------------- QFT

def qft_hand(n: int, approx: int = 0, bug: bool = False) -> QuantumCircuit:
    """Textbook QFT matching Qiskit's QFTGate convention; approx>0 drops controlled phases with k > n-approx."""
    qc = QuantumCircuit(n, name=f"qft{n}_hand")
    for j in reversed(range(n)):
        qc.h(j)
        for k in reversed(range(j)):
            dist = j - k
            if approx and dist > n - 1 - approx:
                continue
            angle = pi / 2 ** dist
            if bug and j == n - 1 and k == n - 2:
                angle = -angle  # sign slip on one controlled phase
            qc.cp(angle, k, j)
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    return qc


def qft_reference(n: int, approx: int = 0) -> QuantumCircuit:
    if approx:
        return synth_qft_full(n, approximation_degree=approx, do_swaps=True)
    qc = QuantumCircuit(n, name=f"qft{n}_ref")
    qc.append(QFTGate(n), range(n))
    return qc.decompose()


# ----------------------------------------------------------------------------- Grover-like phase oracle

def _marked(n: int) -> str:
    rng = random.Random(1000 + n)
    return "".join(rng.choice("01") for _ in range(n))


def oracle_hand(n: int, bug: bool = False) -> QuantumCircuit:
    """Phase oracle for one marked string (little-endian label), decomposed by Qiskit to {u, cx}."""
    s = _marked(n)
    qc = QuantumCircuit(n, name=f"oracle{n}")
    zeros = [q for q in range(n) if s[n - 1 - q] == "0"]
    if bug:
        zeros = zeros[1:]  # forgets one X-conjugation -> marks the wrong string
    if zeros:
        qc.x(zeros)
    qc.h(n - 1)
    qc.mcx(list(range(n - 1)), n - 1)
    qc.h(n - 1)
    if zeros:
        qc.x(zeros)
    return transpile(qc, basis_gates=["u", "cx"], optimization_level=1, qubits_initially_zero=False)


def oracle_reference(n: int) -> QuantumCircuit:
    s = _marked(n)
    qc = QuantumCircuit(n, name=f"oracle{n}_ref")
    zeros = [q for q in range(n) if s[n - 1 - q] == "0"]
    if zeros:
        qc.x(zeros)
    qc.mcp(pi, list(range(n - 1)), n - 1)  # native multi-controlled phase: QCEC handles it without decomposition
    if zeros:
        qc.x(zeros)
    return qc


# ----------------------------------------------------------------------------- random Clifford+T

def clifford_t(n: int, t_count: int | None = None, depth_factor: int = 3, seed: int = 0,
               nearest_neighbour: bool = True) -> QuantumCircuit:
    rng = random.Random(seed * 7919 + n)
    t_count = n // 2 if t_count is None else t_count
    qc = QuantumCircuit(n, name=f"cliffT{n}")
    for q in range(n - 1):  # entangling ladder: the circuit is one connected block (no trivial partition)
        qc.h(q)
        qc.cx(q, q + 1)
    slots = depth_factor * n
    t_at = set(rng.sample(range(slots), min(t_count, slots)))
    for i in range(slots):
        q = rng.randrange(n)
        r = rng.random()
        if i in t_at:
            qc.t(q)
        elif r < 0.25:
            qc.h(q)
        elif r < 0.45:
            qc.s(q)
        else:
            if nearest_neighbour:
                a = rng.randrange(n - 1)
                a, b = (a, a + 1) if rng.random() < 0.5 else (a + 1, a)
            else:
                a, b = rng.sample(range(n), 2)
            qc.cx(a, b)
    return qc


def clifford_t_compiled(n: int, bug: bool = False, **kw) -> QuantumCircuit:
    """Candidate: the same circuit, optimized by Qiskit (opt=3, {rz, sx, x, cx}), so it is written differently."""
    src = clifford_t(n, **kw)
    out = transpile(src, basis_gates=["rz", "sx", "x", "cx"], optimization_level=3, seed_transpiler=1)
    out = _strip_layout(out)
    if bug:
        _drop_one_rz(out)
    return out


def _strip_layout(qc: QuantumCircuit) -> QuantumCircuit:
    """No coupling map was given, so the layout is trivial; drop it so both circuits share qubit order."""
    plain = QuantumCircuit(qc.num_qubits, name=qc.name)
    for inst in qc.data:
        plain.append(inst.operation, [qc.find_bit(q).index for q in inst.qubits])
    return plain


def _drop_one_rz(qc: QuantumCircuit) -> None:
    idx = [i for i, inst in enumerate(qc.data) if inst.operation.name == "rz"
           and abs((float(inst.operation.params[0]) / (pi / 4)) % 2 - 1) < 1e-9]  # an odd multiple of pi/4 = a T
    i = idx[len(idx) // 2] if idx else next(i for i, x in enumerate(qc.data) if x.operation.name == "rz")
    del qc.data[i]


def clifford_resynth(n: int, bug: bool = False) -> QuantumCircuit:
    """Candidate for the pure-Clifford family: the reference re-synthesized from its tableau (greedy), so it is a
    different gate sequence that stays syntactically Clifford. Bug: one S becomes S-dagger."""
    from qiskit.quantum_info import Clifford
    from qiskit.synthesis import synth_clifford_greedy

    out = synth_clifford_greedy(Clifford(clifford_t(n, t_count=0)))
    out.name = f"clifford{n}_resynth"
    if bug:
        idx = [i for i, inst in enumerate(out.data) if inst.operation.name == "s"]
        i = idx[len(idx) // 2]
        inst = out.data[i]
        out.data[i] = inst.replace(operation=SdgGate())
    return out


# ----------------------------------------------------------------------------- Cuccaro ripple-carry adder

def cuccaro_hand(n: int, bug: bool = False) -> QuantumCircuit:
    """Cuccaro et al. (2004) adder on n = 2m+2 qubits: [cin, a0..am-1, b0..bm-1, cout] like CDKMRippleCarryAdder."""
    m = (n - 2) // 2
    qc = QuantumCircuit(2 * m + 2, name=f"cuccaro{m}")
    cin, a, b, cout = 0, list(range(1, m + 1)), list(range(m + 1, 2 * m + 1)), 2 * m + 1

    def maj(x, y, z):
        qc.cx(z, y)
        qc.cx(z, x)
        qc.ccx(x, y, z)

    def uma(x, y, z, slip=False):
        qc.ccx(x, y, z)
        qc.cx(z, x)
        if slip:
            qc.cx(z, y)  # BUG: should be cx(x, y)
        else:
            qc.cx(x, y)

    carry = [cin] + a[:-1]
    for i in range(m):
        maj(carry[i], b[i], a[i])
    qc.cx(a[m - 1], cout)
    for i in reversed(range(m)):
        uma(carry[i], b[i], a[i], slip=bug and i == m // 2)
    return qc


def cuccaro_reference(n: int) -> QuantumCircuit:
    m = (n - 2) // 2
    return CDKMRippleCarryAdder(m, kind="full").decompose()


# ----------------------------------------------------------------------------- independent blocks

BLOCK = 5


def blocks_hand(n: int, bug: bool = False) -> QuantumCircuit:
    """n // 5 independent 5-qubit QFT blocks (plus a leftover block): exercises the partitioned check."""
    qc = QuantumCircuit(n, name=f"blocks{n}")
    starts = list(range(0, n, BLOCK))
    for i, s in enumerate(starts):
        w = min(BLOCK, n - s)
        qc.compose(qft_hand(w, bug=bug and i == len(starts) // 2 and w > 1), range(s, s + w), inplace=True)
    return qc


def blocks_reference(n: int) -> QuantumCircuit:
    qc = QuantumCircuit(n, name=f"blocks{n}_ref")
    for s in range(0, n, BLOCK):
        w = min(BLOCK, n - s)
        qc.compose(qft_reference(w), range(s, s + w), inplace=True)
    return qc


# ----------------------------------------------------------------------------- registry

def build(family: str, n: int, bug: bool) -> tuple[QuantumCircuit, QuantumCircuit, str]:
    if family == "ghz":
        return ghz_chain(n, bug), ghz_tree(n), "state"
    if family == "qft":
        return qft_hand(n, bug=bug), qft_reference(n), "unitary"
    if family == "qft_approx":
        d = max(1, n - 6)  # keep controlled phases up to distance 5 (AQFT, the variant used at scale)
        return qft_hand(n, approx=d, bug=bug), qft_reference(n, approx=d), "unitary"
    if family == "oracle":
        return oracle_hand(n, bug), oracle_reference(n), "unitary"
    if family == "clifford_t":
        return clifford_t_compiled(n, bug), clifford_t(n), "unitary"
    if family == "clifford":
        return clifford_resynth(n, bug), clifford_t(n, t_count=0), "unitary"
    if family == "cuccaro":
        return cuccaro_hand(n, bug), cuccaro_reference(n), "unitary"
    if family == "blocks":
        return blocks_hand(n, bug), blocks_reference(n), "unitary"
    raise KeyError(family)


FAMILIES = ["ghz", "qft", "qft_approx", "oracle", "clifford_t", "clifford", "cuccaro", "blocks"]
