"""Load a Qiskit QuantumCircuit from a .py module (Qiskit, Cirq or pytket code), an OpenQASM 2/3 file, or a
Cirq / TKET JSON file. Framework conversion lives in `veriq.frontends`."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from qiskit import QuantumCircuit


class LoadError(Exception):
    """Input problem: file missing, unsupported type, unparsable."""


class BuildError(LoadError):
    """The candidate's own code failed to produce a circuit ("does not build").

    Raised when executing the module or calling its builder raises, when the requested
    builder is missing, or when it returns something that is not a QuantumCircuit.
    """

    error_type = "does not build"

    def __init__(self, message: str, exc_type: str | None = None):
        super().__init__(message)
        self.exc_type = exc_type


def load_circuit(path: str | Path, function: str | None = None, framework: str | None = None) -> QuantumCircuit:
    """Load a circuit. For .py files, `function` names a builder to call (default: build/circuit).

    `framework` (qiskit | qasm2 | qasm3 | cirq | tket, default auto-detect) forces the frontend; see
    `veriq.frontends`."""
    from .frontends import load

    return load(path, function, framework)


def _load_py(p: Path, function: str | None = None, framework: str | None = None) -> QuantumCircuit:
    """Convention: the module exposes `circuit` (a QuantumCircuit) or `build()` returning one,
    or the caller names a builder function with `function`."""
    mod_name = f"_veriq_user_{abs(hash(str(p.resolve())))}"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    if spec is None or spec.loader is None:
        raise LoadError(f"cannot import {p}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(p.parent))
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        hint = _extra_hint(exc.name)
        raise BuildError(f"error while executing {p.name}: {exc!r}{hint}", type(exc).__name__) from exc
    except Exception as exc:  # user code may raise anything
        raise BuildError(f"error while executing {p.name}: {exc!r}", type(exc).__name__) from exc
    finally:
        sys.path.pop(0)
    try:
        if function is not None:
            fn = getattr(module, function, None)
            if not callable(fn):
                raise BuildError(f"{p.name} does not define a function `{function}()`", "MissingFunction")
            qc = fn()
        elif hasattr(module, "build") and callable(module.build):
            qc = module.build()
        elif hasattr(module, "circuit"):
            qc = module.circuit
        else:
            raise BuildError(f"{p.name} must define `circuit` or a `build()` function", "MissingFunction")
    except BuildError:
        raise
    except Exception as exc:
        where = f"{function}()" if function else "build()"
        raise BuildError(f"{p.name}: {where} raised {exc!r}", type(exc).__name__) from exc
    from .frontends import from_object

    if not isinstance(qc, QuantumCircuit) or framework is not None:
        try:
            qc = from_object(qc, framework, "python", p.name)
        except LoadError:
            raise
        except Exception as exc:  # a converter failure on user objects is a build failure
            raise BuildError(f"{p.name}: cannot convert the circuit: {exc!r}", type(exc).__name__) from exc
    if not qc.name or qc.name.startswith("circuit-"):
        qc.name = p.stem
    return qc


def _load_qasm(p: Path, framework: str | None = None) -> QuantumCircuit:
    text = p.read_text()
    m = re.search(r"OPENQASM\s+(\d+)", text)
    version = int(m.group(1)) if m else 2
    if framework in ("qasm2", "qasm3") and int(framework[-1]) != (3 if version >= 3 else 2):
        raise LoadError(f"{p.name} declares OPENQASM {version}, but framework '{framework}' was requested")
    try:
        if version >= 3:
            from qiskit import qasm3

            try:
                qc = qasm3.loads(text)
            except ImportError as exc:  # qiskit.qasm3.loads needs the optional importer package
                raise LoadError("OpenQASM 3 import needs qiskit-qasm3-import: pip install 'veriq[qasm3]'") from exc
        else:
            from qiskit import qasm2

            qc = qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
    except Exception as exc:
        raise LoadError(f"cannot parse OpenQASM {version} in {p.name}: {exc}") from exc
    qc.name = p.stem
    from .frontends import frontend_info

    # Record the source format so it survives the QPY round trip out of the sandbox (for certificates).
    qc.metadata = {**(qc.metadata or {}), "veriq_frontend": frontend_info(qc, str(p))}
    return qc


def _extra_hint(module: str | None) -> str:
    root = (module or "").split(".")[0]
    extra = {"cirq": "cirq", "cirq_core": "cirq", "pytket": "tket", "qiskit_qasm3_import": "qasm3"}.get(root)
    return f" (install the optional extra: pip install 'veriq[{extra}]')" if extra else ""
