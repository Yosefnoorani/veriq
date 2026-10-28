"""Cirq -> Qiskit.

Qubit mapping: the circuit's qubits are sorted with Cirq's own ordering (`sorted(circuit.all_qubits())`,
i.e. `cirq.QubitOrder.DEFAULT`; LineQubit(i) by i, GridQubit by (row, col), NamedQubit by name) and the i-th
qubit in that list becomes Qiskit qubit i. Only qubits the circuit touches exist (an unused LineQubit(5)
is not created; add `cirq.I(q)` to keep it).

Endianness: Cirq's `cirq.unitary(circuit)` and state vectors are big-endian (qubit 0 is the MOST significant
bit); Qiskit's are little-endian (qubit 0 is the LEAST significant). The *circuits* are the same, the
matrices differ by a qubit-order reversal: Operator(qc) == reverse_qargs(cirq.unitary(c)). A bitstring
measured on cirq qubits (q0, q1, ...) reads q0 first; Qiskit's count key prints the last qubit first.

Global phase is tracked exactly (each gate is matched up to a phase, which is moved into
`qc.global_phase`; `cirq.GlobalPhaseGate` adds its phase), so Operator(qc) equals Cirq's unitary exactly.
"""

from __future__ import annotations

import cmath
import math

import numpy as np

from ..loader import LoadError
from ._exact import append_exact, append_unitary

MAX_DECOMP_CHECK_QUBITS = 10


def _require():
    try:
        import cirq  # noqa: F401
    except ImportError as exc:
        raise LoadError("this circuit needs Cirq, which is not installed: pip install 'veriq[cirq]' "
                        "(cirq-core)") from exc
    return cirq


def is_cirq_circuit(obj) -> bool:
    mod = type(obj).__module__ or ""
    if not mod.startswith("cirq"):
        return False
    import cirq

    return isinstance(obj, cirq.AbstractCircuit)


def _num(x) -> float:
    try:
        return float(x)
    except TypeError as exc:
        raise LoadError(f"symbolic Cirq parameter {x!r} is not supported; resolve parameters first "
                        f"(cirq.resolve_parameters)") from exc


def _candidates(gate):
    """Qiskit gates to try for a Cirq gate (each is checked against cirq.unitary up to phase)."""
    import cirq
    from qiskit.circuit import library as L

    t = getattr(gate, "exponent", None)
    if t is not None:
        t = _num(t)
    out = []
    if isinstance(gate, cirq.HPowGate):
        out = [L.HGate()] if t == 1 else []
    elif isinstance(gate, cirq.XPowGate):
        out = ([L.XGate()] if t % 2 == 1 else []) + ([L.SXGate()] if t == 0.5 else []) + [L.RXGate(math.pi * t)]
    elif isinstance(gate, cirq.YPowGate):
        out = ([L.YGate()] if t % 2 == 1 else []) + [L.RYGate(math.pi * t)]
    elif isinstance(gate, cirq.ZPowGate):
        named = {1: L.ZGate(), 0.5: L.SGate(), -0.5: L.SdgGate(), 0.25: L.TGate(), -0.25: L.TdgGate()}
        out = ([named[t]] if t in named else []) + [L.PhaseGate(math.pi * t)]
    elif isinstance(gate, cirq.CZPowGate):
        out = ([L.CZGate()] if t == 1 else []) + [L.CPhaseGate(math.pi * t)]
    elif isinstance(gate, cirq.CXPowGate):
        out = [L.CXGate()] if t == 1 else []
    elif isinstance(gate, cirq.SwapPowGate):
        out = [L.SwapGate()] if t == 1 else []
    elif isinstance(gate, cirq.ISwapPowGate):
        out = [L.iSwapGate()] if t == 1 else []
    elif isinstance(gate, cirq.CCXPowGate):
        out = [L.CCXGate()] if t == 1 else []
    elif isinstance(gate, cirq.CCZPowGate):
        out = [L.CCZGate()] if t == 1 else []
    elif isinstance(gate, cirq.CSwapGate):
        out = [L.CSwapGate()]
    elif isinstance(gate, cirq.ControlledGate):
        cv = getattr(gate, "control_values", None)
        try:
            all_one = all(tuple(v) == (1,) for v in cv) if cv is not None else True
        except TypeError:
            all_one = False
        if all_one and gate.sub_gate.num_qubits() == 1:
            out = [g.control(gate.num_controls()) for g in _candidates(gate.sub_gate)]
    return out


def cirq_to_qiskit(circuit, source_format: str = "python"):
    """Convert a cirq.Circuit into an exactly-equal Qiskit QuantumCircuit (see the module docstring)."""
    cirq = _require()
    from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

    qubits = sorted(circuit.all_qubits())
    index = {q: i for i, q in enumerate(qubits)}
    meas_keys: list[str] = []
    n_meas = 0
    for op in circuit.all_operations():
        if cirq.is_measurement(op):
            n_meas += len(op.qubits)
    qc = QuantumCircuit(QuantumRegister(len(qubits), "q"))
    creg = ClassicalRegister(n_meas, "c") if n_meas else None
    if creg is not None:
        qc.add_register(creg)
    stats = {"ops": 0, "opaque_ops": 0, "decomposed_ops": 0}
    cache: dict = {}
    clbit = [0]

    def emit(op, depth=0):
        gate = op.gate
        qargs = [index[q] for q in op.qubits]
        if isinstance(op, cirq.ClassicallyControlledOperation):
            raise LoadError("classically controlled Cirq operations are not supported")
        if gate is not None and isinstance(gate, cirq.MeasurementGate):
            if any(gate.full_invert_mask()):
                raise LoadError("Cirq measurements with an invert_mask are not supported")
            meas_keys.append(str(gate.key))
            for q in qargs:
                qc.measure(q, creg[clbit[0]])
                clbit[0] += 1
            return
        if gate is not None and isinstance(gate, cirq.ResetChannel):
            qc.reset(qargs[0])
            return
        if gate is not None and isinstance(gate, cirq.GlobalPhaseGate):
            qc.global_phase += cmath.phase(complex(gate.coefficient))
            return
        if gate is not None and isinstance(gate, cirq.IdentityGate):
            return
        if not cirq.has_unitary(op):
            raise LoadError(f"Cirq operation {op!r} is not unitary (noise channels and other non-unitary "
                            f"operations other than measurement/reset are not supported)")
        if gate is not None and not cirq.is_parameterized(op):
            target = None
            for cand in _candidates(gate):
                if target is None:
                    target = cirq.unitary(op)
                if append_exact(qc, cand, qargs, target, cache):
                    stats["ops"] += 1
                    return
        if cirq.is_parameterized(op):
            raise LoadError(f"symbolic Cirq parameters in {op!r} are not supported; resolve them first")
        sub = cirq.decompose_once(op, default=None) if depth < 12 else None
        if sub:
            sub = list(sub)
            before = qc.global_phase
            start = len(qc.data)
            for s in sub:
                emit(s, depth + 1)
            stats["decomposed_ops"] += 1
            if len(op.qubits) <= MAX_DECOMP_CHECK_QUBITS:
                _fix_decomposition_phase(qc, op, start, before, index, cirq)
            return
        append_unitary(qc, qargs, cirq.unitary(op), f"cirq:{gate or op}")
        stats["opaque_ops"] += 1

    for op in circuit.all_operations():
        emit(op)
    qc.name = "cirq_circuit"
    qc.metadata = {"veriq_frontend": {
        "framework": "cirq", "framework_version": cirq.__version__, "source_format": source_format,
        "qubit_order": "sorted(circuit.all_qubits()) -> qiskit qubit i",
        "qubit_map": [str(q) for q in qubits], "measurement_keys": meas_keys, **stats}}
    return qc


def _fix_decomposition_phase(qc, op, start, phase_before, index, cirq) -> None:
    """cirq.decompose_once may drop a global phase; restore it so the conversion stays exact."""
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Operator

    from ._exact import be_to_le, phase_between

    local = {index[q]: i for i, q in enumerate(op.qubits)}
    part = QuantumCircuit(len(op.qubits))
    for inst in qc.data[start:]:
        part.append(inst.operation, [local[qc.find_bit(b).index] for b in inst.qubits])
    part.global_phase = qc.global_phase - phase_before
    ph = phase_between(Operator(part).data, be_to_le(cirq.unitary(op)))
    if ph is None:
        raise LoadError(f"internal: Cirq decomposition of {op!r} does not reproduce its unitary")
    qc.global_phase += ph


def load_cirq_json(text: str, source_format: str = "json"):
    cirq = _require()
    try:
        obj = cirq.read_json(json_text=text)
    except Exception as exc:  # noqa: BLE001
        raise LoadError(f"cannot parse Cirq JSON: {exc}") from exc
    if not isinstance(obj, cirq.AbstractCircuit):
        raise LoadError(f"Cirq JSON holds a {type(obj).__name__}, not a Circuit")
    return cirq_to_qiskit(obj, source_format)
