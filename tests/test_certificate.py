"""Signed verification certificates: build, sign, verify, tamper detection, INCONCLUSIVE never PASS."""
import copy
import json
import os
import stat
from pathlib import Path

import pytest
from qiskit import QuantumCircuit

from veriq import certificate as C
from veriq.cli import main
from veriq.models import CheckResult, Report, Status
from veriq.runner import run_checks

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    """Keys are generated at test time; none are ever stored in the repository."""
    d = tmp_path_factory.mktemp("keys")
    C.generate_keypair(d / "k.key")
    C.generate_keypair(d / "other.key")
    return {"priv": C.load_private_key(str(d / "k.key")), "pub": C.load_public_key(str(d / "k.pub")),
            "other_pub": C.load_public_key(str(d / "other.pub")), "dir": d}


def _bell():
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    return qc


@pytest.fixture(scope="module")
def qft_cert():
    from veriq.loader import load_circuit
    cand, ref = load_circuit(str(EX / "qft_correct.py")), load_circuit(str(EX / "qft_reference.py"))
    rep = run_checks(cand, reference=ref)
    return C.certificate_from_report(rep, candidate_path=str(EX / "qft_correct.py"),
                                     reference_path=str(EX / "qft_reference.py"), options={})


@pytest.fixture(scope="module")
def ghz_fail_cert():
    from veriq.loader import load_circuit
    cand, ref = load_circuit(str(EX / "ghz_buggy.py")), load_circuit(str(EX / "ghz_correct.py"))
    rep = run_checks(cand, reference=ref, shots=512, mode="state")
    return C.certificate_from_report(rep, candidate_path=str(EX / "ghz_buggy.py"),
                                     reference_path=str(EX / "ghz_correct.py"), options={"mode": "state", "shots": 512})


def _reasons(v):
    return " | ".join(f"{r['check']}: {r['detail']}" for r in v["results"] if r["ok"] is False)


# ------------------------------------------------------------------ content

def test_pass_certificate_content(qft_cert):
    c = qft_cert
    assert c["schema"] == "veriq.certificate/1" and c["kind"] == "verify"
    assert c["verdict"] == "PASS" and c["claim"] == "PROVEN_EQUIVALENT"
    assert c["proof"]["status"] == "proven" and c["proof"]["method"]
    roles = [i["role"] for i in c["inputs"]]
    assert roles == ["candidate", "reference"]
    for i in c["inputs"]:
        assert len(i["source_sha256"]) == 64 and len(i["canonical_sha256"]) == 64 and i["canonical"]
        assert i["source_sha256"] == C.sha256_file(i["path"])
    a = c["assumptions"]
    for k in ("mode", "initial_state", "qubits_initially_zero", "allowed_gates", "coupling",
              "permutation_allowed", "black_boxes_allowed"):
        assert k in a
    for k in ("veriq", "qiskit", "mqt.qcec", "python"):
        assert c["tool_versions"].get(k)
    assert c["timestamps"]["issued"].endswith("Z") and c["counterexample"] is None
    assert C.semantic_problems(c) == []


def test_fail_certificate_has_counterexample(ghz_fail_cert):
    c = ghz_fail_cert
    assert c["verdict"] == "FAIL" and c["claim"] == "NOT_EQUIVALENT"
    assert c["counterexample"] is not None


def test_canonical_hash_is_deterministic():
    def build():
        sub = QuantumCircuit(3, name="block")
        sub.h(0)
        sub.ccx(0, 1, 2)
        qc = QuantumCircuit(3)
        qc.append(sub.to_gate(), [0, 1, 2])
        qc.append(sub.to_gate(), [2, 1, 0])
        return qc
    a, b = build(), build()
    assert C.circuit_record("x", a)["canonical_sha256"] == C.circuit_record("x", b)["canonical_sha256"]
    assert C.normalize_qasm("gate foo_123 q { h q; }\nfoo_123 q[0];") == "gate foo_v0 q { h q; }\nfoo_v0 q[0];"


# ------------------------------------------------------------------ signing and tamper detection

def test_sign_and_verify(qft_cert, keys):
    s = C.sign_certificate(qft_cert, keys["priv"])
    v = C.verify_certificate(s, keys["pub"], circuits=[str(EX / "qft_correct.py"), str(EX / "qft_reference.py")])
    assert v["ok"] and v["trusted"], _reasons(v)
    v = C.verify_certificate(s)  # embedded key: integrity only
    assert v["ok"] and not v["trusted"]


def test_altered_verdict_detected(ghz_fail_cert, keys):
    s = C.sign_certificate(ghz_fail_cert, keys["priv"])
    t = copy.deepcopy(s)
    t["verdict"] = "PASS"
    t["claim"] = "PROVEN_EQUIVALENT"
    v = C.verify_certificate(t, keys["pub"])
    assert not v["ok"] and "modified after signing" in _reasons(v)


def test_altered_metrics_or_assumptions_detected(qft_cert, keys):
    s = C.sign_certificate(qft_cert, keys["priv"])
    t = copy.deepcopy(s)
    t["assumptions"]["qubits_initially_zero"] = not t["assumptions"]["qubits_initially_zero"]
    assert not C.verify_certificate(t, keys["pub"])["ok"]


def test_altered_circuit_detected(qft_cert, keys):
    s = C.sign_certificate(qft_cert, keys["priv"])
    v = C.verify_certificate(s, keys["pub"], circuits=[str(EX / "qft_buggy.py"), str(EX / "qft_reference.py")])
    assert not v["ok"] and "candidate" in _reasons(v)


def test_altered_circuit_file_detected(qft_cert, keys, tmp_path):
    f = tmp_path / "qft_correct.py"
    f.write_text((EX / "qft_correct.py").read_text() + "\n# harmless edit\n")
    s = C.sign_certificate(qft_cert, keys["priv"])
    v = C.verify_certificate(s, keys["pub"], circuits=[str(f), str(EX / "qft_reference.py")])
    assert not v["ok"] and "source" in _reasons(v)


def test_altered_embedded_circuit_detected(qft_cert, keys):
    s = C.sign_certificate(qft_cert, keys["priv"])
    t = copy.deepcopy(s)
    t["inputs"][0]["canonical"] = t["inputs"][0]["canonical"].replace("cp(", "cp(0.1+", 1)
    assert not C.verify_certificate(t, keys["pub"])["ok"]
    # and re-signing the tampered content is refused (embedded QASM no longer matches its hash)
    with pytest.raises(C.CertificateError):
        C.sign_certificate({k: v for k, v in t.items() if k != "signature"}, keys["priv"])


def test_wrong_key_rejected(qft_cert, keys):
    s = C.sign_certificate(qft_cert, keys["priv"])
    v = C.verify_certificate(s, keys["other_pub"])
    assert not v["ok"] and not v["trusted"] and "not by the supplied key" in _reasons(v)


def test_resigned_by_attacker_not_trusted(qft_cert, keys):
    """Replacing the signature with an attacker's key passes integrity but not the pinned key."""
    priv2 = C.load_private_key(str(keys["dir"] / "other.key"))
    s = C.sign_certificate(qft_cert, priv2)
    assert C.verify_certificate(s)["ok"]
    assert not C.verify_certificate(s, keys["pub"])["ok"]


def test_unsigned_rejected_unless_allowed(qft_cert):
    assert not C.verify_certificate(qft_cert)["ok"]
    v = C.verify_certificate(qft_cert, allow_unsigned=True)
    assert v["ok"] and not v["trusted"]


# ------------------------------------------------------------------ INCONCLUSIVE is never PASS

def _inconclusive_report():
    checks = [CheckResult("Transpile integrity", Status.PASS, "ok"),
              CheckResult("Reference equivalence", Status.INCONCLUSIVE, "QCEC timed out; no proof",
                          {"method": "qcec", "qcec_result": "no_information"})]
    return Report(target="x", reference="y", verdict=Status.INCONCLUSIVE, checks=checks, metrics={},
                  circuits={"candidate": _bell(), "reference": _bell()})


def test_inconclusive_certificate_claims_nothing(keys):
    c = C.certificate_from_report(_inconclusive_report())
    assert c["verdict"] == "INCONCLUSIVE" and c["claim"] == "NONE" and c["proof"]["status"] == "undecided"
    s = C.sign_certificate(c, keys["priv"])
    v = C.verify_certificate(s, keys["pub"])
    assert v["ok"] and v["verdict"] == "INCONCLUSIVE" and v["claim"] == "NONE"


def test_inconclusive_report_cannot_be_built_as_pass():
    rep = _inconclusive_report()
    rep.verdict = Status.PASS  # a buggy caller claiming PASS
    with pytest.raises(C.CertificateError, match="not every applicable check passed"):
        C.certificate_from_report(rep)


def test_inconclusive_forged_to_pass_rejected(keys):
    c = C.certificate_from_report(_inconclusive_report())
    forged = dict(c, verdict="PASS", claim="PROVEN_EQUIVALENT", proof=dict(c["proof"], status="proven"))
    with pytest.raises(C.CertificateError):
        C.sign_certificate(forged, keys["priv"])
    # even if an attacker signs it with their own crypto, verification still fails on semantics
    s = C.sign_certificate(c, keys["priv"])
    s.update(verdict="PASS", claim="PROVEN_EQUIVALENT", proof=dict(c["proof"], status="proven"))
    payload = C.payload_of(s)
    import base64
    s["signature"] = dict(s["signature"], payload_sha256=C.sha256_bytes(payload),
                          value=base64.b64encode(keys["priv"].sign(payload)).decode())
    v = C.verify_certificate(s, keys["pub"])
    assert not v["ok"] and "semantics" in _reasons(v)


def test_probably_equivalent_is_not_a_proof():
    checks = [CheckResult("Reference equivalence", Status.PASS, "simulation agreed",
                          {"method": "statevector sampling", "probably_equivalent": True})]
    rep = Report(target="x", reference="y", verdict=Status.PASS, checks=checks, metrics={},
                 circuits={"candidate": _bell(), "reference": _bell()})
    c = C.certificate_from_report(rep)
    assert c["claim"] == "CHECKS_PASSED_NO_PROOF" and c["proof"]["status"] == "undecided"


def test_no_reference_is_not_a_proof():
    rep = run_checks(_bell(), expect={"00": 0.5, "11": 0.5}, shots=512)
    c = C.certificate_from_report(rep, options={})
    assert c["verdict"] == "PASS" and c["claim"] == "CHECKS_PASSED_NO_PROOF" and c["proof"]["status"] == "none"


# ------------------------------------------------------------------ recheck

def test_recheck_from_files_and_embedded(qft_cert, keys):
    s = C.sign_certificate(qft_cert, keys["priv"])
    v = C.verify_certificate(s, keys["pub"], recheck=True)  # embedded canonical QASM
    assert v["ok"], _reasons(v)
    v = C.verify_certificate(s, keys["pub"], circuits=[str(EX / "qft_correct.py"), str(EX / "qft_reference.py")],
                             recheck=True)
    assert v["ok"], _reasons(v)


def test_recheck_catches_wrong_but_consistent_certificate(qft_cert, keys):
    """A self-consistent certificate whose embedded circuit is actually buggy fails --recheck."""
    from veriq.loader import load_circuit
    bad = C.circuit_record("candidate", load_circuit(str(EX / "qft_buggy.py")))
    c = copy.deepcopy(qft_cert)
    c["inputs"][0] = dict(bad, path=None)
    s = C.sign_certificate(c, keys["priv"])
    assert C.verify_certificate(s, keys["pub"])["ok"]  # integrity alone cannot know
    v = C.verify_certificate(s, keys["pub"], recheck=True)
    assert not v["ok"] and "recheck" in _reasons(v)


# ------------------------------------------------------------------ CLI

def test_cli_keygen_check_certify_verify(tmp_path):
    key = tmp_path / "veriq-signing.key"
    assert main(["keygen", "-o", str(key)]) == 0
    assert stat.S_IMODE(os.stat(key).st_mode) == 0o600
    assert (tmp_path / "veriq-signing.pub").exists()
    assert main(["keygen", "-o", str(key)]) != 0  # no silent overwrite
    cert = tmp_path / "c.json"
    code = main(["check", str(EX / "qft_correct.py"), "-r", str(EX / "qft_reference.py"),
                 "--certificate", str(cert), "-q"])
    assert code == 0 and "signature" not in json.loads(cert.read_text())
    pub = str(tmp_path / "veriq-signing.pub")
    assert main(["cert", "verify", str(cert), "-q"]) == 1  # unsigned
    assert main(["cert", "verify", str(cert), "--allow-unsigned", "-q"]) == 0
    assert main(["certify", str(cert), "--key", str(key)]) == 0
    out = tmp_path / "v.json"
    assert main(["cert", "verify", str(cert), "--key", pub, "--circuit", str(EX / "qft_correct.py"),
                 "--circuit", str(EX / "qft_reference.py"), "--json", str(out), "-q"]) == 0
    assert json.loads(out.read_text())["trusted"] is True
    assert main(["cert", "verify", str(cert), "--key", pub, "--circuit", str(EX / "qft_buggy.py"), "-q"]) == 1
    d = json.loads(cert.read_text())
    d["verdict"] = "FAIL"
    cert.write_text(json.dumps(d))
    assert main(["cert", "verify", str(cert), "--key", pub, "-q"]) == 1
    assert main(["cert", "verify", str(tmp_path / "missing.json"), "-q"]) == 3


def test_cli_sign_key_from_env(tmp_path, monkeypatch):
    C.generate_keypair(tmp_path / "k.key")
    monkeypatch.setenv("VERIQ_SIGNING_KEY", (tmp_path / "k.key").read_text())  # PEM text, as from a CI secret
    cert = tmp_path / "c.json"
    assert main(["check", str(EX / "ghz_buggy.py"), "-r", str(EX / "ghz_correct.py"), "--mode", "state",
                 "--shots", "256", "--certificate", str(cert), "-q"]) == 1
    d = json.loads(cert.read_text())
    assert d["verdict"] == "FAIL" and d["signature"]["alg"] == "Ed25519"
    assert main(["cert", "verify", str(cert), "--key", str(tmp_path / "k.pub"), "-q"]) == 0


def test_optimize_certificate(tmp_path, keys):
    cert = tmp_path / "o.json"
    code = main(["optimize", str(EX / "qft_reference.py"), "--certificate", str(cert), "-q"])
    assert code == 0
    d = json.loads(cert.read_text())
    assert d["kind"] == "optimize" and [i["role"] for i in d["inputs"]] == ["input", "output"]
    assert d["verdict"] == "PASS" and d["claim"] == "PROVEN_EQUIVALENT"
    s = C.sign_certificate(d, keys["priv"])
    v = C.verify_certificate(s, keys["pub"], recheck=True)
    assert v["ok"], _reasons(v)


def test_ci_certificates(tmp_path, keys):
    for f in ("qft_correct.py", "qft_buggy.py", "qft_reference.py"):
        (tmp_path / f).write_text((EX / f).read_text())
    cfg = tmp_path / ".veriq.yml"
    cfg.write_text("""
version: 1
report-dir: out
checks:
  - name: qft_ok
    file: qft_correct.py
    reference: qft_reference.py
  - name: qft_bug
    file: qft_buggy.py
    reference: qft_reference.py
    expect: FAIL
""")
    js = tmp_path / "s.json"
    go = tmp_path / "gh_out"
    code = main(["ci", "-c", str(cfg), "-q", "--certificates", "--sign-key", str(keys["dir"] / "k.key"),
                 "--json", str(js), "--github-output", str(go)])
    assert code == 0
    cdir = tmp_path / "out" / "certificates"
    ok = json.loads((cdir / "qft_ok.cert.json").read_text())
    bug = json.loads((cdir / "qft_bug.cert.json").read_text())
    assert ok["claim"] == "PROVEN_EQUIVALENT" and bug["claim"] == "NOT_EQUIVALENT"
    assert bug["ci"]["expect"] == "FAIL" and bug["ci"]["as_expected"] is True
    assert ok["inputs"][0]["path"] == "qft_correct.py"  # repo-relative
    for c in (ok, bug):
        assert C.verify_certificate(c, keys["pub"])["ok"]
    assert json.loads(js.read_text())["certificates"]["errors"] == 0
    assert "certificate-dir=" in go.read_text()


def test_mcp_tool_returns_unsigned_certificate():
    from veriq import tools
    out = tools.verify_circuit(_bell(), reference=_bell(), shots=256, certificate=True,
                               sources={"candidate": {"source_sha256": "ab" * 32}})
    c = out["certificate"]
    assert c["claim"] == "PROVEN_EQUIVALENT" and "signature" not in c
    assert c["inputs"][0]["source_sha256"] == "ab" * 32
    assert C.verify_certificate(c, allow_unsigned=True)["ok"]
    assert "certificate" not in tools.verify_circuit(_bell(), reference=_bell(), shots=256)


def test_gitignore_blocks_private_keys():
    gi = (ROOT / ".gitignore").read_text()
    assert "*.key" in gi and "*.pem" in gi


def test_proven_but_inconclusive_claims_nothing(keys):
    """Proof succeeded but another check was borderline: verdict INCONCLUSIVE, claim NONE, not PASS."""
    checks = [CheckResult("Reference equivalence", Status.PASS, "proved", {"method": "qcec"}),
              CheckResult("Statistical test (Aer)", Status.INCONCLUSIVE, "borderline")]
    rep = Report(target="x", reference="y", verdict=Status.INCONCLUSIVE, checks=checks, metrics={},
                 circuits={"candidate": _bell(), "reference": _bell()})
    c = C.certificate_from_report(rep)
    assert c["proof"]["status"] == "proven" and c["claim"] == "NONE"
    with pytest.raises(C.CertificateError):
        C.sign_certificate(dict(c, claim="PROVEN_EQUIVALENT"), keys["priv"])
