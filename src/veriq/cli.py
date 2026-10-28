"""Command-line interface: `veriq check <file> [--reference R] [--expect JSON] --report out.html`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .loader import LoadError
from .models import Status
from .report import render_html, render_json
from .runner import run_checks

EXIT = {Status.PASS: 0, Status.FAIL: 1, Status.INCONCLUSIVE: 2}
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
    ci.add_argument("--quiet", "-q", action="store_true")

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
    if args.cmd == "ci":
        from . import ci

        return ci.main(args)
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

    if not args.quiet:
        print(f"Veriq  {report.target}" + (f"  vs  {report.reference}" if report.reference else ""))
        for c in report.checks:
            print(f"  {SYMBOL[c.status.value]} {c.status.value:<12} {c.name:<24} {c.summary}")
        print(f"  => VERDICT: {report.verdict.value}  ({report.seconds:.2f}s)")
        if args.report:
            print(f"  report: {args.report}" + (f"  json: {json_out}" if json_out else ""))
        if args.repair_report:
            print(f"  repair report: {args.repair_report}")
    return EXIT[report.verdict]


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


if __name__ == "__main__":
    sys.exit(main())
