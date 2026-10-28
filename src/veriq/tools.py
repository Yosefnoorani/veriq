"""Analysis behind the MCP tools. Pure functions on QuantumCircuit objects that return JSON-able dicts.

They run inside the sandbox worker (on circuits deserialized from QPY), and are also directly
unit-testable. Nothing here executes user code.
"""

from __future__ import annotations

import time
from typing import Any

from qiskit import QuantumCircuit, transpile

from . import checks
from .models import Status
from .runner import run_checks

MAX_EVIDENCE_KEYS = 16


# --------------------------------------------------------------------------- helpers


def _trim(obj: Any, depth: int = 0) -> Any:
    """Keep evidence small enough for an LLM context: cap dict sizes and long strings."""
    if isinstance(obj, dict):
        items = list(obj.items())
        if len(items) > MAX_EVIDENCE_KEYS and all(isinstance(v, (int, float)) for _, v in items):
            items = sorted(items, key=lambda kv: -abs(kv[1]))[:MAX_EVIDENCE_KEYS]
            out = {k: _trim(v, depth + 1) for k, v in items}
            out["…"] = f"{len(obj) - MAX_EVIDENCE_KEYS} more entries omitted"
            return out
        return {k: _trim(v, depth + 1) for k, v in items}
    if isinstance(obj, list):
        return [_trim(v, depth + 1) for v in obj[:50]]
    if isinstance(obj, str) and len(obj) > 2000:
        return obj[:2000] + "…"
    return obj


def _bits_differ(a: str, b: str) -> list[int]:
    """Qubit indices (little-endian: rightmost char is qubit 0) where two bitstrings differ."""
    a, b = a.replace(" ", ""), b.replace(" ", "")
    n = min(len(a), len(b))
    return [i for i in range(n) if a[len(a) - 1 - i] != b[len(b) - 1 - i]]


def hints_for(report: dict[str, Any]) -> list[str]:
    """Actionable, LLM-oriented hints derived from a Veriq report dict."""
    hints: list[str] = []
    by = {c["name"]: c for c in report.get("checks", [])}
    b = by.get("Build")
    if b and b["status"] == "FAIL":
        ev = b.get("evidence", {})
        hints.append(f"The code did not produce a circuit ({ev.get('exception') or 'error'}): "
                     f"{ev.get('message', b['summary'])[:300]}. Fix the error; the module must define "
                     "`build()` returning a QuantumCircuit (or `circuit`), or pass `function`.")
        return hints
    for name in ("Reference equivalence", "State equivalence (from |0...0>)"):
        c = by.get(name)
        if not c or c["status"] != "FAIL":
            continue
        ev = c.get("evidence", {})
        if "candidate_qubits" in ev:
            hints.append(f"Your circuit has {ev['candidate_qubits']} qubits but the reference has "
                         f"{ev['reference_qubits']}. Use exactly the reference's register size (ancillas included).")
            continue
        cx = ev.get("counterexample")
        if cx:
            hints.append(f"Counterexample: on input {cx['input_state']} the output overlaps the reference's by only "
                         f"{cx['fidelity']:.4f}. Simulate that input by hand or with Statevector to find the step "
                         "where they diverge.")
            ct, rt = cx.get("candidate_output_top") or {}, cx.get("reference_output_top") or {}
            if ct and rt:
                ck, rk = next(iter(ct)), next(iter(rt))
                peaked = ct[ck] >= 0.5 and rt[rk] >= 0.5  # only meaningful for (near-)basis outputs
                if peaked and len(ck) == len(rk) and ck != rk:
                    diff = _bits_differ(ck, rk)
                    hints.append(f"Most likely output: yours |{ck}> vs reference |{rk}>; they differ on qubit(s) "
                                 f"{diff} (Qiskit is little-endian: the rightmost bit is qubit 0).")
                    if ck == rk[::-1]:
                        hints.append("Your output is the bit-reverse of the reference: a qubit-order/endianness "
                                     "mix-up (e.g. a missing or extra final swap layer in a QFT).")
            if cx.get("note"):
                hints.append("All basis inputs give the right output up to phase, so the bug is in relative phases: "
                             "check rotation/phase angles and their signs (cp(θ) vs cp(-θ), s vs sdg, t vs tdg).")
        elif "fidelity" in ev:
            hints.append(f"The prepared state has fidelity {ev['fidelity']} with the reference state.")
        else:
            hints.append("Not equivalent to the reference. Compare the two circuits gate by gate.")
    t = by.get("Transpile integrity")
    if t and t["status"] == "FAIL":
        hints.append("Qiskit's compiled output differs from your circuit. This is rare: check for custom gates "
                     "with inconsistent definitions, or report a transpiler bug with this circuit.")
    if t and (t.get("evidence") or {}).get("zero_init_hazard"):
        hints.append("Zero-init hazard: transpile() with the default qubits_initially_zero=True produced a circuit "
                     "that is only valid on |0…0>. If you transpile this block and reuse it (to_gate/compose), "
                     "pass qubits_initially_zero=False.")
    g = by.get("Gate-set constraint")
    if g and g["status"] == "FAIL":
        bad = sorted((g.get("evidence") or {}).get("violations") or {})
        hints.append(f"Disallowed instructions {bad}: rewrite them with the allowed gates only (for example "
                     "decompose mcx/ccx into h, t, tdg, cx; do not call library blocks).")
    cp = by.get("Coupling-map constraint")
    if cp and cp["status"] == "FAIL":
        ev = cp.get("evidence") or {}
        hints.append(f"Gates off the coupling map: {str(ev.get('first_violations', ''))[:300]}. "
                     "Route with explicit SWAPs (3 CX) or re-order qubits; 3+-qubit gates must be decomposed.")
    bb = by.get("No black boxes")
    if bb and bb["status"] == "FAIL":
        hints.append("Black-box instructions found (matrix/state/library blocks). Write the circuit out gate by gate.")
    s = by.get("Statistical test (Aer)")
    if s and s["status"] == "FAIL":
        ev = s.get("evidence") or {}
        obs, exp = ev.get("observed_counts") or {}, ev.get("expected_distribution") or {}
        if obs and exp:
            top = max(obs, key=obs.get)
            if top not in exp and top[::-1] in exp:
                hints.append(f"Measured {top} most often but the expectation has {top[::-1]}: probably reversed bit "
                             "order (Qiskit prints qubit 0 rightmost).")
        hints.append("The measured distribution disagrees with the expectation; see evidence.tvd / "
                     "impossible_outcomes.")
    if report.get("verdict") == "INCONCLUSIVE":
        reasons = [f"{c['name']}: {c['summary']}" for c in report.get("checks", []) if c["status"] == "INCONCLUSIVE"]
        hints.append("Not proved either way. " + " | ".join(reasons)[:500] +
                     " Pass a reference circuit, an `expect` distribution, or reduce the circuit size.")
    if report.get("verdict") == "PASS" and not hints:
        hints.append("All applicable checks passed; you can present this circuit, citing the checks above.")
    return hints


def _counterexample(report: dict[str, Any]) -> dict[str, Any] | None:
    for c in report.get("checks", []):
        cx = (c.get("evidence") or {}).get("counterexample")
        if cx:
            return cx
    return None


def report_to_tool_result(rep: dict[str, Any]) -> dict[str, Any]:
    checks_out = [{"name": c["name"], "status": c["status"], "summary": c["summary"],
                   "evidence": _trim(c.get("evidence") or {}), "seconds": c.get("seconds", 0)}
                  for c in rep.get("checks", [])]
    out = {
        "verdict": rep["verdict"],
        "summary": _one_line(rep),
        "checks": checks_out,
        "counterexample": _counterexample(rep),
        "metrics": _trim((rep.get("metrics") or {}).get("source") or {}),
        "hints": hints_for(rep),
        "seconds": rep.get("seconds"),
        "versions": rep.get("versions", {}),
    }
    return out


def _one_line(rep: dict[str, Any]) -> str:
    v = rep["verdict"]
    key = [c for c in rep.get("checks", []) if c["status"] in ("FAIL", "INCONCLUSIVE")]
    if v == "PASS":
        return "PASS: every applicable check passed."
    if key:
        return f"{v}: " + "; ".join(f"{c['name']}: {c['summary']}" for c in key)[:600]
    return v


# --------------------------------------------------------------------------- tools


def verify_circuit(candidate: QuantumCircuit, reference: QuantumCircuit | None = None, mode: str = "unitary",
                   allowed_gates: list[str] | None = None, coupling: str | list | None = None,
                   no_black_boxes: bool = False, shots: int = 4096, expect: dict | None = None,
                   seed: int = 7, timeout: float = 30.0, certificate: bool = False,
                   sources: dict[str, dict] | None = None) -> dict[str, Any]:
    """`certificate=True` adds an UNSIGNED veriq.certificate/1 (sign it later with `veriq certify`).
    `sources` = {role: {path, function, source_sha256}} recorded in the certificate's inputs."""
    from .certificate import utc_now

    started = utc_now()
    report = run_checks(candidate, reference=reference, expect=expect, shots=shots, seed=seed, timeout=timeout,
                        mode=mode, allowed_gates=allowed_gates, coupling=coupling, no_black_boxes=no_black_boxes)
    rep = report.to_dict()
    out = report_to_tool_result(rep)
    if out["verdict"] != "PASS":
        out["repair_report"] = _compact_repair(_repair(candidate, reference, mode, rep))
    if certificate:
        out["certificate"] = _certificate(report, started, sources or {}, dict(
            mode=mode, allowed_gates=allowed_gates, coupling=coupling, no_black_boxes=no_black_boxes,
            shots=shots, expect=expect, seed=seed, timeout=timeout))
    return out


def _certificate(report, started: str, sources: dict[str, dict], options: dict[str, Any]) -> dict[str, Any]:
    from .certificate import certificate_from_report

    try:
        cert = certificate_from_report(report, kind="verify", options=options, started=started)
    except Exception as exc:  # a certificate problem must never break the verdict
        return {"error": f"certificate not produced: {exc!r}"[:300]}
    for rec in cert.get("inputs", []):
        src = sources.get(rec["role"]) or {}
        for k in ("path", "function", "source_sha256"):
            if src.get(k) is not None:
                rec[k] = src[k]
    return cert


def _repair(candidate: QuantumCircuit, reference: QuantumCircuit | None, mode: str,
            rep: dict[str, Any]) -> dict[str, Any]:
    from .repair_report import SCHEMA, build_repair_report

    try:
        return build_repair_report(candidate, reference, mode, result=rep, localize_circuit=rep["verdict"] != "PASS")
    except Exception as exc:  # never let the explanation break the verdict
        return {"schema": SCHEMA, "verdict": rep.get("verdict"), "error": f"repair report failed: {exc!r}"[:300]}


def _compact_repair(r: dict[str, Any]) -> dict[str, Any]:
    r = dict(r)
    loc = r.get("localization")
    if isinstance(loc, dict):
        loc = {k: v for k, v in loc.items() if k != "support_size_per_gap"}
        loc["regions"] = [dict(reg, gates=reg["gates"][:12]) for reg in loc.get("regions", [])[:3]]
        loc["fixes"] = [{k: v for k, v in f.items() if k != "gate" or "matrix" not in v} for f in loc.get("fixes", [])[:4]]
        r["localization"] = loc
    return _trim(r)


def repair_hints(candidate: QuantumCircuit, reference: QuantumCircuit | None = None, mode: str = "unitary",
                 allowed_gates: list[str] | None = None, coupling: str | list | None = None,
                 no_black_boxes: bool = False, timeout: float = 30.0) -> dict[str, Any]:
    """Full machine-readable repair report (see veriq.repair_report)."""
    rep = run_checks(candidate, reference=reference, timeout=timeout, mode=mode, allowed_gates=allowed_gates,
                     coupling=coupling, no_black_boxes=no_black_boxes, shots=1024).to_dict()
    out = _repair(candidate, reference, mode, rep)
    out["summary"] = _one_line(rep)
    return _trim(out)


def _coupling_edges(spec: str | list | None, n: int) -> list[list[int]] | None:
    if spec in (None, "all", "full"):
        return None
    edges = checks.parse_coupling(spec, n)
    if edges is None:
        return None
    both = {tuple(e) for e in edges} | {(b, a) for a, b in edges}
    return [list(e) for e in sorted(both)]


def check_transpile(candidate: QuantumCircuit, optimization_level: int = 3,
                    basis_gates: list[str] | None = None, coupling: str | list | None = "linear",
                    seed: int = 1234, qubits_initially_zero: bool | None = None,
                    timeout: float = 30.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    u = checks.unitary_part(candidate)
    nu = checks.non_unitary_ops(u)
    basis = basis_gates or checks.GENERIC_BASIS
    cmap = _coupling_edges(coupling, max(u.num_qubits, 1))
    base = dict(basis_gates=basis, coupling_map=cmap, optimization_level=optimization_level, seed_transpiler=seed)
    runs: dict[str, Any] = {}
    settings = [False, True] if qubits_initially_zero is None else [bool(qubits_initially_zero)]
    if nu:
        return {"verdict": "INCONCLUSIVE", "equivalent": None, "status": "UNKNOWN",
                "summary": f"circuit has mid-circuit non-unitary operations {nu}; unitary equivalence undefined",
                "runs": {}, "zero_init_hazard": None, "seconds": round(time.perf_counter() - t0, 3)}
    for z in settings:
        key = f"qubits_initially_zero={z}"
        try:
            tq = transpile(u, qubits_initially_zero=z, **base)
        except Exception as exc:
            runs[key] = {"status": "ERROR", "error": repr(exc)[:300]}
            continue
        res = checks.equivalence_status(u, tq, timeout)
        entry = {"status": res["status"], "method": res.get("method"), "evidence": _trim(res.get("evidence", {})),
                 "compiled_metrics": _trim(checks.circuit_metrics(tq))}
        if res["status"] == "NOT_EQUIVALENT":
            cex = res.get("evidence", {}).get("counterexample") or checks.find_counterexample(u, tq)
            entry["counterexample"] = cex
            if z:
                entry["equal_on_zero_input"] = checks.zero_input_equal(u, tq)
        runs[key] = entry
    primary = runs.get(f"qubits_initially_zero={settings[0]}", {})
    hazard = None
    if "qubits_initially_zero=True" in runs and "qubits_initially_zero=False" in runs:
        hazard = (runs["qubits_initially_zero=True"].get("status") == "NOT_EQUIVALENT"
                  and runs["qubits_initially_zero=False"].get("status") == "PROVEN_EQUIVALENT")
    elif settings == [True]:
        hazard = primary.get("status") == "NOT_EQUIVALENT" and bool(primary.get("equal_on_zero_input"))
    st = primary.get("status", "ERROR")
    verdict = {"PROVEN_EQUIVALENT": "PASS", "NOT_EQUIVALENT": "FAIL"}.get(st, "INCONCLUSIVE")
    summary = {"PASS": "Proved: the compiled circuit implements the same unitary (up to global phase).",
               "FAIL": "The compiled circuit is NOT equivalent to the source as a unitary.",
               "INCONCLUSIVE": f"Not proved ({st})."}[verdict]
    if hazard:
        summary += (" zero_init_hazard: with qubits_initially_zero=True the output is only correct on |0…0> "
                    "input; do not reuse it as a gate/block.")
    return {"verdict": verdict, "equivalent": {"PASS": True, "FAIL": False}.get(verdict), "status": st,
            "summary": summary, "zero_init_hazard": hazard,
            "options": {"optimization_level": optimization_level, "basis_gates": basis,
                        "coupling": coupling if isinstance(coupling, (str, type(None))) else "custom", "seed": seed},
            "source_metrics": _trim(checks.circuit_metrics(u)), "runs": runs,
            "seconds": round(time.perf_counter() - t0, 3)}


def compare_circuits(candidate: QuantumCircuit, reference: QuantumCircuit, mode: str = "unitary",
                     timeout: float = 30.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    a, b = checks.unitary_part(candidate), checks.unitary_part(reference)
    base = {"a_qubits": a.num_qubits, "b_qubits": b.num_qubits, "mode": mode}
    if a.num_qubits != b.num_qubits:
        return dict(base, verdict="FAIL", equivalent=False, status="NOT_EQUIVALENT", method="qubit count",
                    summary=f"different widths: {a.num_qubits} vs {b.num_qubits} qubits", counterexample=None,
                    seconds=round(time.perf_counter() - t0, 3))
    nu = checks.non_unitary_ops(a) + checks.non_unitary_ops(b)
    if nu:
        return dict(base, verdict="INCONCLUSIVE", equivalent=None, status="UNKNOWN", method=None, counterexample=None,
                    summary=f"mid-circuit non-unitary operations {sorted(set(nu))}",
                    seconds=round(time.perf_counter() - t0, 3))
    if mode == "state":
        c = checks.state_equivalence(a, b)
        st = {Status.PASS: "PROVEN_EQUIVALENT", Status.FAIL: "NOT_EQUIVALENT"}.get(c.status, "UNKNOWN")
        return dict(base, verdict=_v(st), equivalent={"PROVEN_EQUIVALENT": True, "NOT_EQUIVALENT": False}.get(st), status=st,
                    method=(c.evidence or {}).get("engine"), summary=c.summary, counterexample=None,
                    evidence=_trim(c.evidence), seconds=round(time.perf_counter() - t0, 3))
    res = checks.equivalence_status(a, b, timeout)
    st = res["status"]
    cex = (res.get("evidence", {}).get("counterexample") or checks.find_counterexample(a, b)) \
        if st == "NOT_EQUIVALENT" else None
    summary = {"PROVEN_EQUIVALENT": "Proved equivalent (same unitary up to global phase).",
               "NOT_EQUIVALENT": "NOT equivalent.",
               "PROBABLY_EQUIVALENT": "Probably equivalent: no difference found by simulation (falsification only), "
                                      "NOT proved.",
               "UNKNOWN": "Could not decide within the limits."}[st]
    if cex:
        summary += f" Counterexample input {cex['input_state']} (overlap {cex['fidelity']:.4f})."
    return dict(base, verdict=_v(st), equivalent={"PROVEN_EQUIVALENT": True, "NOT_EQUIVALENT": False}.get(st), status=st,
                method=res.get("method"), summary=summary, counterexample=cex, evidence=_trim(res.get("evidence", {})),
                seconds=round(time.perf_counter() - t0, 3))


def _v(status: str) -> str:
    return {"PROVEN_EQUIVALENT": "PASS", "NOT_EQUIVALENT": "FAIL"}.get(status, "INCONCLUSIVE")


def circuit_metrics(candidate: QuantumCircuit, compile: bool = True, seed: int = 1234) -> dict[str, Any]:
    out: dict[str, Any] = {"source": checks.circuit_metrics(candidate)}
    if compile:
        u = checks.unitary_part(candidate)
        if not checks.non_unitary_ops(u):
            n = max(u.num_qubits, 1)
            tq = transpile(u, basis_gates=checks.GENERIC_BASIS,
                           coupling_map=_coupling_edges("linear", n) if n > 1 else None, optimization_level=3,
                           seed_transpiler=seed, qubits_initially_zero=False)
            out["compiled"] = {"target": f"basis {checks.GENERIC_BASIS}, linear coupling, opt=3",
                               **checks.circuit_metrics(tq)}
    out["is_clifford"] = checks.is_clifford(candidate)
    return out


def optimize_circuit(candidate: QuantumCircuit, mode: str = "unitary", basis_gates: list[str] | None = None,
                     coupling: str | list | None = None, seeds: int = 3, timeout: float = 20.0,
                     budget: float = 60.0, allow_permutation: bool = False) -> dict[str, Any]:
    """Cheapest PROVEN-equivalent compilation (see veriq.optimize)."""
    from .optimize import optimize_circuit as _optimize

    r = _optimize(candidate, mode=mode, basis_gates=basis_gates, coupling=coupling, seeds=seeds,
                  timeout=timeout, budget=budget, allow_permutation=allow_permutation)
    r.pop("best_circuit", None)
    b = r.get("best")
    r["summary"] = (f"best PROVEN candidate: {b['cx']} two-qubit gates, depth {b['depth']} "
                    f"(source compiled at opt=0: {r['baseline']['cx']}); proof: {b['method']}" if b else
                    "no candidate could be proven equivalent; nothing is returned")
    return _trim(r)


def preflight_circuit(candidate: QuantumCircuit, reference: QuantumCircuit | None = None,
                      backend: str | dict = "fake_torino", mode: str = "unitary", seeds: int = 4,
                      levels: list[int] | None = None, min_esp: float | None = None, warn_esp: float | None = None,
                      max_cx: int | None = None, max_duration: float | None = None, noisy_sim: bool = False,
                      max_tvd: float | None = None, timeout: float = 30.0) -> dict[str, Any]:
    """Pre-submission hardware gate (see veriq.preflight): go / warn / no-go."""
    from qiskit import qasm3

    from .preflight import PreflightError, preflight, to_json

    try:
        res = preflight(candidate, backend, reference=reference, mode=mode, seeds=seeds,
                        levels=tuple(levels or (1, 3)), min_esp=min_esp, warn_esp=warn_esp, max_cx=max_cx,
                        max_duration=max_duration, noisy_sim=noisy_sim, max_tvd=max_tvd, timeout=timeout)
    except PreflightError as exc:
        return {"verdict": "ERROR", "gate": None, "summary": f"preflight error: {exc}",
                "error": {"kind": "input", "detail": str(exc), "stderr_tail": ""}}
    out = to_json(res)
    comp = (res.get("compact") or {}).get("circuit")
    if comp is not None:
        try:
            out["compiled_qasm"] = qasm3.dumps(comp)
        except Exception:  # noqa: BLE001
            out["compiled_qasm"] = None
    est = out.get("estimate") or {}
    bad = [f"{c['name']}: {c['summary']}" for c in out["checks"] if c["status"] not in ("PASS", "SKIPPED")]
    out["summary"] = (f"{out['gate'].upper()} on {out['backend']['name']}: estimated success probability "
                      f"{est.get('esp', 0):.3g}, {est.get('two_qubit_gates')} two-qubit gates, "
                      f"{est.get('duration_s', 0) * 1e6:.3g} us; proof {(out.get('proof') or {}).get('status')}"
                      + ("; " + "; ".join(bad) if bad else "")) if est else f"{out['gate'].upper()}: " + "; ".join(bad)
    out["disclaimer"] = "ESP, duration and TVD are estimates from an offline calibration snapshot / profile, " \
                        "not hardware measurements."
    return _trim(out)
