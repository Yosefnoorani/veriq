"""Load a Qiskit QuantumCircuit from a .py module or an OpenQASM 2/3 file."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from qiskit import QuantumCircuit


class LoadError(Exception):
    pass


def load_circuit(path: str | Path) -> QuantumCircuit:
    p = Path(path)
    if not p.exists():
        raise LoadError(f"file not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".py":
        return _load_py(p)
    if suffix in (".qasm", ".qasm2", ".qasm3"):
        return _load_qasm(p)
    raise LoadError(f"unsupported file type '{suffix}' (expected .py or .qasm)")


def _load_py(p: Path) -> QuantumCircuit:
    """Convention: the module exposes `circuit` (a QuantumCircuit) or `build()` returning one."""
    mod_name = f"_veriq_user_{abs(hash(str(p.resolve())))}"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    if spec is None or spec.loader is None:
        raise LoadError(f"cannot import {p}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(p.parent))
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # user code may raise anything
        raise LoadError(f"error while executing {p.name}: {exc!r}") from exc
    finally:
        sys.path.pop(0)
    if hasattr(module, "build") and callable(module.build):
        qc = module.build()
    elif hasattr(module, "circuit"):
        qc = module.circuit
    else:
        raise LoadError(f"{p.name} must define `circuit` or a `build()` function")
    if not isinstance(qc, QuantumCircuit):
        raise LoadError(f"{p.name}: expected a QuantumCircuit, got {type(qc).__name__}")
    if not qc.name or qc.name.startswith("circuit-"):
        qc.name = p.stem
    return qc


def _load_qasm(p: Path) -> QuantumCircuit:
    text = p.read_text()
    m = re.search(r"OPENQASM\s+(\d+)", text)
    version = int(m.group(1)) if m else 2
    try:
        if version >= 3:
            from qiskit import qasm3

            qc = qasm3.loads(text)
        else:
            from qiskit import qasm2

            qc = qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
    except Exception as exc:
        raise LoadError(f"cannot parse OpenQASM {version} in {p.name}: {exc}") from exc
    qc.name = p.stem
    return qc
