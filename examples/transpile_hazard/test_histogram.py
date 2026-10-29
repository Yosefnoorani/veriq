"""The usual test: sample the compiled block on Aer and compare histograms with the source.

This is what most notebooks and CI suites do. It PASSES for the transpile hazard
(examples/transpile_hazard), because every run starts from |0...0>.
"""
import importlib.util
from pathlib import Path

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

HAZARD = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_demo_{name}", HAZARD / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build()


def _counts(block: QuantumCircuit, shots: int = 4096) -> dict:
    qc = QuantumCircuit(block.num_qubits)
    qc.h([0, 1, 2])                       # controls in superposition
    qc.compose(block, inplace=True)
    qc.measure_all()
    sim = AerSimulator(seed_simulator=7)
    return sim.run(transpile(qc, sim), shots=shots).result().get_counts()


def test_compiled_block_matches_source_histogram():
    src, compiled = _counts(_load("block")), _counts(_load("compiled"))
    keys = set(src) | set(compiled)
    tvd = 0.5 * sum(abs(src.get(k, 0) - compiled.get(k, 0)) for k in keys) / 4096
    assert tvd < 0.05
