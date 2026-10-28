from itertools import combinations
from collections import deque
from math import pi

from qiskit import QuantumCircuit


def build_maj5_oracle():
    qc = QuantumCircuit(6)
    ctrls = [0, 1, 2, 3, 4]
    for pattern in range(32):
        if bin(pattern).count("1") >= 3:
            zeros = [q for q in ctrls if not (pattern >> q) & 1]
            for q in zeros:
                qc.x(q)
            qc.mcx(ctrls, 5)
            for q in zeros:
                qc.x(q)
    return qc


def build_cmul7_mod15():
    qc = QuantumCircuit(5)

    def swap_states(a, b):
        diff = a ^ b
        p = min(i for i in range(4) if (diff >> i) & 1)
        others = [d for d in range(4) if (diff >> d) & 1 and d != p]
        for d in others:
            qc.cx(p, d)
        a1 = a
        if (a >> p) & 1:

            for d in others:
                a1 ^= 1 << d
        ctrl_bits = [i for i in range(4) if i != p]
        zeros = [i for i in ctrl_bits if not (a1 >> i) & 1]
        for i in zeros:
            qc.x(i)
        qc.mcx(ctrl_bits + [4], p)
        for i in zeros:
            qc.x(i)
        for d in reversed(others):
            qc.cx(p, d)

    perm = {x: (7 * x) % 15 for x in range(15)}
    perm[15] = 15
    seen = set()
    for start in range(16):
        if start in seen or perm[start] == start:
            seen.add(start)
            continue
        cycle = [start]
        seen.add(start)
        nxt = perm[start]
        while nxt != start:
            cycle.append(nxt)
            seen.add(nxt)
            nxt = perm[nxt]
        for j in range(1, len(cycle)):
            swap_states(cycle[0], cycle[j])
    return qc


def build_qpe_t():

    qc = QuantumCircuit(4)
    qc.x(3)
    qc.h([0, 1, 2])
    qc.cp(pi / 4, 0, 3)
    qc.cp(pi / 2, 1, 3)
    qc.cp(pi, 2, 3)
    # inverse QFT on q0..q2 (little-endian)
    qc.swap(0, 2)
    qc.h(0)
    qc.cp(-pi / 2, 0, 1)
    qc.h(1)
    qc.cp(-pi / 4, 0, 2)
    qc.cp(-pi / 2, 1, 2)
    qc.h(2)
    return qc


def build_c3x_linear():
    n = 4
    qc = QuantumCircuit(n)
    moves = [(0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2)]  # (control, target)

    def apply(state, mv):
        c, t = mv
        s = list(state)
        s[t] ^= s[c]
        return tuple(s)

    identity = tuple(1 << i for i in range(n))

    def bfs_path(start, goal_fn):
        if goal_fn(start):

            return []
        prev = {start: None}
        dq = deque([start])
        while dq:
            cur = dq.popleft()
            for mv in moves:
                nx = apply(cur, mv)
                if nx not in prev:
                    prev[nx] = (cur, mv)
                    if goal_fn(nx):
                        path = []
                        node = nx
                        while prev[node] is not None:
                            node, m = prev[node][0], prev[node][1]
                            path.append(m)
                        return path[::-1]
                    dq.append(nx)
        raise RuntimeError("unreachable")

    # phase polynomial: pi * abcd = sum_S (-1)^{|S|+1} (pi/8) parity_S
    angle = {}
    for k in range(1, n + 1):
        for S in combinations(range(n), k):
            mask = sum(1 << i for i in S)
            angle[mask] = (pi / 8) * (1 if k % 2 == 1 else -1)

    target = 3
    qc.h(target)
    state = identity
    remaining = set(angle.keys())

    def flush(state):

        for q in range(n):
            if state[q] in remaining:
                qc.p(angle[state[q]], q)
                remaining.discard(state[q])

    flush(state)
    while remaining:
        path = bfs_path(state, lambda st: any(r in remaining for r in st))
        for mv in path:
            qc.cx(*mv)
            state = apply(state, mv)
        flush(state)
    for mv in bfs_path(state, lambda st: st == identity):
        qc.cx(*mv)
        state = apply(state, mv)
    qc.h(target)
    return qc


def build_reverse6_nn():
    n = 6
    qc = QuantumCircuit(n)
    for r in range(n):
        for i in range(r % 2, n - 1, 2):
            qc.cx(i, i + 1)
            qc.cx(i + 1, i)
            qc.cx(i, i + 1)
    return qc


def build_bv22():
    qc = QuantumCircuit(6)

    s = 22
    qc.h(range(5))
    qc.x(5)
    qc.h(5)
    for i in range(5):
        if (s >> i) & 1:
            qc.cx(i, 5)
    qc.h(range(5))
    qc.h(5)
    qc.x(5)
    return qc


def build_add3():
    qc = QuantumCircuit(6)
    a0, a1, a2 = 0, 1, 2
    b0, b1, b2 = 3, 4, 5
    # bit 2 (uses original b0, b1)
    qc.cx(a2, b2)
    qc.ccx(a1, b1, b2)
    qc.mcx([a0, b0, a1], b2)
    qc.mcx([a0, b0, b1], b2)
    # bit 1
    qc.cx(a1, b1)
    qc.ccx(a0, b0, b1)
    # bit 0
    qc.cx(a0, b0)
    return qc
