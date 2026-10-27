"""The same block after a plain `transpile()` with default settings.

Default `qubits_initially_zero=True` lets HighLevelSynthesis borrow the idle q4 as a
*clean* ancilla. The result is correct only if q4 really starts in |0>.
"""
from qiskit import QuantumCircuit, transpile

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("_hazard_block", Path(__file__).with_name("block.py"))
_block = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_block)
build_source = _block.build

BASIS = ["cx", "rz", "sx", "x"]


def build(qubits_initially_zero: bool = True) -> QuantumCircuit:
    t = transpile(build_source(), basis_gates=BASIS, optimization_level=1, seed_transpiler=1,
                  qubits_initially_zero=qubits_initially_zero)
    t.name = "c3x_block_compiled" if qubits_initially_zero else "c3x_block_compiled_safe"
    return t


def build_safe() -> QuantumCircuit:
    return build(qubits_initially_zero=False)
