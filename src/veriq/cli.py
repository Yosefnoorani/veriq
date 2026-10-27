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
    c = sub.add_parser("check", help="run all checks on a circuit (.py or .qasm)")
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
    c.add_argument("--quiet", "-q", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_checks(args.file, reference=args.reference, expect=args.expect, backend=args.backend,
                            shots=args.shots, seed=args.seed, timeout=args.timeout, mode=args.mode,
                            allowed_gates=[g.strip() for g in args.allowed_gates.split(",") if g.strip()]
                            if args.allowed_gates else None,
                            function=args.function, reference_function=args.reference_function)
    except (LoadError, ValueError, OSError) as exc:
        print(f"veriq: error: {exc}", file=sys.stderr)
        return 3

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_html(report))
    json_out = args.json_out or (str(Path(args.report).with_suffix(".json")) if args.report else None)
    if json_out:
        Path(json_out).write_text(render_json(report))

    if not args.quiet:
        print(f"Veriq  {report.target}" + (f"  vs  {report.reference}" if report.reference else ""))
        for c in report.checks:
            print(f"  {SYMBOL[c.status.value]} {c.status.value:<12} {c.name:<24} {c.summary}")
        print(f"  => VERDICT: {report.verdict.value}  ({report.seconds:.2f}s)")
        if args.report:
            print(f"  report: {args.report}" + (f"  json: {json_out}" if json_out else ""))
    return EXIT[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
