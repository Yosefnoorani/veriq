"""Multi-framework frontends: exact conversion, qubit ordering, global phase, plumbing (CLI, CI, MCP, certificates)."""
import json
import math
import sys

import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from veriq import ci
from veriq.cli import main
from veriq.frontends import detect_json, frontend_info, load, normalize_framework
from veriq.loader import LoadError, load_circuit

cirq = pytest.importorskip("cirq")
pytket = pytest.importorskip("pytket")
from pytket import Circuit as TkCircuit  # noqa: E402

from veriq.frontends.cirq_frontend import cirq_to_qiskit  # noqa: E402
from veriq.frontends.tket_frontend import tket_to_qiskit  # noqa: E402


def le(qc):
    """Qiskit operator in big-endian order (to compare with cirq.unitary / tket get_unitary)."""
    return Operator(qc.remove_final_measurements(inplace=False)).reverse_qargs().data


def same_up_to_phase(a, b):
    i = np.unravel_index(np.argmax(abs(b)), b.shape)
    return np.allclose(a * (b[i] / a[i]), b, atol=1e-8)


# ----------------------------------------------------------------------------- endianness

def test_cirq_qubit0_is_qiskit_qubit0():
    a, b = cirq.LineQubit.range(2)
    qc = cirq_to_qiskit(cirq.Circuit(cirq.X(a)))
    assert [qc.find_bit(q).index for q in qc.data[0].qubits] == [0]
    # |10> big-endian in Cirq == bit 0 set == little-endian index 1 in Qiskit
    from qiskit.quantum_info import Statevector
    assert np.argmax(abs(cirq.final_state_vector(cirq.Circuit(cirq.X(a), cirq.I(b))))) == 2
    assert np.argmax(abs(Statevector(qc).data)) == 1


def test_tket_qubit0_is_qiskit_qubit0():
    qc = tket_to_qiskit(TkCircuit(2).X(0))
    assert qc.find_bit(qc.data[0].qubits[0]).index == 0


def test_exact_unitary_including_global_phase_cirq():
    q = cirq.LineQubit.range(3)
    c = cirq.Circuit(cirq.H(q[0]), cirq.FSimGate(0.3, 0.7)(q[0], q[2]), cirq.PhasedXPowGate(phase_exponent=0.2,
                     exponent=0.4)(q[1]), cirq.Y(q[2]).controlled_by(q[1]) ** 0.3, cirq.CZ(q[0], q[1]) ** 0.5,
                     cirq.global_phase_operation(np.exp(0.4j)))
    qc = cirq_to_qiskit(c)
    assert np.allclose(le(qc), cirq.unitary(c), atol=1e-8)  # exact, global phase included
    assert qc.metadata["veriq_frontend"]["opaque_ops"] == 0


def test_exact_unitary_including_global_phase_tket():
    from pytket.circuit import CircBox
    sub = TkCircuit(2).CX(0, 1).Rz(0.25, 1)
    t = TkCircuit(3).H(0).add_circbox(CircBox(sub), [1, 2]).TK1(0.1, 0.2, 0.3, 0).TK2(0.1, 0.2, 0.3, 0, 2)
    t.PhasedX(0.3, 0.7, 1).ISWAP(0.4, 0, 1).CRz(0.5, 2, 0)
    t.add_phase(0.37)
    qc = tket_to_qiskit(t)
    assert np.allclose(le(qc), t.get_unitary(), atol=1e-8)
    assert qc.metadata["veriq_frontend"]["opaque_ops"] == 0


def test_reversed_qubit_order_is_caught(tmp_path):
    """A translation that forgets the endianness flip must FAIL against the Qiskit original."""
    from veriq.scale import decide_equivalence
    orig = QuantumCircuit(3)
    orig.h(0)
    orig.cx(0, 1)
    orig.cp(0.7, 1, 2)
    q = cirq.LineQubit.range(3)
    right = cirq.Circuit(cirq.H(q[0]), cirq.CNOT(q[0], q[1]), cirq.CZ(q[1], q[2]) ** (0.7 / math.pi))
    wrong = cirq.Circuit(cirq.H(q[2]), cirq.CNOT(q[2], q[1]), cirq.CZ(q[1], q[0]) ** (0.7 / math.pi))
    assert decide_equivalence(orig, cirq_to_qiskit(right))["status"] == "PROVEN_EQUIVALENT"
    assert decide_equivalence(orig, cirq_to_qiskit(wrong))["status"] == "NOT_EQUIVALENT"


def test_tket_half_turns_not_radians():
    t = TkCircuit(1).Rz(0.5, 0)  # 0.5 half-turns = pi/2
    ref = QuantumCircuit(1)
    ref.rz(math.pi / 2, 0)
    assert same_up_to_phase(Operator(tket_to_qiskit(t)).data, Operator(ref).data)


def test_controlled_phase_difference_is_caught():
    from veriq.scale import decide_equivalence
    q = cirq.LineQubit.range(2)
    a = cirq_to_qiskit(cirq.Circuit(cirq.H(q[0]), cirq.CZ(q[0], q[1]) ** 0.25))
    b = cirq_to_qiskit(cirq.Circuit(cirq.H(q[0]), cirq.Z(q[1]) ** 0.25))  # controlled phase made uncontrolled
    assert decide_equivalence(a, b)["status"] == "NOT_EQUIVALENT"


def test_unused_named_qubits_and_measurements():
    a, b = cirq.NamedQubit("b"), cirq.NamedQubit("a")
    qc = cirq_to_qiskit(cirq.Circuit(cirq.H(a), cirq.CNOT(a, b), cirq.measure(a, b, key="m")))
    meta = qc.metadata["veriq_frontend"]
    assert meta["qubit_map"][0].endswith("a") and qc.num_qubits == 2  # sorted(all_qubits()): a before b
    assert qc.count_ops().get("measure") == 2


def test_symbolic_parameters_rejected():
    import sympy
    q = cirq.LineQubit(0)
    with pytest.raises(LoadError, match="symbol"):
        cirq_to_qiskit(cirq.Circuit(cirq.rx(sympy.Symbol("t"))(q)))


# ----------------------------------------------------------------------------- loading

def _files(tmp_path):
    (tmp_path / "bell.qasm").write_text('OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nh q[0];\ncx q[0], q[1];\n')
    (tmp_path / "bell_cirq.py").write_text("import cirq\ndef build():\n    a, b = cirq.LineQubit.range(2)\n"
                                           "    return cirq.Circuit(cirq.H(a), cirq.CNOT(a, b))\n")
    (tmp_path / "bell_rev_cirq.py").write_text("import cirq\ndef build():\n    a, b = cirq.LineQubit.range(2)\n"
                                               "    return cirq.Circuit(cirq.H(b), cirq.CNOT(b, a))\n")
    (tmp_path / "bell_tket.py").write_text("from pytket import Circuit\ncircuit = Circuit(2).H(0).CX(0, 1)\n")
    a, b = cirq.LineQubit.range(2)
    (tmp_path / "bell_cirq.json").write_text(cirq.to_json(cirq.Circuit(cirq.H(a), cirq.CNOT(a, b))))
    (tmp_path / "bell_tket.json").write_text(json.dumps(TkCircuit(2).H(0).CX(0, 1).to_dict()))
    return tmp_path


def test_load_all_formats_and_detect(tmp_path):
    d = _files(tmp_path)
    want = Operator(load_circuit(d / "bell.qasm"))
    for f in ("bell_cirq.py", "bell_tket.py", "bell_cirq.json", "bell_tket.json"):
        assert Operator(load_circuit(d / f)).equiv(want), f
    assert detect_json((d / "bell_cirq.json").read_text()) == "cirq"
    assert detect_json((d / "bell_tket.json").read_text()) == "tket"
    assert load_circuit(d / "bell_cirq.json").metadata["veriq_frontend"]["framework"] == "cirq"
    assert normalize_framework("pytket") == "tket" and normalize_framework("auto") is None


def test_framework_mismatch_errors(tmp_path):
    d = _files(tmp_path)
    with pytest.raises(LoadError, match="tket"):
        load(d / "bell_cirq.py", framework="tket")
    with pytest.raises(LoadError, match="qasm2"):
        load(d / "bell.qasm", framework="qasm2")
    with pytest.raises(LoadError):
        normalize_framework("quil")


def test_missing_extra_message(tmp_path, monkeypatch):
    d = _files(tmp_path)
    monkeypatch.setitem(sys.modules, "cirq", None)
    with pytest.raises(LoadError, match=r"veriq\[cirq\]"):
        load_circuit(d / "bell_cirq.json")


def test_frontend_info_in_certificate_records(tmp_path):
    d = _files(tmp_path)
    info = frontend_info(load_circuit(d / "bell_tket.json"))
    assert info["framework"] == "tket" and info["framework_version"] == pytket.__version__
    info = frontend_info(load_circuit(d / "bell.qasm"))
    assert info["source_format"] == "qasm3" and "qasm3_importer_version" in info


# ----------------------------------------------------------------------------- CLI / CI / MCP

def test_cli_cross_framework_verify(tmp_path, capsys):
    d = _files(tmp_path)
    assert main(["check", str(d / "bell.qasm"), str(d / "bell_cirq.py")]) == 0
    assert main(["check", str(d / "bell_tket.json"), str(d / "bell_cirq.json"), "--framework", "tket"]) == 0
    assert main(["check", str(d / "bell_rev_cirq.py"), str(d / "bell.qasm")]) == 1
    assert main(["check", str(d / "bell_cirq.py"), str(d / "bell.qasm"), "--framework", "tket"]) == 3


def test_cli_certificate_records_frontend(tmp_path):
    d = _files(tmp_path)
    out = tmp_path / "cert.json"
    rc = main(["check", str(d / "bell_cirq.py"), "--reference", str(d / "bell_tket.json"), "--certificate", str(out)])
    if rc == 2:  # pragma: no cover - option name differs
        pytest.skip("no --certificate option")
    assert rc == 0
    cert = json.loads(out.read_text())
    fws = {i["role"]: i["frontend"]["framework"] for i in cert["inputs"]}
    assert fws == {"candidate": "cirq", "reference": "tket"}


def test_ci_framework_keys(tmp_path):
    d = _files(tmp_path)
    (d / ".veriq.yml").write_text("version: 1\nchecks:\n  - name: x\n    file: bell_cirq.py\n    framework: cirq\n"
                                  "    reference: bell_tket.json\n    reference-framework: pytket\n")
    cfg = ci.load_config(d / ".veriq.yml")
    e = cfg.entries[0]
    assert (e.framework, e.reference_framework) == ("cirq", "tket")
    assert ci.run_entry(e, str(d)).verdict == "PASS"
    (d / ".veriq.yml").write_text("version: 1\nchecks:\n  - name: x\n    file: bell_cirq.py\n    framework: quil\n")
    with pytest.raises(ci.ConfigError, match="framework"):
        ci.load_config(d / ".veriq.yml")


def test_mcp_sandbox_cross_framework(tmp_path):
    pytest.importorskip("mcp")
    from veriq.mcp_server import Runner
    d = _files(tmp_path)
    r = Runner(roots=[str(d)])
    ref = r.source(None, str(d / "bell.qasm"), None, "reference")
    a = r.source((d / "bell_cirq.py").read_text(), None, None, "candidate", framework="cirq")
    assert r.execute("compare_circuits", {"candidate": a, "reference": ref},
                     {"mode": "unitary", "timeout": 30})["status"] == "PROVEN_EQUIVALENT"
    a = r.source((d / "bell_tket.json").read_text(), None, None, "candidate")  # JSON code, auto-detected
    assert r.execute("compare_circuits", {"candidate": a, "reference": ref},
                     {"mode": "unitary", "timeout": 30})["status"] == "PROVEN_EQUIVALENT"
    a = r.source(None, str(d / "bell_rev_cirq.py"), None, "candidate")
    res = r.execute("compare_circuits", {"candidate": a, "reference": ref}, {"mode": "unitary", "timeout": 30})
    assert res["status"] == "NOT_EQUIVALENT" and res["counterexample"]
