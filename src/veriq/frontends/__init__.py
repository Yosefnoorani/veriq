"""Frontends: load a circuit written for Qiskit, OpenQASM 2/3, Cirq or pytket/TKET into a Qiskit QuantumCircuit.

    load(path, function=None, framework=None) -> QuantumCircuit

| file | framework (auto-detected) |
|---|---|
| `.qasm` / `.qasm2` / `.qasm3` | `qasm2` or `qasm3` from the `OPENQASM` header (qiskit.qasm2 / qiskit.qasm3) |
| `.py` | by the type of the built object: `qiskit.QuantumCircuit`, `cirq.Circuit` or `pytket.Circuit` |
| `.json` | Cirq JSON (`"cirq_type"`) or TKET JSON (`"commands"` + `"qubits"`) |

`framework=` (CLI `--framework`, `.veriq.yml` `framework:`, MCP `framework`) forces the parser / asserts the
type; a mismatch is a load error. Converted circuits carry `qc.metadata["veriq_frontend"]` (framework,
framework version, source format, qubit map), which certificates record. Qubit-order rules: see
`cirq_frontend` / `tket_frontend` and docs/frameworks.md.
"""

from __future__ import annotations

import json
from pathlib import Path

FRAMEWORKS = ("qiskit", "qasm2", "qasm3", "cirq", "tket")
ALIASES = {"pytket": "tket", "openqasm2": "qasm2", "openqasm3": "qasm3", "auto": None, "": None}
EXTRA = {"cirq": "cirq", "tket": "tket", "qasm3": "qasm3"}


def normalize_framework(fw: str | None) -> str | None:
    if fw is None:
        return None
    f = str(fw).strip().lower()
    f = ALIASES.get(f, f)
    if f is not None and f not in FRAMEWORKS:
        from ..loader import LoadError

        raise LoadError(f"unknown framework '{fw}' (expected one of: auto, {', '.join(FRAMEWORKS)})")
    return f


def from_object(obj, framework: str | None = None, source_format: str = "python", where: str = "circuit"):
    """Convert a built circuit object (Qiskit, Cirq or TKET) into a Qiskit QuantumCircuit."""
    from qiskit import QuantumCircuit

    from ..loader import BuildError, LoadError

    fw = normalize_framework(framework)
    if isinstance(obj, QuantumCircuit):
        found = "qiskit"
    else:
        mod = type(obj).__module__ or ""
        found = "cirq" if mod.startswith("cirq") else "tket" if mod.startswith("pytket") else None
    if found is None:
        raise BuildError(f"{where}: expected a QuantumCircuit, cirq.Circuit or pytket Circuit, got "
                         f"{type(obj).__name__}", "WrongReturnType")
    if fw is not None and fw not in (found,) and not (fw in ("qasm2", "qasm3") and found == "qiskit"):
        raise LoadError(f"{where}: framework '{fw}' requested but the code built a {found} circuit")
    if found == "qiskit":
        return obj
    if found == "cirq":
        from .cirq_frontend import cirq_to_qiskit, is_cirq_circuit

        if not is_cirq_circuit(obj):
            raise BuildError(f"{where}: {type(obj).__name__} is not a cirq.Circuit", "WrongReturnType")
        return cirq_to_qiskit(obj, source_format)
    from .tket_frontend import is_tket_circuit, tket_to_qiskit

    if not is_tket_circuit(obj):
        raise BuildError(f"{where}: {type(obj).__name__} is not a pytket Circuit", "WrongReturnType")
    return tket_to_qiskit(obj, source_format)


def detect_json(text: str) -> str:
    from ..loader import LoadError

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LoadError(f"not valid JSON: {exc}") from exc
    if isinstance(data, dict) and "cirq_type" in data:
        return "cirq"
    if isinstance(data, dict) and "commands" in data and "qubits" in data:
        return "tket"
    raise LoadError("unrecognised circuit JSON: expected Cirq JSON (cirq.to_json) or TKET JSON (Circuit.to_dict)")


def load(path, function: str | None = None, framework: str | None = None):
    from ..loader import LoadError, _load_py, _load_qasm

    p = Path(path)
    if not p.exists():
        raise LoadError(f"file not found: {p}")
    fw = normalize_framework(framework)
    suffix = p.suffix.lower()
    if suffix == ".py":
        if fw in ("qasm2", "qasm3"):
            raise LoadError(f"framework '{fw}' needs a .qasm file, got {p.name}")
        return _load_py(p, function, fw)
    if suffix in (".qasm", ".qasm2", ".qasm3"):
        if fw in ("cirq", "tket"):
            raise LoadError(f"framework '{fw}' cannot read OpenQASM directly; load {p.name} as qasm2/qasm3")
        return _load_qasm(p, fw)
    if suffix == ".json":
        text = p.read_text()
        kind = detect_json(text)
        if fw is not None and fw != kind:
            raise LoadError(f"{p.name} is {kind} JSON, but framework '{fw}' was requested")
        if kind == "cirq":
            from .cirq_frontend import load_cirq_json

            qc = load_cirq_json(text)
        else:
            from .tket_frontend import load_tket_json

            qc = load_tket_json(text)
        qc.name = p.stem
        return qc
    raise LoadError(f"unsupported file type '{suffix}' (expected .py, .qasm or a Cirq/TKET .json)")


def frontend_info(qc, path: str | None = None) -> dict:
    """What produced this circuit: framework, its version, and the source format (for certificates)."""
    from importlib.metadata import PackageNotFoundError, version

    meta = (getattr(qc, "metadata", None) or {}).get("veriq_frontend") if qc is not None else None
    if meta:
        keep = ("framework", "framework_version", "source_format", "qubit_order", "opaque_ops")
        return {k: meta[k] for k in keep if k in meta}
    suffix = Path(path).suffix.lower() if path else ""
    fw = "qiskit"
    fmt = "python" if suffix == ".py" else "qasm" if suffix.startswith(".qasm") else None
    if suffix.startswith(".qasm") and path and Path(path).is_file():
        import re

        m = re.search(r"OPENQASM\s+(\d+)", Path(path).read_text(errors="replace"))
        fmt = "qasm3" if m and int(m.group(1)) >= 3 else "qasm2"
    try:
        v = version("qiskit")
    except PackageNotFoundError:  # pragma: no cover
        v = None
    out = {"framework": fw, "framework_version": v}
    if fmt:
        out["source_format"] = fmt
    if fmt == "qasm3":
        try:
            out["qasm3_importer_version"] = version("qiskit-qasm3-import")
        except PackageNotFoundError:  # pragma: no cover
            pass
    return out
