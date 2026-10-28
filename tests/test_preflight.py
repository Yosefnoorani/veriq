"""Stage 4: `veriq preflight` (offline backend profiles, layout-aware proof, ESP estimates, go/warn/no-go)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from qiskit import QuantumCircuit, transpile

from veriq import ci
from veriq.cli import main
from veriq.preflight import (PreflightError, builtin_profiles, compact, estimate, expected_circuit,
                             fake_backend_names, load_backend, native_violations, noisy_tvd, preflight,
                             prove_compiled, to_json)

GHZ = """from qiskit import QuantumCircuit


def ghz():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    return qc


def bad():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    return qc
"""


def toy(**over):
    """3-qubit linear toy device with round numbers so ESP can be checked by hand."""
    d = {"schema": "veriq.backend/1", "name": "toy", "illustrative": True, "num_qubits": 3, "coupling": "linear",
         "gates": {"rz": {"error": 0.0, "duration": 0.0}, "sx": {"error": 0.001, "duration": 5e-8},
                   "x": {"error": 0.001, "duration": 5e-8}, "cz": {"error": 0.01, "duration": 3e-7}},
         "readout": {"error": 0.02, "duration": 1e-6}, "t1": 1e-4, "t2": 1e-4}
    d.update(over)
    return d


def ghz3():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    return qc


# ----------------------------------------------------------------------------- backends

def test_builtin_profiles_are_labelled_illustrative():
    names = builtin_profiles()
    assert {"ionq_style_25q", "quantinuum_style_20q", "braket_superconducting_style_12q"} <= set(names)
    for n in names:
        be = load_backend(n)
        assert be.source["illustrative"] is True and "NOT vendor data" in be.source["note"]


def test_fake_backend_snapshot_and_name_normalisation():
    assert "FakeTorino" in fake_backend_names()
    a, b = load_backend("fake_torino"), load_backend("FakeTorino")
    assert a.name == b.name == "fake_torino" and a.num_qubits == 133
    info = a.info()
    assert info["illustrative"] is False and "qiskit-ibm-runtime" in info["source"]
    assert info["calibration_date"] and len(info["data_sha256"]) == 64 and "snapshot" in info["note"]


@pytest.mark.parametrize("bad, msg", [
    ({"schema": "nope"}, "schema"),
    ({"schema": "veriq.backend/1"}, "num_qubits"),
    (toy(gates={"gpi": {}}), "unknown gate"),
    (toy(gates={"ccx": {}}), "only 1q/2q"),
])
def test_profile_validation(bad, msg):
    with pytest.raises(PreflightError, match=msg):
        load_backend(bad)


def test_unknown_backend_and_missing_file(tmp_path):
    with pytest.raises(PreflightError):
        load_backend("fake_nowhere")
    with pytest.raises(PreflightError, match="not found"):
        load_backend(str(tmp_path / "x.json"))


def test_profile_coupling_and_overrides():
    be = load_backend(toy(coupling={"grid": [1, 3]}, gates={**toy()["gates"],
                                                            "cz": {"error": 0.01, "overrides": {"1,2": {"error": 0.2}}}}))
    assert be.target["cz"][(1, 2)].error == 0.2 and be.target["cz"][(2, 1)].error == 0.2
    assert be.target["cz"][(0, 1)].error == 0.01 and (0, 2) not in be.target["cz"]


# ----------------------------------------------------------------------------- layout-aware proof

def test_compact_and_proof_with_routing_permutation():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 2)  # needs routing on a line
    qc.t(2)
    qc.cx(2, 1)
    be = load_backend(toy())
    tc = transpile(qc, target=be.target, optimization_level=1, seed_transpiler=1, qubits_initially_zero=False)
    comp = compact(tc, 3)
    assert sorted(comp["perm"]) == list(range(len(comp["physical"])))
    assert prove_compiled(qc, comp)["status"] == "proven"
    # tamper the compiled circuit -> refuted (with counterexample)
    bad = comp["circuit"].copy()
    bad.x(0)
    r = prove_compiled(qc, {**comp, "circuit": bad})
    assert r["status"] == "refuted"
    # a wrong permutation is refuted too (the layout is part of the claim)
    if comp["perm"] != list(range(len(comp["perm"]))):
        assert prove_compiled(qc, {**comp, "perm": list(range(len(comp["perm"])))})["status"] == "refuted"


def test_expected_circuit_places_logical_qubits():
    qc = QuantumCircuit(2)
    qc.x(0)
    e = expected_circuit(qc, 3, [2, 0], [0, 1, 2])
    assert e.num_qubits == 3 and [e.find_bit(i.qubits[0]).index for i in e.data if i.operation.name == "x"] == [2]


def test_native_violations_detected():
    be = load_backend(toy())
    qc = QuantumCircuit(3)
    qc.h(0)       # not native (toy has rz/sx/x/cz)
    qc.cz(0, 2)   # not coupled on the line
    v = native_violations(qc, be.target)
    assert any("h" in s for s in v) and any("cz" in s for s in v)


# ----------------------------------------------------------------------------- estimates

def test_esp_arithmetic_by_hand():
    be = load_backend(toy())
    qc = QuantumCircuit(2)
    qc.sx(0)
    qc.cz(0, 1)
    e = estimate(qc, be, 2, [0, 1])
    assert e["esp_gates"] == pytest.approx(0.999 * 0.99)
    assert e["esp_readout"] == pytest.approx(0.98 ** 2) and e["readout_assumed"]
    assert e["esp"] == pytest.approx(0.999 * 0.99 * 0.98 ** 2)
    assert e["duration_s"] == pytest.approx(5e-8 + 3e-7 + 1e-6)
    assert e["two_qubit_gates"] == 1 and e["one_qubit_gates"] == 1
    assert e["idle_factor"] == pytest.approx(math.exp(-5e-8 / 1e-4))  # q1 idles while sx runs on q0


def test_noise_aware_layout_avoids_bad_qubit():
    ro = [0.01, 0.01, 0.01, 0.01, 0.5]
    be = load_backend(toy(num_qubits=5, readout={"error": ro, "duration": 1e-6}))
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    r = preflight(qc, be, seeds=2, levels=(3,))
    assert 4 not in r["layout"]["physical_qubits"]
    assert r["layout_selection"]["best_esp"] >= r["layout_selection"]["worst_esp"]


def test_noisy_tvd_small_and_ideal_backend_zero():
    be = load_backend(toy())
    r = preflight(ghz3(), be, seeds=1, levels=(1,), noisy_sim=True, shots=2000)
    ns = r["noisy_simulation"]
    assert ns["ran"] and 0 < ns["tvd"] < 0.5
    zero = load_backend(toy(gates={k: {"error": 0.0} for k in toy()["gates"]}, readout={"error": 0.0}))
    r0 = preflight(ghz3(), zero, seeds=1, levels=(1,), noisy_sim=True, shots=4000)
    assert r0["noisy_simulation"]["tvd"] < 0.05 and r0["estimate"]["esp"] == 1.0


# ----------------------------------------------------------------------------- gate

def test_gate_go_warn_nogo():
    be = load_backend(toy())
    assert preflight(ghz3(), be, seeds=1, levels=(1,))["gate"] == "go"
    r = preflight(ghz3(), be, seeds=1, levels=(1,), warn_esp=0.99)
    assert r["gate"] == "warn" and r["verdict"] == "INCONCLUSIVE"
    r = preflight(ghz3(), be, seeds=1, levels=(1,), max_cx=1)
    assert r["gate"] == "no-go" and r["verdict"] == "FAIL"
    r = preflight(ghz3(), be, seeds=1, levels=(1,), max_duration=1e-9)
    assert r["gate"] == "no-go"
    big = QuantumCircuit(4)
    assert preflight(big, be)["gate"] == "no-go"


def test_reference_mismatch_is_nogo():
    ref = QuantumCircuit(3)
    ref.h(0)
    ref.cx(0, 1)
    r = preflight(ghz3(), load_backend(toy()), reference=ref, seeds=1, levels=(1,))
    st = {c["name"]: c["status"] for c in r["checks"]}
    assert st["Input vs reference"] == "FAIL" and r["gate"] == "no-go"
    assert json.dumps(to_json(r))  # serialisable


def test_fake_torino_end_to_end():
    r = preflight(ghz3(), "fake_torino", seeds=2, levels=(1, 3))
    assert r["gate"] == "go" and r["proof"]["status"] == "proven"
    assert not native_violations(r["compiled_circuit"], load_backend("fake_torino").target)
    assert 0.5 < r["estimate"]["esp"] < 1


# ----------------------------------------------------------------------------- CLI, certificate, CI

def test_cli_exit_codes_and_certificate(tmp_path):
    src = tmp_path / "c.py"
    src.write_text(GHZ)
    prof = tmp_path / "toy.json"
    prof.write_text(json.dumps(toy()))
    cert = tmp_path / "pf.cert.json"
    assert main(["preflight", str(src), "-f", "ghz", "-b", str(prof), "--seeds", "1", "--levels", "1",
                 "--json", str(tmp_path / "pf.json"), "--certificate", str(cert), "-q"]) == 0
    j = json.loads((tmp_path / "pf.json").read_text())
    assert j["gate"] == "go"
    c = json.loads(cert.read_text())
    assert c["kind"] == "preflight" and c["preflight"]["gate"] == "go"
    assert main(["cert", "verify", str(cert), "--allow-unsigned", "--recheck"]) == 0
    assert main(["preflight", str(src), "-f", "ghz", "-b", str(prof), "--warn-esp", "0.99", "--seeds", "1",
                 "--levels", "1", "-q"]) == 2
    assert main(["preflight", str(src), "-f", "ghz", "-b", str(prof), "-r", str(src), "--reference-function",
                 "bad", "--seeds", "1", "--levels", "1", "-q"]) == 1
    assert main(["preflight", str(src), "-f", "ghz", "-b", "fake_nowhere", "-q"]) == 3


def test_ci_preflight_key(tmp_path):
    (tmp_path / "c.py").write_text(GHZ)
    (tmp_path / "toy.json").write_text(json.dumps(toy()))
    (tmp_path / ".veriq.yml").write_text("""
checks:
  - name: ok
    file: c.py
    function: ghz
    preflight: toy.json
  - name: strict
    file: c.py
    function: ghz
    expect: fail
    preflight: {backend: toy.json, max-cx: 1, seeds: 1, levels: [1]}
""")
    cfg = ci.load_config(tmp_path / ".veriq.yml")
    assert cfg.entries[1].preflight == {"backend": "toy.json", "max-cx": 1, "seeds": 1, "levels": [1]}
    assert "toy.json" in cfg.entries[0].paths()
    out = tmp_path / "certs"
    assert main(["ci", "--config", str(tmp_path / ".veriq.yml"), "--certificates", str(out),
                 "--markdown", str(tmp_path / "ci.md"), "-q"]) == 0
    md = (tmp_path / "ci.md").read_text()
    assert "preflight GO on toy" in md and "preflight NO-GO on toy" in md
    c = json.loads((out / "strict.cert.json").read_text())
    assert c["verdict"] == "FAIL" and c["preflight"]["gate"] == "no-go"
    assert main(["cert", "verify", str(out / "strict.cert.json"), "--allow-unsigned", "--recheck"]) == 0


@pytest.mark.parametrize("bad", ["{backend: 3}", "{backend: x, levels: [7]}", "{backend: x, colour: red}", "[1]"])
def test_ci_preflight_key_validation(tmp_path, bad):
    (tmp_path / "c.py").write_text(GHZ)
    (tmp_path / ".veriq.yml").write_text(f"checks:\n  - file: c.py\n    function: ghz\n    preflight: {bad}\n")
    with pytest.raises(ci.ConfigError):
        ci.load_config(tmp_path / ".veriq.yml")
