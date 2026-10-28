"""Verification certificates: a self-describing JSON record of one Veriq result, optionally Ed25519-signed.

A certificate binds a verdict to the exact circuits that were checked (sha256 of the source file and of a
canonical OpenQASM serialization), the assumptions the verdict depends on, the proof method and engine,
the tool versions, and, for a FAIL, the counterexample. `verify_certificate` checks the signature,
re-hashes the embedded and (optionally) the on-disk circuits, enforces the semantic rules below, and can
re-run the proof.

Semantic rules (enforced when building, signing and verifying):
  * verdict PASS requires every recorded, applicable check to be PASS (an INCONCLUSIVE check can never
    be part of a PASS certificate);
  * claim PROVEN_EQUIVALENT requires verdict PASS and a proof whose status is "proven" by a decision
    procedure (never PROBABLY_EQUIVALENT / simulation-only evidence);
  * claim NOT_EQUIVALENT requires verdict FAIL and a refuted proof.

Signing is over the canonical JSON of the certificate without its `signature` member
(UTF-8, sorted keys, separators (",", ":"), ASCII-escaped). Private keys never enter a certificate.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "veriq.certificate/1"
SIG_ALG = "Ed25519"
KEY_ENV = "VERIQ_SIGNING_KEY"              # PEM text, or a path to a PEM file
PASSPHRASE_ENV = "VERIQ_SIGNING_KEY_PASSPHRASE"
MAX_EMBED_QASM = 512_000                   # bytes; larger circuits are hashed but not embedded

EQ_CHECKS = ("Reference equivalence", "State equivalence (from |0...0>)")
PROOF_METHODS = {"qcec", "operator", "clifford", "clifford_tableau", "tableau", "mps_exact", "partition",
                 "dense", "exact"}


class CertificateError(Exception):
    """Malformed certificate, bad key, or a semantic rule violation."""


# ----------------------------------------------------------------------------- hashing / serialization

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


_GATE_DEF = re.compile(r"^\s*gate\s+([A-Za-z_][A-Za-z0-9_]*?)_(\d+)\b", re.M)


def normalize_qasm(text: str) -> str:
    """Make exporter output deterministic: Qiskit names custom gate definitions `<name>_<id(obj)>` /
    `circuit_<counter>`, which change from run to run. Rename them `<name>_v<k>` in definition order."""
    mapping: dict[str, str] = {}
    for m in _GATE_DEF.finditer(text):
        full = f"{m.group(1)}_{m.group(2)}"
        if full not in mapping:
            mapping[full] = f"{m.group(1)}_v{len(mapping)}"
    if not mapping:
        return text
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)) + r")\b")
    return pat.sub(lambda m: mapping[m.group(1)], text)


def canonical_qasm(qc) -> tuple[str, str]:
    """(format, text): OpenQASM 2 when the exporter supports the circuit, else OpenQASM 3; normalized."""
    from qiskit import qasm2, qasm3

    try:
        return "qasm2", normalize_qasm(qasm2.dumps(qc))
    except Exception:  # noqa: BLE001 - qasm2 cannot express every circuit
        return "qasm3", normalize_qasm(qasm3.dumps(qc))


def qpy_sha256(qc) -> str | None:
    try:
        from qiskit import qpy

        buf = io.BytesIO()
        qpy.dump(qc, buf)
        return sha256_bytes(buf.getvalue())
    except Exception:  # noqa: BLE001
        return None


def circuit_record(role: str, qc, path: str | None = None, function: str | None = None,
                   source_text: str | None = None) -> dict[str, Any]:
    """Hashes (and embedded canonical QASM) for one input or output circuit."""
    rec: dict[str, Any] = {"role": role, "path": path, "function": function}
    if path and Path(path).is_file():
        rec["source_sha256"] = sha256_file(path)
    elif source_text is not None:
        rec["source_sha256"] = sha256_bytes(source_text.encode())
    else:
        rec["source_sha256"] = None
    if qc is None:
        rec.update(canonical=None, canonical_sha256=None, qpy_sha256=None, num_qubits=None)
        return rec
    fmt, text = canonical_qasm(qc)
    rec.update(num_qubits=qc.num_qubits, canonical_format=fmt, canonical_sha256=sha256_bytes(text.encode()),
               qpy_sha256=qpy_sha256(qc), canonical=text if len(text.encode()) <= MAX_EMBED_QASM else None)
    return rec


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()


def payload_of(cert: dict[str, Any]) -> bytes:
    return canonical_json({k: v for k, v in cert.items() if k != "signature"})


# ----------------------------------------------------------------------------- versions / time

def tool_versions() -> dict[str, str]:
    from importlib.metadata import version

    out = {}
    for pkg in ("veriq", "qiskit", "qiskit-aer", "mqt.qcec", "cryptography"):
        try:
            out[pkg] = version(pkg)
        except Exception:  # noqa: BLE001
            out[pkg] = "?"
    out["python"] = platform.python_version()
    out["platform"] = f"{sys.platform}-{platform.machine()}"
    return out


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ----------------------------------------------------------------------------- building

def _proof_from_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    eq = next((c for c in checks if c["name"] in EQ_CHECKS), None)
    if eq is None or eq["status"] == "SKIPPED":
        return {"status": "none", "check": None, "reason": "no reference given: nothing was proven"}
    ev = eq.get("evidence") or {}
    status = {"PASS": "proven", "FAIL": "refuted"}.get(eq["status"], "undecided")
    if status == "proven" and (ev.get("probably_equivalent") or "PROBABLY" in str(ev.get("scale_status", ""))):
        status = "undecided"  # defensive: simulation-only evidence is never a proof
    keep = ("method", "engine", "qcec_result", "qcec_check_time_s", "fallback", "scale_status", "strategy",
            "strategies", "tiers", "result")
    return {"status": status, "check": eq["name"], "method": ev.get("method"), "engine": ev.get("engine"),
            "engine_details": {k: ev[k] for k in keep if k in ev}, "summary": eq.get("summary")}


def _claim(verdict: str, proof_status: str) -> str:
    if verdict == "PASS" and proof_status == "proven":
        return "PROVEN_EQUIVALENT"
    if verdict == "FAIL" and proof_status == "refuted":
        return "NOT_EQUIVALENT"
    if verdict == "PASS":
        return "CHECKS_PASSED_NO_PROOF"
    if verdict == "FAIL":
        return "CHECK_FAILED"
    return "NONE"


def _base(kind: str, verdict: str, inputs: list[dict], assumptions: dict, proof: dict, metrics: dict,
          checks: list[dict], counterexample: Any, started: str | None, seconds: float | None,
          extra: dict | None = None) -> dict[str, Any]:
    cert = {
        "schema": SCHEMA,
        "kind": kind,
        "verdict": verdict,
        "claim": _claim(verdict, proof.get("status", "none")),
        "inputs": inputs,
        "assumptions": assumptions,
        "proof": proof,
        "checks": checks,
        "metrics": metrics,
        "counterexample": counterexample if verdict == "FAIL" else None,
        "tool_versions": tool_versions(),
        "timestamps": {"started": started, "issued": utc_now(),
                       "seconds": None if seconds is None else round(seconds, 3)},
    }
    if extra:
        cert.update(extra)
    problems = semantic_problems(cert)
    if problems:
        raise CertificateError("refusing to build an inconsistent certificate: " + "; ".join(problems))
    return cert


def certificate_from_report(report, *, kind: str = "verify", candidate_path: str | None = None,
                            reference_path: str | None = None, function: str | None = None,
                            reference_function: str | None = None, options: dict[str, Any] | None = None,
                            candidate_source: str | None = None, reference_source: str | None = None,
                            started: str | None = None) -> dict[str, Any]:
    """Certificate for a `run_checks` Report (CLI check/verify, CI entry, MCP verify_circuit)."""
    rd = report.to_dict() if hasattr(report, "to_dict") else dict(report)
    circs = getattr(report, "circuits", {}) or {}
    o = dict(options or {})
    mode = o.get("mode", "unitary")
    inputs = [circuit_record("candidate", circs.get("candidate"), candidate_path, function, candidate_source)]
    if reference_path is not None or circs.get("reference") is not None or reference_source is not None:
        inputs.append(circuit_record("reference", circs.get("reference"), reference_path, reference_function,
                                     reference_source))
    checks = [{"name": c["name"], "status": c["status"], "summary": c["summary"]} for c in rd["checks"]]
    ti = next((c for c in rd["checks"] if c["name"] == "Transpile integrity"), None)
    assumptions = {
        "equivalence": ("same state prepared from |0...0>, up to global phase" if mode == "state"
                        else "same unitary on every input, up to global phase"),
        "mode": mode,
        "initial_state": "|0...0>" if mode == "state" else "any",
        "qubits_initially_zero": mode == "state",
        "transpile_check_qubits_initially_zero": False if ti else None,
        "allowed_gates": o.get("allowed_gates"),
        "coupling": o.get("coupling"),
        "coupling_scope": "circuit as written (before transpilation)" if o.get("coupling") else None,
        "permutation_allowed": False,
        "black_boxes_allowed": not o.get("no_black_boxes", False),
        "measurements": "final measurements ignored for equivalence; mid-circuit measurement/reset -> INCONCLUSIVE",
        "backend": o.get("backend"),
        "statistical": {k: o[k] for k in ("shots", "seed") if k in o},
        "expect": o.get("expect"),
        "timeout_s": o.get("timeout"),
    }
    eq = next((c for c in rd["checks"] if c["name"] in EQ_CHECKS), None)
    cex = (eq or {}).get("evidence", {}).get("counterexample") if eq else None
    if rd["verdict"] == "FAIL" and cex is None:
        failing = [c for c in rd["checks"] if c["status"] == "FAIL"]
        cex = {"failing_checks": [{"name": c["name"], "summary": c["summary"],
                                   "evidence": _small(c.get("evidence"))} for c in failing]}
    metrics = _small(rd.get("metrics") or {})
    return _base(kind, rd["verdict"], inputs, assumptions, _proof_from_checks(rd["checks"]), metrics, checks,
                 cex, started, rd.get("seconds"))


def certificate_from_optimize(res: dict[str, Any], source_qc, *, path: str | None = None,
                              function: str | None = None, options: dict[str, Any] | None = None,
                              started: str | None = None) -> dict[str, Any]:
    """Certificate for `veriq optimize`: the output circuit is proven equivalent to the input."""
    o = dict(options or {})
    best = res.get("best")
    inputs = [circuit_record("input", source_qc, path, function)]
    if res.get("best_circuit") is not None:
        inputs.append(circuit_record("output", res["best_circuit"]))
    mode = res.get("mode", "unitary")
    layout = bool(o.get("coupling")) or bool(o.get("allow_permutation"))
    if best:
        proof = {"status": "proven" if best.get("status") == "PROVEN_EQUIVALENT" else "undecided",
                 "check": "output vs input", "method": best.get("method"), "engine": "veriq.scale",
                 "engine_details": {"proof_seconds": best.get("proof_seconds"), "config": best.get("config")},
                 "summary": f"best candidate {best.get('config')} proven {best.get('status')}"}
        verdict = "PASS" if proof["status"] == "proven" else "INCONCLUSIVE"
    else:
        proof = {"status": "undecided", "check": "output vs input", "method": None, "engine": "veriq.scale",
                 "engine_details": {}, "summary": "no candidate could be proven equivalent; nothing returned"}
        verdict = "INCONCLUSIVE"
    assumptions = {
        "equivalence": ("same state prepared from |0...0>, up to global phase" if mode == "state"
                        else "same unitary on every input, up to global phase"),
        "mode": mode, "initial_state": "|0...0>" if mode == "state" else "any",
        "qubits_initially_zero": mode == "state",
        "allowed_gates": res.get("basis"), "coupling": o.get("coupling"),
        "permutation_allowed": bool(o.get("allow_permutation")),
        "proof_scope": res.get("proof_scope"),
        "layout_dependent": layout,
        "black_boxes_allowed": True,
        "timeout_s": o.get("timeout"), "budget_s": o.get("budget"), "seeds": o.get("seeds"),
    }
    metrics = {"source": res.get("source"), "baseline": res.get("baseline"),
               "best": {k: best.get(k) for k in ("cx", "depth", "size", "config", "final_index_layout")} if best else None,
               "cx_saved_vs_baseline": res.get("cx_saved_vs_baseline"),
               "cx_saved_vs_qiskit_level3": res.get("cx_saved_vs_qiskit_level3"), "counts": res.get("counts")}
    checks = [{"name": "Proven equivalence of output", "status": verdict, "summary": proof["summary"]}]
    return _base("optimize", verdict, inputs, assumptions, proof, _small(metrics), checks, None, started,
                 res.get("seconds"))


def _small(x: Any, limit: int = 4000) -> Any:
    """Keep certificates compact: drop big blobs (counts, distributions) from evidence/metrics."""
    s = json.dumps(x, default=str)
    if len(s) <= limit:
        return json.loads(s)
    if isinstance(x, dict):
        return {k: _small(v, limit // 2) for k, v in x.items()
                if k not in ("observed_counts", "expected_distribution", "matrix")}
    return f"<omitted: {len(s)} bytes>"


# ----------------------------------------------------------------------------- semantics

def semantic_problems(cert: dict[str, Any]) -> list[str]:
    p: list[str] = []
    if cert.get("schema") != SCHEMA:
        p.append(f"unknown schema {cert.get('schema')!r}")
    v = cert.get("verdict")
    if v not in ("PASS", "FAIL", "INCONCLUSIVE"):
        p.append(f"invalid verdict {v!r}")
    applicable = [c for c in cert.get("checks", []) if c.get("status") != "SKIPPED"]
    statuses = {c.get("status") for c in applicable}
    if v == "PASS" and (not applicable or statuses != {"PASS"}):
        bad = [f"{c.get('name')}={c.get('status')}" for c in applicable if c.get("status") != "PASS"]
        p.append("verdict PASS but not every applicable check passed" + (f" ({', '.join(bad)})" if bad else ""))
    if v == "FAIL" and "FAIL" not in statuses:
        p.append("verdict FAIL but no check failed")
    if v == "INCONCLUSIVE" and "FAIL" in statuses:
        p.append("verdict INCONCLUSIVE but a check failed (that is a FAIL)")
    proof = cert.get("proof") or {}
    ps = proof.get("status")
    claim = cert.get("claim")
    expected = _claim(v, ps) if v in ("PASS", "FAIL", "INCONCLUSIVE") else None
    if claim != expected:
        p.append(f"claim {claim!r} does not follow from verdict {v!r} and proof status {ps!r} (expected {expected!r})")
    # A proven proof with a non-PASS verdict is legitimate (e.g. a constraint FAILed or the sampling test was
    # borderline); its claim is then CHECK_FAILED / NONE, never PROVEN_EQUIVALENT (enforced via `claim`).
    if ps not in ("proven", "refuted", "undecided", "none"):
        p.append(f"invalid proof status {ps!r}")
    if ps == "proven" and "PROBABLY" in json.dumps(proof).upper():
        p.append("a PROBABLY_EQUIVALENT (simulation-only) result is not a proof")
    if v == "FAIL" and cert.get("counterexample") is None:
        p.append("FAIL certificate without a counterexample / failing evidence")
    return p


# ----------------------------------------------------------------------------- keys / signing

def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover
        raise CertificateError("signing needs the `cryptography` package: pip install cryptography") from exc
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def generate_keypair(private_path: str | Path, public_path: str | Path | None = None,
                     passphrase: bytes | None = None, overwrite: bool = False) -> dict[str, str]:
    serialization, Priv, _ = _crypto()
    private_path = Path(private_path)
    public_path = Path(public_path) if public_path else private_path.with_suffix(".pub")
    for p in (private_path, public_path):
        if p.exists() and not overwrite:
            raise CertificateError(f"{p} exists (use --force to overwrite)")
    key = Priv.generate()
    enc = (serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    os.chmod(private_path, 0o600)
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    public_path.write_bytes(pub)
    return {"private": str(private_path), "public": str(public_path), "key_id": key_id(key.public_key())}


def _raw_pub(pub) -> bytes:
    serialization, _, _ = _crypto()
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(pub) -> str:
    return sha256_bytes(_raw_pub(pub))[:16]


def load_private_key(spec: str | Path | None = None, passphrase: bytes | None = None):
    """`spec` is a PEM file path or PEM text; default: $VERIQ_SIGNING_KEY (PEM text or path)."""
    serialization, Priv, _ = _crypto()
    spec = spec if spec is not None else os.environ.get(KEY_ENV)
    if not spec:
        raise CertificateError(f"no signing key: pass --sign-key FILE or set ${KEY_ENV}")
    if passphrase is None and os.environ.get(PASSPHRASE_ENV):
        passphrase = os.environ[PASSPHRASE_ENV].encode()
    s = str(spec)
    data = s.encode() if "-----BEGIN" in s else Path(s).expanduser().read_bytes()
    try:
        key = serialization.load_pem_private_key(data, password=passphrase)
    except (ValueError, TypeError) as exc:
        raise CertificateError(f"cannot load the private key: {exc}") from None
    if not isinstance(key, Priv):
        raise CertificateError("the signing key is not an Ed25519 private key")
    return key


def load_public_key(spec: str | Path):
    serialization, Priv, Pub = _crypto()
    s = str(spec)
    data = s.encode() if "-----BEGIN" in s else Path(s).expanduser().read_bytes()
    try:
        key = serialization.load_pem_public_key(data)
    except ValueError:
        try:  # a private key file also identifies its public key
            key = serialization.load_pem_private_key(data, password=None).public_key()
        except Exception as exc:  # noqa: BLE001
            raise CertificateError(f"cannot load the public key: {exc}") from None
    if not isinstance(key, Pub):
        raise CertificateError("the key is not an Ed25519 public key")
    return key


def sign_certificate(cert: dict[str, Any], private_key) -> dict[str, Any]:
    problems = semantic_problems(cert)
    if problems:
        raise CertificateError("refusing to sign an inconsistent certificate: " + "; ".join(problems))
    emb = embedded_hash_problems(cert)
    if emb:
        raise CertificateError("refusing to sign: " + "; ".join(emb))
    out = {k: v for k, v in cert.items() if k != "signature"}
    payload = payload_of(out)
    pub = private_key.public_key()
    out["signature"] = {
        "alg": SIG_ALG,
        "key_id": key_id(pub),
        "public_key": base64.b64encode(_raw_pub(pub)).decode(),
        "payload_sha256": sha256_bytes(payload),
        "signed_at": utc_now(),
        "value": base64.b64encode(private_key.sign(payload)).decode(),
        "canonicalization": "json, sorted keys, separators (',',':'), ensure_ascii, without `signature`",
    }
    return out


def embedded_hash_problems(cert: dict[str, Any]) -> list[str]:
    p = []
    for rec in cert.get("inputs", []):
        if rec.get("canonical") is not None and sha256_bytes(rec["canonical"].encode()) != rec.get("canonical_sha256"):
            p.append(f"{rec.get('role')}: embedded canonical circuit does not match canonical_sha256")
    return p


# ----------------------------------------------------------------------------- verification

def _check(results: list, name: str, ok: bool | None, detail: str) -> None:
    results.append({"check": name, "ok": ok, "detail": detail})


def verify_certificate(cert: dict[str, Any], public_key=None, circuits: list[str] | None = None,
                       recheck: bool = False, allow_unsigned: bool = False,
                       timeout: float | None = None) -> dict[str, Any]:
    """Verify signature, hashes and semantics; optionally re-hash files and re-run the proof.

    `ok` is True only when every performed check passed. `trusted` is True only when the signature was
    checked against a key the caller supplied (an embedded key alone proves integrity, not authorship).
    """
    from cryptography.exceptions import InvalidSignature

    res: list[dict[str, Any]] = []
    trusted = False
    sig = cert.get("signature")
    if not sig:
        _check(res, "signature", True if allow_unsigned else False,
               "certificate is unsigned" + (" (allowed)" if allow_unsigned else ""))
    else:
        try:
            _, _, Pub = _crypto()
            if sig.get("alg") != SIG_ALG:
                raise CertificateError(f"unsupported signature algorithm {sig.get('alg')!r}")
            embedded = Pub.from_public_bytes(base64.b64decode(sig["public_key"]))
            key = public_key if public_key is not None else embedded
            if public_key is not None and _raw_pub(public_key) != _raw_pub(embedded):
                raise CertificateError(f"signed by key {sig.get('key_id')}, not by the supplied key "
                                       f"{key_id(public_key)}")
            payload = payload_of(cert)
            if sha256_bytes(payload) != sig.get("payload_sha256"):
                raise CertificateError("payload hash mismatch: the certificate was modified after signing")
            key.verify(base64.b64decode(sig["value"]), payload)
            trusted = public_key is not None
            _check(res, "signature", True, f"valid {SIG_ALG} signature by key {sig['key_id']}"
                   + ("" if trusted else " (embedded key; pass --key to pin the signer)"))
        except InvalidSignature:
            _check(res, "signature", False, "INVALID signature")
        except (CertificateError, KeyError, ValueError, TypeError) as exc:
            _check(res, "signature", False, str(exc))

    problems = semantic_problems(cert)
    _check(res, "semantics", not problems, "; ".join(problems) or
           f"verdict {cert.get('verdict')} / claim {cert.get('claim')} consistent with checks and proof")
    emb = embedded_hash_problems(cert)
    _check(res, "embedded circuits", not emb, "; ".join(emb) or "embedded canonical circuits match their hashes")

    inputs = cert.get("inputs", [])
    file_inputs = [r for r in inputs if r.get("role") in ("candidate", "reference", "input")]
    loaded: dict[str, Any] = {}
    if circuits:
        if len(circuits) > len(file_inputs):
            _check(res, "circuit files", False, f"{len(circuits)} files given, certificate has {len(file_inputs)} inputs")
        for rec, f in zip(file_inputs, circuits):
            _rehash(res, rec, f, loaded)
    if recheck:
        _recheck(res, cert, loaded, timeout)
    ok = all(r["ok"] is not False for r in res)
    return {"ok": ok, "trusted": trusted and ok, "verdict": cert.get("verdict"), "claim": cert.get("claim"),
            "key_id": (sig or {}).get("key_id"), "results": res}


def _rehash(res: list, rec: dict, path: str, loaded: dict) -> None:
    from .loader import load_circuit

    role = rec.get("role")
    p = Path(path)
    if not p.is_file():
        _check(res, f"{role} file", False, f"{path}: not found")
        return
    src = sha256_file(p)
    if rec.get("source_sha256") and src != rec["source_sha256"]:
        _check(res, f"{role} source hash", False, f"{path}: sha256 {src[:16]}… != certified {rec['source_sha256'][:16]}…")
    else:
        _check(res, f"{role} source hash", True if rec.get("source_sha256") else None,
               f"{path}: source sha256 matches" if rec.get("source_sha256") else "no source hash certified")
    try:
        qc = load_circuit(p, rec.get("function"))
    except Exception as exc:  # noqa: BLE001
        _check(res, f"{role} canonical hash", False if rec.get("canonical_sha256") else None,
               f"{path} does not build: {exc}"[:300])
        return
    _, text = canonical_qasm(qc)
    h = sha256_bytes(text.encode())
    _check(res, f"{role} canonical hash", h == rec.get("canonical_sha256"),
           "canonical circuit matches" if h == rec.get("canonical_sha256")
           else f"canonical sha256 {h[:16]}… != certified {str(rec.get('canonical_sha256'))[:16]}…")
    loaded[role] = qc


def _from_record(rec: dict | None):
    from qiskit import qasm2, qasm3

    if not rec or rec.get("canonical") is None:
        return None
    return (qasm2.loads(rec["canonical"], custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
            if rec.get("canonical_format") == "qasm2" else qasm3.loads(rec["canonical"]))


def _recheck(res: list, cert: dict, loaded: dict, timeout: float | None) -> None:
    from . import scale

    byrole = {r.get("role"): r for r in cert.get("inputs", [])}
    a = cert.get("assumptions", {})
    mode = a.get("mode", "unitary")
    to = timeout or a.get("timeout_s") or 30.0
    try:
        if cert.get("kind") == "optimize":
            if a.get("layout_dependent"):
                _check(res, "recheck", None, "skipped: the proof is up to a layout the QASM does not carry")
                return
            src = loaded.get("input") or _from_record(byrole.get("input"))
            out = _from_record(byrole.get("output"))
            if src is None or out is None:
                _check(res, "recheck", None if cert.get("verdict") != "PASS" else False,
                       "nothing to recheck (no output circuit)")
                return
            from .checks import unitary_part

            r = scale.decide_equivalence(out, unitary_part(src), mode=mode, timeout=to)
            ok = (r["status"] == scale.PROVEN) == (cert.get("verdict") == "PASS")
            _check(res, "recheck", ok, f"re-proved output vs input: {r['status']} ({r.get('method')})")
            return
        from .runner import run_checks

        cand = loaded.get("candidate") or _from_record(byrole.get("candidate"))
        ref = loaded.get("reference") or _from_record(byrole.get("reference"))
        if cand is None:
            _check(res, "recheck", None, "no candidate circuit available (it did not build)")
            return
        st = a.get("statistical") or {}
        from_files = "candidate" in loaded and ("reference" in loaded or "reference" not in byrole)
        # Constraints (gate set, coupling, black boxes) are about the source AS WRITTEN; the QASM export can
        # rename or inline gates, so from embedded QASM only the proof (and statistics) are re-run.
        rep = run_checks(cand, reference=ref, expect=a.get("expect"), backend=a.get("backend"), mode=mode,
                         allowed_gates=a.get("allowed_gates") if from_files else None,
                         coupling=a.get("coupling") if from_files else None,
                         no_black_boxes=(not a.get("black_boxes_allowed", True)) if from_files else False,
                         shots=st.get("shots", 4096), seed=st.get("seed", 7), timeout=to)
        new = rep.verdict.value
        newproof = _proof_from_checks(rep.to_dict()["checks"])["status"]
        old = cert.get("verdict")
        oldproof = (cert.get("proof") or {}).get("status")
        if from_files:
            _check(res, "recheck", new == old and newproof == oldproof,
                   f"re-ran all checks on the source files: verdict {new} (certified {old}), "
                   f"proof {newproof} (certified {oldproof})")
        elif not (a.get("allowed_gates") or a.get("coupling") or not a.get("black_boxes_allowed", True)):
            _check(res, "recheck", new == old and newproof == oldproof,
                   f"re-ran all checks on the embedded canonical QASM: verdict {new} (certified {old}), "
                   f"proof {newproof} (certified {oldproof})")
        else:
            _check(res, "recheck", newproof == oldproof,
                   f"re-ran the proof on the embedded canonical QASM: proof {newproof} (certified {oldproof}); "
                   "constraints not rechecked (pass --circuit files for a full recheck)")
    except Exception as exc:  # noqa: BLE001
        _check(res, "recheck", False, f"recheck failed: {exc!r}"[:300])


# ----------------------------------------------------------------------------- IO helpers

def write_certificate(cert: dict[str, Any], path: str | Path, sign_key: str | None = None,
                      sign_env: bool = False) -> dict[str, Any]:
    if sign_key or (sign_env and os.environ.get(KEY_ENV)):
        cert = sign_certificate(cert, load_private_key(sign_key))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(cert, indent=1, sort_keys=False, default=str) + "\n")
    return cert


def read_certificate(path: str | Path) -> dict[str, Any]:
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CertificateError(f"cannot read certificate {path}: {exc}") from None
    if not isinstance(d, dict):
        raise CertificateError("certificate must be a JSON object")
    return d
