"""pytket (TKET) -> Qiskit.

Qubit mapping: `circ.qubits` (TKET's default ordering: sorted by register name, then index; `q[0], q[1], ...`
for a plain `Circuit(n)`) -- the i-th qubit becomes Qiskit qubit i. Classical bits likewise from `circ.bits`.

Endianness: `circ.get_unitary()` / `get_statevector()` are big-endian (ILO-BE: q[0] is the MOST significant
bit); Qiskit is little-endian. As with Cirq, the circuits are the same and the matrices differ by a qubit-order
reversal.

Angles: TKET parameters are in half-turns (Rz(0.5) is a quarter turn, pi/2 radians); they are multiplied by pi.
Global phase: `circ.phase` (half-turns) is added to `qc.global_phase`, and every gate is matched against
TKET's own matrix up to a phase that is also moved into `qc.global_phase`, so the result is exact.
Boxes (CircBox, QControlBox, ...) are expanded with TKET's DecomposeBoxes pass first.
"""

from __future__ import annotations

import math

from ..loader import LoadError
from ._exact import append_exact, append_unitary


def _require():
    try:
        import pytket  # noqa: F401
    except ImportError as exc:
        raise LoadError("this circuit needs pytket (TKET), which is not installed: pip install 'veriq[tket]'") from exc
    return pytket


def is_tket_circuit(obj) -> bool:
    mod = type(obj).__module__ or ""
    if not mod.startswith("pytket"):
        return False
    from pytket import Circuit

    return isinstance(obj, Circuit)


def _num(p) -> float:
    try:
        return float(p)
    except (TypeError, RuntimeError) as exc:
        raise LoadError(f"symbolic TKET parameter {p!r} is not supported; substitute values first "
                        f"(circ.symbol_substitution)") from exc


def _candidates(name: str, params: list[float]):
    from qiskit.circuit import library as L

    a = [math.pi * p for p in params]
    simple = {"H": L.HGate, "X": L.XGate, "Y": L.YGate, "Z": L.ZGate, "S": L.SGate, "Sdg": L.SdgGate,
              "T": L.TGate, "Tdg": L.TdgGate, "SX": L.SXGate, "SXdg": L.SXdgGate, "CX": L.CXGate,
              "CY": L.CYGate, "CZ": L.CZGate, "CH": L.CHGate, "CCX": L.CCXGate, "SWAP": L.SwapGate,
              "CSWAP": L.CSwapGate, "CSX": L.CSXGate, "ISWAPMax": L.iSwapGate, "ECR": L.ECRGate}
    if name in simple:
        return [simple[name]()]
    one = {"Rx": L.RXGate, "Ry": L.RYGate, "Rz": L.RZGate, "U1": L.PhaseGate, "CRx": L.CRXGate,
           "CRy": L.CRYGate, "CRz": L.CRZGate, "CU1": L.CPhaseGate, "ZZPhase": L.RZZGate,
           "XXPhase": L.RXXGate, "YYPhase": L.RYYGate}
    if name in one:
        return [one[name](a[0])]
    if name == "V":
        return [L.RXGate(math.pi / 2)]
    if name == "Vdg":
        return [L.RXGate(-math.pi / 2)]
    if name == "ZZMax":
        return [L.RZZGate(math.pi / 2)]
    if name == "U2":
        return [L.U2Gate(a[0], a[1])]
    if name == "U3":
        return [L.UGate(a[0], a[1], a[2])]
    if name == "CU3":
        return [L.CUGate(a[0], a[1], a[2], 0.0)]
    return []


def _append_rebased(qc, op, qs, target, cache) -> bool:
    """Rebase one unmapped TKET op (PhasedX, TK1, TK2, ISWAP, ...) to {CX, Rx, Rz} with TKET's own pass and
    append the result, keeping it only if it reproduces TKET's matrix exactly (up to a tracked phase)."""
    from pytket import Circuit, OpType
    from pytket.passes import AutoRebase
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Operator

    from ._exact import be_to_le, phase_between

    k = len(qs)
    try:
        sub = Circuit(k)
        sub.add_gate(op, list(range(k)))
        AutoRebase({OpType.CX, OpType.Rx, OpType.Rz}).apply(sub)
    except Exception:  # noqa: BLE001
        return False
    part = QuantumCircuit(k)
    part.global_phase = math.pi * _num(sub.phase)
    for c in sub.get_commands():
        idx = [a.index[0] for a in c.args]
        if not any(append_exact(part, g, idx, c.op.get_unitary(), cache)
                   for g in _candidates(c.op.type.name, [_num(p) for p in c.op.params])):
            return False
    ph = phase_between(Operator(part).data, be_to_le(target))
    if ph is None:
        return False
    qc.compose(part, qubits=qs, inplace=True)
    qc.global_phase += ph
    return True


def tket_to_qiskit(circ, source_format: str = "python"):
    """Convert a pytket Circuit into an exactly-equal Qiskit QuantumCircuit (see the module docstring)."""
    pytket = _require()
    from pytket.passes import DecomposeBoxes
    from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

    circ = circ.copy()
    DecomposeBoxes().apply(circ)
    qubits = list(circ.qubits)
    bits = list(circ.bits)
    qidx = {q: i for i, q in enumerate(qubits)}
    cidx = {b: i for i, b in enumerate(bits)}
    qc = QuantumCircuit(QuantumRegister(len(qubits), "q"))
    if bits:
        qc.add_register(ClassicalRegister(len(bits), "c"))
    qc.global_phase = math.pi * _num(circ.phase)
    stats = {"ops": 0, "opaque_ops": 0}
    cache: dict = {}
    for cmd in circ.get_commands():
        op = cmd.op
        name = op.type.name
        if name in ("Conditional", "ClassicalExpBox", "WASM", "RangePredicate", "ClExpr") or \
                getattr(cmd, "opgroup", None) == "conditional":
            raise LoadError(f"classically controlled TKET operations ({name}) are not supported")
        qs = [qidx[a] for a in cmd.args if a in qidx]
        cs = [cidx[a] for a in cmd.args if a in cidx]
        if name == "Measure":
            qc.measure(qs[0], cs[0])
            continue
        if name == "Reset":
            qc.reset(qs[0])
            continue
        if name == "Barrier":
            qc.barrier(*qs)
            continue
        if name in ("noop",):
            continue
        if name == "Phase":
            qc.global_phase += math.pi * _num(op.params[0])
            continue
        if cs:
            raise LoadError(f"TKET operation {name} with classical arguments is not supported")
        params = [_num(p) for p in op.params]
        try:
            target = op.get_unitary()
        except Exception as exc:  # noqa: BLE001
            raise LoadError(f"TKET operation {name} has no unitary and is not supported: {exc}") from exc
        if any(append_exact(qc, g, qs, target, cache) for g in _candidates(name, params)):
            stats["ops"] += 1
            continue
        if _append_rebased(qc, op, qs, target, cache):
            stats["ops"] += 1
            stats["rebased_ops"] = stats.get("rebased_ops", 0) + 1
            continue
        append_unitary(qc, qs, target, f"tket:{name}")
        stats["opaque_ops"] += 1
    qc.name = circ.name or "tket_circuit"
    qc.metadata = {"veriq_frontend": {
        "framework": "tket", "framework_version": pytket.__version__, "source_format": source_format,
        "qubit_order": "circ.qubits (TKET default order) -> qiskit qubit i",
        "qubit_map": [str(q) for q in qubits], "bit_map": [str(b) for b in bits], **stats}}
    return qc


def load_tket_json(text: str, source_format: str = "json"):
    _require()
    import json

    from pytket import Circuit

    try:
        circ = Circuit.from_dict(json.loads(text))
    except Exception as exc:  # noqa: BLE001
        raise LoadError(f"cannot parse TKET JSON: {exc}") from exc
    return tket_to_qiskit(circ, source_format)
