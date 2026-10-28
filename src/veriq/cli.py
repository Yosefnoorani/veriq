"""Command-line interface: `veriq check <file> [--reference R] [--expect JSON] --report out.html`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .loader import LoadError
from .models import Status
from .report import render_html, render_json
from .runner import run_checks

from .preflight import DEFAULTS as _PF_DEFAULTS

EXIT = {Status.PASS: 0, Status.FAIL: 1, Status.INCONCLUSIVE: 2}

DEFAULT_MIN_ESP, DEFAULT_WARN_ESP = _PF_DEFAULTS["min_esp"], _PF_DEFAULTS["warn_esp"]
SYMBOL = {"PASS": "\u2714", "FAIL": "\u2718", "INCONCLUSIVE": "?", "SKIPPED": "-"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="veriq", description="Veriq: verify AI-written quantum circuits.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", aliases=["verify"], help="run all checks on a circuit (.py or .qasm); alias: verify")
    c.add_argument("file", help="candidate circuit: .py exposing `circuit`/`build()`, or OpenQASM 2/3")
    c.add_argument("--reference", "-r", help="trusted reference circuit to prove equivalence against")
    c.add_argument("--expect", "-e", help="expected distribution/property: inline JSON or path to .json")
    c.add_argument("--report", help="write a self-contained HTML report here")
    c.add_argument("--json", dest="json_out", help="write the JSON report here (default: next to --report)")
    c.add_argument("--backend", help="also transpile for a fake backend: 'generic' or 'generic:<nqubits>'")
    c.add_argument("--shots", type=int, default=4096)
    c.add_argument("--seed", type=int, default=7)
    c.add_argument("--timeout", type=float, default=30.0, help="QCEC timeout per proof (s)")
    c.add_argument("--function", "-f", help="builder function to call in a multi-function .py candidate")
    c.add_argument("--reference-function", help="builder function to call in a multi-function .py reference")
    c.add_argument("--mode", choices=["unitary", "state"], default="unitary",
                   help="unitary: full unitary equivalence; state: compare states prepared from |0...0>")
    c.add_argument("--allowed-gates", help="comma-separated gate-set constraint, e.g. h,t,tdg,cx (FAIL if violated)")
    c.add_argument("--coupling", help="coupling-map constraint on the circuit as written: 'linear', 'ring' or "
                                      "edges like '0-1,1-2,2-3' (FAIL on any 2-qubit gate off an edge or any 3+-qubit gate)")
    c.add_argument("--no-black-boxes", action="store_true",
                   help="FAIL on UnitaryGate, initialize, StatePreparation, PermutationGate, QFTGate or other library blocks")
    c.add_argument("--repair-report", help="write a machine-readable repair report (JSON) here: counterexample, "
                                           "localized bug region, hardware violations, metric deltas, hints")
    c.add_argument("--certificate", help="write a verification certificate (JSON) here")
    c.add_argument("--sign-key", help="sign the certificate with this Ed25519 private key (PEM); "
                     "default: $VERIQ_SIGNING_KEY if set, else unsigned")
    c.add_argument("--quiet", "-q", action="store_true")

    ci = sub.add_parser("ci", help="run every check listed in a .veriq.yml config (for CI)")
    ci.add_argument("--config", "-c", default=".veriq.yml", help="config file (default .veriq.yml)")
    ci.add_argument("--fail-on", choices=["fail", "inconclusive"], default="fail",
                    help="fail: only unexpected FAILs fail the run; inconclusive: unexpected INCONCLUSIVE too")
    co = ci.add_mutually_exclusive_group()
    co.add_argument("--changed-only", dest="changed_only", action="store_true", default=None,
                    help="only run entries whose files changed vs --base (overrides the config)")
    co.add_argument("--all", dest="changed_only", action="store_false", help="run every entry")
    ci.add_argument("--base", help="git ref to diff against (default origin/$GITHUB_BASE_REF)")
    ci.add_argument("--changed-files", help="file listing changed paths, one per line (instead of git diff)")
    ci.add_argument("--report-dir", help="HTML/JSON reports directory (default: report-dir from the config)")
    ci.add_argument("--json", dest="json_out", help="write the combined JSON summary here")
    ci.add_argument("--markdown", help="write the Markdown summary here")
    ci.add_argument("--github-output", help="append exit-code/ran/unexpected/skipped to this file ($GITHUB_OUTPUT)")
    ci.add_argument("--artifact-hint", help=argparse.SUPPRESS)
    ci.add_argument("--certificates", nargs="?", const="", default=None, metavar="DIR",
                    help="write one certificate per entry (default DIR: <report-dir>/certificates); signed when "
                         "--sign-key or $VERIQ_SIGNING_KEY is given")
    ci.add_argument("--sign-key", help="Ed25519 private key (PEM) for the certificates")
    ci.add_argument("--quiet", "-q", action="store_true")

    r = sub.add_parser("repair", help="verify, then repair with a fixer until PASS/INCONCLUSIVE (bounded retries)")
    r.add_argument("file", help="candidate circuit (.py or .qasm)")
    r.add_argument("--reference", "-r", required=True, help="trusted reference circuit")
    r.add_argument("--function", "-f")
    r.add_argument("--reference-function")
    r.add_argument("--mode", choices=["unitary", "state"], default="unitary")
    r.add_argument("--fixer", default="demo", help="'demo' (deterministic, offline) or 'module:function'; "
                                                   "see docs/repair.md for plugging in an LLM")
    r.add_argument("--max-attempts", type=int, default=5)
    r.add_argument("--allowed-gates")
    r.add_argument("--coupling")
    r.add_argument("--no-black-boxes", action="store_true")
    r.add_argument("--timeout", type=float, default=30.0)
    r.add_argument("--out", "-o", help="write the final circuit here as OpenQASM 2 (only if it PASSes)")
    r.add_argument("--json", dest="json_out", help="write the attempt log + last repair report here")
    r.add_argument("--quiet", "-q", action="store_true")

    o = sub.add_parser("optimize", help="find the cheapest PROVEN-equivalent compilation (CX count, then depth)")
    o.add_argument("file", help="circuit (.py or .qasm)")
    o.add_argument("--function", "-f")
    o.add_argument("--mode", choices=["unitary", "state"], default="unitary",
                   help="unitary (default): candidates must equal the circuit for every input; state: only from |0..0>")
    o.add_argument("--basis", default="cx,rz,sx,x", help="target basis gates (comma-separated)")
    o.add_argument("--coupling", help="optional coupling map: 'linear', 'ring' or '0-1,1-2' (default all-to-all)")
    o.add_argument("--allow-permutation", action="store_true",
                   help="accept candidates equal only up to a recorded output qubit permutation")
    o.add_argument("--seeds", type=int, default=4, help="transpiler seeds per configuration")
    o.add_argument("--timeout", type=float, default=30.0, help="proof timeout per candidate (s)")
    o.add_argument("--budget", type=float, default=300.0, help="total wall-clock budget (s)")
    o.add_argument("--out", "-o", help="write the best proven circuit here as OpenQASM 2")
    o.add_argument("--json", dest="json_out", help="write the full candidate report here")
    o.add_argument("--certificate", help="write a verification certificate (JSON) here")
    o.add_argument("--sign-key", help="sign the certificate with this Ed25519 private key (PEM); "
                     "default: $VERIQ_SIGNING_KEY if set, else unsigned")
    o.add_argument("--quiet", "-q", action="store_true")

    pf = sub.add_parser("preflight", help="pre-submission hardware gate: compile for a backend, PROVE the compiled "
                        "circuit equivalent, estimate ESP/duration/2q count -> go / warn / no-go")
    pf.add_argument("file", help="circuit (.py or .qasm)")
    pf.add_argument("--function", "-f")
    pf.add_argument("--backend", "-b", required=True,
                    help="fake IBM backend (fake_torino, FakeBrisbane, ...), a built-in profile "
                         "(ionq_style_25q, quantinuum_style_20q, braket_superconducting_style_12q) or profile.json")
    pf.add_argument("--reference", "-r", help="also prove the input equivalent to this reference")
    pf.add_argument("--reference-function")
    pf.add_argument("--mode", choices=["unitary", "state"], default="unitary", help="mode for --reference")
    pf.add_argument("--seeds", type=int, default=4, help="transpiler seeds per optimisation level (default 4)")
    pf.add_argument("--levels", default="1,3", help="optimisation levels to try (default 1,3)")
    pf.add_argument("--min-esp", type=float, help=f"no-go below this ESP (default {DEFAULT_MIN_ESP})")
    pf.add_argument("--warn-esp", type=float, help=f"warn below this ESP (default {DEFAULT_WARN_ESP})")
    pf.add_argument("--max-cx", type=int, help="no-go above this many two-qubit gates")
    pf.add_argument("--max-duration", type=float, help="no-go above this estimated duration (seconds)")
    pf.add_argument("--warn-t2-fraction", type=float, help="warn when duration > this x min T2 (default 0.5)")
    pf.add_argument("--noisy-sim", action="store_true", help="also run a noisy Aer simulation (<= 12 active qubits)")
    pf.add_argument("--max-tvd", type=float, help="no-go when the noisy TVD exceeds this (needs --noisy-sim)")
    pf.add_argument("--shots", type=int, default=4000)
    pf.add_argument("--timeout", type=float, default=60.0, help="proof timeout (s)")
    pf.add_argument("--out", "-o", help="write the chosen compiled circuit (physical qubits) as OpenQASM 2")
    pf.add_argument("--json", dest="json_out", help="write the full preflight result here")
    pf.add_argument("--certificate", help="write a verification certificate (JSON) here")
    pf.add_argument("--sign-key", help="sign the certificate with this Ed25519 private key (PEM); "
                    "default: $VERIQ_SIGNING_KEY if set, else unsigned")
    pf.add_argument("--quiet", "-q", action="store_true")

    b = sub.add_parser("bench", help="Veriq Bench: score model outputs or a bug detector against the benchmark")
    bs = b.add_subparsers(dest="bench_cmd", required=True)
    br = bs.add_parser("run", help="score a directory of model outputs (proof, constraints, CX cost, optimized-CX gap)")
    br.add_argument("--model-outputs", "-m", required=True,
                    help="DIR with <model>.py (all task functions) or <model>/<task>.py|.qasm; optional provenance.json")
    br.add_argument("--bench", help="bench data directory (default: benchmark/veriqbench/v0.1)")
    br.add_argument("--out", "-o", help="write the run JSON here")
    br.add_argument("--no-optimize", action="store_true", help="skip `veriq optimize` (no optimized-CX column)")
    br.add_argument("--budget", type=float, default=60.0, help="optimizer budget per circuit (s)")
    br.add_argument("--seeds", type=int, default=4)
    br.add_argument("--timeout", type=float, default=30.0, help="proof timeout (s)")
    br.add_argument("--tasks", help="comma-separated task ids (default: all)")
    br.add_argument("--models", help="comma-separated model names (default: all found)")
    br.add_argument("--quiet", "-q", action="store_true")
    bc = bs.add_parser("corpus-eval", help="score a bug detector against the mutant corpus")
    bc.add_argument("--detector", "-d", required=True,
                    help="histogram | zero-state | all-basis | proof | veriq | module:function | file.py:function")
    bc.add_argument("--bench")
    bc.add_argument("--out", "-o", help="write the evaluation JSON here")
    bc.add_argument("--limit", type=int, help="evaluate a deterministic subsample of about this many wrong mutants")
    bc.add_argument("--tasks", help="comma-separated task ids")
    bc.add_argument("--no-negatives", action="store_true", help="skip the 28 correct originals")
    bc.add_argument("--shots", type=int, default=4096)
    bc.add_argument("--seed", type=int, default=7)
    bc.add_argument("--timeout", type=float, default=30.0)
    bc.add_argument("--quiet", "-q", action="store_true")
    bl = bs.add_parser("leaderboard", help="render a static leaderboard (Markdown + self-contained HTML)")
    bl.add_argument("--run", required=True, help="JSON written by `veriq bench run --out`")
    bl.add_argument("--corpus-eval", nargs="*", default=[], help="JSON files written by `veriq bench corpus-eval --out`")
    bl.add_argument("--out-dir", required=True)

    k = sub.add_parser("keygen", help="generate an Ed25519 key pair for signing certificates")
    k.add_argument("--out", "-o", default="veriq-signing.key", help="private key path (public key: <out>.pub)")
    k.add_argument("--pub", help="public key path (default: private path with .pub)")
    k.add_argument("--passphrase-env", help="encrypt the private key with the passphrase in this env variable")
    k.add_argument("--force", action="store_true", help="overwrite existing files")

    cf = sub.add_parser("certify", help="sign an existing (unsigned) certificate")
    cf.add_argument("certificate")
    cf.add_argument("--key", "-k", help="Ed25519 private key (PEM); default $VERIQ_SIGNING_KEY")
    cf.add_argument("--out", "-o", help="output path (default: overwrite the input)")

    ce = sub.add_parser("cert", help="work with verification certificates")
    ces = ce.add_subparsers(dest="cert_cmd", required=True)
    cv = ces.add_parser("verify", help="check signature, circuit hashes and semantics; optionally re-run the proof")
    cv.add_argument("certificate")
    cv.add_argument("--key", "-k", help="trusted Ed25519 PUBLIC key (PEM) the certificate must be signed by")
    cv.add_argument("--circuit", action="append", default=[], metavar="FILE",
                    help="circuit file(s) to re-hash, in certificate input order (candidate, then reference)")
    cv.add_argument("--recheck", action="store_true", help="re-run the checks / proof and compare the verdict")
    cv.add_argument("--allow-unsigned", action="store_true", help="do not fail on an unsigned certificate")
    cv.add_argument("--timeout", type=float, help="proof timeout for --recheck (default: the certified one)")
    cv.add_argument("--json", dest="json_out", help="write the verification result as JSON here")
    cv.add_argument("--quiet", "-q", action="store_true")

    m = sub.add_parser("mcp", help="run Veriq as an MCP server (stdio by default; executes circuit code in a sandbox)")
    try:
        from .mcp_server import build_parser as mcp_parser

        mcp_parser(m)
    except ImportError:  # the `mcp` SDK is an optional extra
        m.set_defaults(mcp_missing=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "mcp":
        if getattr(args, "mcp_missing", False):
            print("veriq: error: the MCP SDK is not installed; run: pip install 'veriq[mcp]'", file=sys.stderr)
            return 3
        from . import mcp_server

        return mcp_server.main(args=args)
    if args.cmd == "repair":
        return _repair_cmd(args)
    if args.cmd == "optimize":
        return _optimize_cmd(args)
    if args.cmd == "preflight":
        return _preflight_cmd(args)
    if args.cmd == "bench":
        return _bench_cmd(args)
    if args.cmd in ("keygen", "certify", "cert"):
        return _cert_cmd(args)
    if args.cmd == "ci":
        from . import ci

        return ci.main(args)
    from .certificate import utc_now

    started = utc_now()
    try:
        report = run_checks(args.file, reference=args.reference, expect=args.expect, backend=args.backend,
                            shots=args.shots, seed=args.seed, timeout=args.timeout, mode=args.mode,
                            allowed_gates=[g.strip() for g in args.allowed_gates.split(",") if g.strip()]
                            if args.allowed_gates else None,
                            function=args.function, reference_function=args.reference_function,
                            coupling=args.coupling, no_black_boxes=args.no_black_boxes)
    except (LoadError, ValueError, OSError) as exc:
        print(f"veriq: error: {exc}", file=sys.stderr)
        return 3

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_html(report))
    json_out = args.json_out or (str(Path(args.report).with_suffix(".json")) if args.report else None)
    if json_out:
        Path(json_out).write_text(render_json(report))

    if args.repair_report:
        _write_repair_report(args, report)
    if args.certificate:
        rc = _emit_check_certificate(args, report, started)
        if rc:
            return rc

    if not args.quiet:
        print(f"Veriq  {report.target}" + (f"  vs  {report.reference}" if report.reference else ""))
        for c in report.checks:
            print(f"  {SYMBOL[c.status.value]} {c.status.value:<12} {c.name:<24} {c.summary}")
        print(f"  => VERDICT: {report.verdict.value}  ({report.seconds:.2f}s)")
        if args.report:
            print(f"  report: {args.report}" + (f"  json: {json_out}" if json_out else ""))
        if args.repair_report:
            print(f"  repair report: {args.repair_report}")
        if args.certificate:
            print(f"  certificate: {args.certificate}")
    return EXIT[report.verdict]


def _emit_check_certificate(args, report, started) -> int:
    from .certificate import CertificateError, certificate_from_report, write_certificate

    opts = {"mode": args.mode, "allowed_gates": _gates(args.allowed_gates), "coupling": args.coupling,
            "no_black_boxes": args.no_black_boxes, "backend": args.backend, "shots": args.shots,
            "seed": args.seed, "timeout": args.timeout, "expect": _expect_obj(args.expect)}
    try:
        cert = certificate_from_report(report, kind="verify", candidate_path=args.file,
                                       reference_path=args.reference, function=args.function,
                                       reference_function=args.reference_function, options=opts, started=started)
        write_certificate(cert, args.certificate, args.sign_key, sign_env=True)
    except (CertificateError, OSError) as exc:
        print(f"veriq: certificate error: {exc}", file=sys.stderr)
        return 3
    return 0


def _expect_obj(expect):
    if expect is None:
        return None
    from .runner import parse_expect

    try:
        return parse_expect(expect)
    except Exception:  # noqa: BLE001
        return None


def _write_repair_report(args, report) -> None:
    import json

    from .loader import load_circuit
    from .repair_report import SCHEMA, build_repair_report

    rd = report.to_dict()
    try:
        cand = load_circuit(args.file, args.function)
        ref = load_circuit(args.reference, args.reference_function) if args.reference else None
    except Exception as exc:  # the candidate does not build: the failing Build check is the whole story
        out = {"schema": SCHEMA, "verdict": rd["verdict"], "mode": args.mode,
               "failing_checks": [{"name": c["name"], "summary": c["summary"]} for c in rd["checks"]
                                  if c["status"] == "FAIL"],
               "counterexample": None, "localization": {"available": False, "reason": f"does not build: {exc}"[:300]},
               "hardware_violations": [], "metric_deltas": {}, "hints": ["Fix the build error first."]}
    else:
        out = build_repair_report(cand, ref, args.mode, result=rd,
                                  localize_circuit=rd["verdict"] != "PASS")
    Path(args.repair_report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.repair_report).write_text(json.dumps(out, indent=1, default=str))




def _gates(spec):
    return [g.strip() for g in spec.split(",") if g.strip()] if spec else None


def _repair_cmd(args) -> int:
    import json

    from .loader import load_circuit
    from .repair import load_fixer, repair_loop

    try:
        cand = load_circuit(args.file, args.function)
        ref = load_circuit(args.reference, args.reference_function)
        fixer = load_fixer(args.fixer)
    except (LoadError, ValueError, OSError, ImportError, AttributeError) as exc:
        print(f"veriq: error: {exc}", file=sys.stderr)
        return 3
    src = Path(args.file).read_text()
    res = repair_loop(cand, ref, fixer, mode=args.mode, max_attempts=args.max_attempts, source=src,
                      allowed_gates=_gates(args.allowed_gates), coupling=args.coupling,
                      no_black_boxes=args.no_black_boxes, timeout=args.timeout)
    if args.out and res["verdict"] == "PASS" and res["final_qasm"]:
        Path(args.out).write_text(res["final_qasm"])
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({k: v for k, v in res.items() if k != "final_circuit"},
                                                  indent=1, default=str))
    if not args.quiet:
        for h in res["history"]:
            fix = f"  after: {h['fix']}" if h.get("fix") else ""
            print(f"  attempt {h['attempt']}: {h['verdict']}{fix}")
        print(f"  => {res['verdict']} (stop: {res['stop_reason']}, {res['attempts']} fix(es), {res['seconds']:.2f}s)")
        if args.out and res["verdict"] == "PASS":
            print(f"  fixed circuit: {args.out}")
    return EXIT[Status(res["verdict"])] if res["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE") else 1


def _optimize_cmd(args) -> int:
    import json

    from .loader import load_circuit
    from .optimize import optimize_circuit

    try:
        qc = load_circuit(args.file, args.function)
    except (LoadError, ValueError, OSError) as exc:
        print(f"veriq: error: {exc}", file=sys.stderr)
        return 3
    from .certificate import utc_now

    started = utc_now()
    res = optimize_circuit(qc, mode=args.mode, basis_gates=_gates(args.basis), coupling=args.coupling,
                           seeds=args.seeds, timeout=args.timeout, budget=args.budget,
                           allow_permutation=args.allow_permutation)
    if args.out and res.get("best_qasm"):
        Path(args.out).write_text(res["best_qasm"])
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({k: v for k, v in res.items() if k != "best_circuit"},
                                                  indent=1, default=str))
    if args.certificate:
        from .certificate import CertificateError, certificate_from_optimize, write_certificate

        try:
            cert = certificate_from_optimize(
                res, qc, path=args.file, function=args.function, started=started,
                options={"coupling": args.coupling, "allow_permutation": args.allow_permutation,
                         "timeout": args.timeout, "budget": args.budget, "seeds": args.seeds})
            write_certificate(cert, args.certificate, args.sign_key, sign_env=True)
        except (CertificateError, OSError) as exc:
            print(f"veriq: certificate error: {exc}", file=sys.stderr)
            return 3
    if not args.quiet:
        b = res.get("best")
        print(f"Veriq optimize  {args.file}")
        print(f"  source (as compiled at opt=0): cx={res['baseline']['cx']} depth={res['baseline']['depth']}")
        print(f"  candidates: {res['counts']}")
        if b:
            print(f"  best PROVEN: {b['config']}  cx={b['cx']} depth={b['depth']}  ({b['method']})")
        else:
            print("  no candidate could be proven equivalent; nothing returned")
    return 0 if res.get("best") else 2


def _preflight_cmd(args) -> int:
    import json

    from .certificate import utc_now
    from .loader import load_circuit
    from .preflight import PreflightError, preflight, render_text, to_json

    started = utc_now()
    try:
        qc = load_circuit(args.file, args.function)
        ref = load_circuit(args.reference, args.reference_function) if args.reference else None
        levels = tuple(int(x) for x in args.levels.split(",") if x.strip())
        res = preflight(qc, args.backend, reference=ref, mode=args.mode, seeds=args.seeds, levels=levels,
                        min_esp=args.min_esp, warn_esp=args.warn_esp, max_cx=args.max_cx,
                        max_duration=args.max_duration, warn_t2_fraction=args.warn_t2_fraction,
                        noisy_sim=args.noisy_sim, max_tvd=args.max_tvd, shots=args.shots, timeout=args.timeout)
    except (LoadError, PreflightError, ValueError, OSError) as exc:
        print(f"veriq: error: {exc}", file=sys.stderr)
        return 3
    if args.out and res.get("compiled_circuit") is not None:
        from qiskit import qasm2

        Path(args.out).write_text(qasm2.dumps(res["compiled_circuit"]))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(to_json(res), indent=1, default=str))
    if args.certificate:
        from .certificate import CertificateError, certificate_from_preflight, write_certificate

        try:
            cert = certificate_from_preflight(res, qc, path=args.file, function=args.function, reference_qc=ref,
                                              reference_path=args.reference,
                                              reference_function=args.reference_function, started=started)
            write_certificate(cert, args.certificate, args.sign_key, sign_env=True)
        except (CertificateError, OSError) as exc:
            print(f"veriq: certificate error: {exc}", file=sys.stderr)
            return 3
    if not args.quiet:
        print(render_text(res))
        if args.certificate:
            print(f"  certificate: {args.certificate}")
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[res["verdict"]]


def _cert_cmd(args) -> int:
    import json

    from . import certificate as C

    try:
        if args.cmd == "keygen":
            pw = None
            if args.passphrase_env:
                pw = os.environ.get(args.passphrase_env)
                if not pw:
                    raise C.CertificateError(f"${args.passphrase_env} is empty or unset")
                pw = pw.encode()
            r = C.generate_keypair(args.out, args.pub, passphrase=pw, overwrite=args.force)
            print(f"private key: {r['private']}  (mode 600; keep it secret, never commit it)")
            print(f"public key:  {r['public']}  (share this; verifiers pass it to `veriq cert verify --key`)")
            print(f"key id:      {r['key_id']}")
            return 0
        if args.cmd == "certify":
            cert = C.read_certificate(args.certificate)
            signed = C.sign_certificate(cert, C.load_private_key(args.key))
            out = args.out or args.certificate
            Path(out).write_text(json.dumps(signed, indent=1, default=str) + "\n")
            print(f"signed {out} with key {signed['signature']['key_id']} "
                  f"(verdict {signed['verdict']}, claim {signed['claim']})")
            return 0
        cert = C.read_certificate(args.certificate)
        pub = C.load_public_key(args.key) if args.key else None
        r = C.verify_certificate(cert, public_key=pub, circuits=args.circuit, recheck=args.recheck,
                                 allow_unsigned=args.allow_unsigned, timeout=args.timeout)
    except (C.CertificateError, OSError) as exc:
        print(f"veriq: error: {exc}", file=sys.stderr)
        return 3
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(r, indent=1))
    if not args.quiet:
        print(f"Veriq certificate  {args.certificate}  ({cert.get('kind')}, verdict {r['verdict']}, claim {r['claim']})")
        for x in r["results"]:
            mark = {True: "✔", False: "✘", None: "·"}[x["ok"]]
            print(f"  {mark} {x['check']:<22} {x['detail']}")
        state = "VALID" if r["ok"] else "INVALID"
        if r["ok"] and not r["trusted"]:
            state += " (integrity only: signer not pinned with --key)" if cert.get("signature") else " (unsigned)"
        print(f"  => {state}")
    return 0 if r["ok"] else 1


def _csv(x: str | None) -> list[str] | None:
    return [t.strip() for t in x.split(",") if t.strip()] if x else None


def _bench_cmd(args) -> int:
    import json

    from . import bench

    say = (lambda m: None) if getattr(args, "quiet", False) else (lambda m: print(m, flush=True))
    if args.bench_cmd == "run":
        res = bench.run_bench(args.model_outputs, bench=args.bench, optimize=not args.no_optimize, budget=args.budget,
                              seeds=args.seeds, timeout=args.timeout, only_tasks=_csv(args.tasks),
                              only_models=_csv(args.models), progress=say)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(res, indent=1, default=str))
        for m, s in res["summary"].items():
            say(f"{m:14s} pass {s['pass']}/{s['tasks']}  correct {s['correct']}  compliant {s['compliant']}  "
                f"CX {s['cx_total_pass']} (best {s['best_cx_total_pass']})  ratio {s['cx_ratio_geomean']}")
        return 0 if res["summary"] else 2
    if args.bench_cmd == "corpus-eval":
        res = bench.corpus_eval(args.detector, bench=args.bench, negatives=not args.no_negatives, limit=args.limit,
                                only_tasks=_csv(args.tasks), shots=args.shots, seed=args.seed, timeout=args.timeout,
                                progress=say)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(res, indent=1))
        s = res["summary"]
        say(f"{res['detector']}: recall {s['detected']}/{s['wrong_mutants']} = {s['recall']}, false positives "
            f"{s['false_positives']}/{s['negatives']}, undecided {s['undecided_on_wrong']}, {res['seconds']}s")
        for c, v in s["by_study_class"].items():
            say(f"  {c:45s} {v['detected']}/{v['n']}")
        return 0
    if args.bench_cmd == "leaderboard":
        run = json.loads(Path(args.run).read_text())
        evals = [json.loads(Path(p).read_text()) for p in args.corpus_eval]
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "leaderboard.md").write_text(bench.render_leaderboard_md(run, evals))
        (out / "leaderboard.html").write_text(bench.render_leaderboard_html(run, evals))
        print(f"wrote {out / 'leaderboard.md'} and {out / 'leaderboard.html'}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
