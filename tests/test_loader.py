import pytest
from qiskit import QuantumCircuit

from veriq.loader import LoadError, load_circuit


def test_load_py_circuit_attr(ex):
    qc = load_circuit(ex("bell_correct.py"))
    assert isinstance(qc, QuantumCircuit) and qc.num_qubits == 2


def test_load_py_build_fn(ex):
    assert load_circuit(ex("ghz_correct.py")).num_qubits == 3


def test_load_qasm2_and_qasm3(ex):
    assert load_circuit(ex("bell.qasm")).num_qubits == 2
    assert load_circuit(ex("ghz3.qasm3")).num_qubits == 3


def test_load_errors(tmp_path):
    bad = tmp_path / "nothing.py"
    bad.write_text("x = 1\n")
    with pytest.raises(LoadError):
        load_circuit(bad)
    with pytest.raises(LoadError):
        load_circuit(tmp_path / "missing.qasm")
    with pytest.raises(LoadError):
        load_circuit(tmp_path / "file.txt")
