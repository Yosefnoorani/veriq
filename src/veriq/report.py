"""Self-contained HTML (and JSON) report rendering. No external assets."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from .models import Report, Status

COLORS = {
    Status.PASS: ("#0f7b3f", "#e3f6ea"),
    Status.FAIL: ("#b42318", "#fdecea"),
    Status.INCONCLUSIVE: ("#9a6700", "#fff6db"),
    Status.SKIPPED: ("#57606a", "#eef1f4"),
}

CSS = """
*{box-sizing:border-box}body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1f2328}
.wrap{max-width:1040px;margin:0 auto;padding:28px 20px 60px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}
h1{font-size:22px;margin:0}h1 small{font-weight:400;color:#57606a;font-size:14px;margin-left:8px}
h2{font-size:16px;margin:0 0 10px}
.meta{color:#57606a;font-size:13px;margin-top:4px}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-weight:700;font-size:12px;letter-spacing:.04em}
.verdict{font-size:20px;padding:10px 22px;border-radius:12px;font-weight:800;letter-spacing:.05em}
.card{background:#fff;border:1px solid #d8dee4;border-radius:12px;padding:16px 18px;margin:14px 0}
.check-head{display:flex;justify-content:space-between;align-items:center;gap:12px}
.check-head h2{margin:0}.time{color:#57606a;font-size:12px}
.summary{margin:8px 0 6px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}
th,td{border-bottom:1px solid #eaeef2;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f6f8fa;font-weight:600}
pre{background:#0d1117;color:#e6edf3;padding:12px;border-radius:8px;overflow:auto;font-size:12px;line-height:1.35}
details summary{cursor:pointer;color:#0969da;font-size:13px;margin-top:6px}
.bar{display:flex;align-items:center;gap:6px;font-family:ui-monospace,Menlo,monospace;font-size:12px;margin:2px 0}
.bar .lab{width:90px;text-align:right}.bar .track{flex:1;position:relative;height:16px;background:#f0f2f5;border-radius:4px}
.bar .obs{position:absolute;left:0;top:0;bottom:0;background:#4c8bf5;border-radius:4px;opacity:.85}
.bar .exp{position:absolute;top:-2px;bottom:-2px;width:2px;background:#d1242f}
.bar .val{width:120px;color:#57606a}
.legend{font-size:12px;color:#57606a;margin:6px 0}.legend i{display:inline-block;width:10px;height:10px;margin:0 4px 0 10px;vertical-align:middle}
.cex{border-left:4px solid #b42318;background:#fff5f4;padding:10px 12px;border-radius:6px;margin-top:8px;font-size:13px}
footer{color:#57606a;font-size:12px;margin-top:24px}
code{font-family:ui-monospace,Menlo,monospace;font-size:12px}
"""


def _badge(status: Status, big: bool = False) -> str:
    fg, bg = COLORS[status]
    cls = "verdict" if big else "badge"
    return f'<span class="{cls}" style="color:{fg};background:{bg};border:1px solid {fg}33">{status.value}</span>'


def _e(x: Any) -> str:
    return html.escape(str(x))


def _kv_table(d: dict[str, Any], skip: tuple[str, ...] = ()) -> str:
    rows = []
    for k, v in d.items():
        if k in skip:
            continue
        val = json.dumps(v) if isinstance(v, (dict, list)) else v
        rows.append(f"<tr><th>{_e(k)}</th><td><code>{_e(val)}</code></td></tr>")
    return f"<table>{''.join(rows)}</table>" if rows else ""


def _histogram(ev: dict[str, Any]) -> str:
    counts = ev.get("observed_counts", {})
    shots = ev.get("shots", 1) or 1
    exp = ev.get("expected_distribution", {})
    keys = sorted(set(counts) | set(exp))
    keys = sorted(keys, key=lambda k: -(counts.get(k, 0) / shots + exp.get(k, 0)))[:16]
    out = ['<div class="legend">observed<i style="background:#4c8bf5"></i> expected<i style="background:#d1242f"></i></div>']
    for k in keys:
        o = counts.get(k, 0) / shots
        e = exp.get(k)
        marker = f'<div class="exp" style="left:{min(e, 1) * 100:.2f}%"></div>' if e is not None else ""
        etxt = f" / {e:.3f}" if e is not None else ""
        out.append(
            f'<div class="bar"><span class="lab">|{_e(k)}&gt;</span><div class="track">'
            f'<div class="obs" style="width:{o * 100:.2f}%"></div>{marker}</div>'
            f'<span class="val">{o:.3f}{etxt}</span></div>'
        )
    return "".join(out)


def _metrics_table(m: dict[str, Any]) -> str:
    cols = [("source", m["source"])] + [(f"compiled: {k}", v) for k, v in m.get("compiled", {}).items()]
    if "reference" in m:
        cols.append(("reference", m["reference"]))
    fields = ["qubits", "depth", "size", "two_qubit_gates", "multi_qubit_gates"]
    head = "".join(f"<th>{_e(c[0])}</th>" for c in cols)
    rows = []
    for f in fields:
        rows.append(f"<tr><th>{f}</th>" + "".join(f"<td>{_e(c[1].get(f))}</td>" for c in cols) + "</tr>")
    rows.append("<tr><th>gate counts</th>" + "".join(
        f"<td><code>{_e(', '.join(f'{k}:{v}' for k, v in c[1]['gate_counts'].items()))}</code></td>" for c in cols) + "</tr>")
    return f"<table><tr><th>metric</th>{head}</tr>{''.join(rows)}</table>"


def render_html(report: Report) -> str:
    cards = []
    for c in report.checks:
        body = [f'<p class="summary">{_e(c.summary)}</p>']
        ev = c.evidence
        if c.name.startswith("Transpile") and ev.get("targets"):
            rows = "".join(
                f"<tr><td>{_e(t.get('target'))}</td><td><b>{_e(t.get('result'))}</b></td>"
                f"<td><code>{_e(t.get('engine', ''))} {_e(t.get('qcec_result', ''))}</code></td>"
                f"<td>{_e(t.get('qcec_check_time_s', ''))}</td></tr>"
                for t in ev["targets"])
            body.append(f"<table><tr><th>target</th><th>result</th><th>engine / raw</th><th>check s</th></tr>{rows}</table>")
        elif c.name.startswith("Reference"):
            cex = ev.get("counterexample")
            body.append(_kv_table(ev, skip=("counterexample",)))
            if cex:
                body.append(
                    f'<div class="cex"><b>Counterexample</b> &mdash; input <code>{_e(cex["input_state"])}</code>, '
                    f'state fidelity <code>{cex["fidelity"]}</code>'
                    + (f'<br><i>{_e(cex["note"])}</i>' if cex.get("note") else "")
                    + f'<br>candidate output (top): <code>{_e(json.dumps(cex["candidate_output_top"]))}</code>'
                    f'<br>reference output (top): <code>{_e(json.dumps(cex["reference_output_top"]))}</code></div>')
        elif c.name.startswith("Statistical") and ev:
            body.append(_kv_table(ev, skip=("observed_counts", "expected_distribution")))
            if "observed_counts" in ev:
                body.append(_histogram(ev))
        elif c.name == "Metrics":
            body.append(_metrics_table(ev))
        cards.append(
            f'<section class="card"><div class="check-head"><h2>{_e(c.name)}</h2>'
            f'<div>{_badge(c.status)} <span class="time">{c.seconds:.3f}s</span></div></div>{"".join(body)}</section>')

    circuits = f'<details open><summary>Candidate circuit</summary><pre>{_e(report.circuit_text)}</pre></details>'
    if report.reference_text:
        circuits += f'<details><summary>Reference circuit</summary><pre>{_e(report.reference_text)}</pre></details>'

    versions = ", ".join(f"{k} {v}" for k, v in report.versions.items())
    raw = _e(json.dumps(report.to_dict(), indent=2))
    ref_line = f" &middot; reference <code>{_e(report.reference)}</code>" if report.reference else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Veriq report: {_e(report.target)}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><div><h1>Veriq report<small>truth layer for AI-written quantum code</small></h1>
<div class="meta">target <code>{_e(report.target)}</code>{ref_line} &middot; {report.seconds:.2f}s &middot; {datetime.now().strftime('%Y-%m-%d %H:%M')}</div></div>
<div>{_badge(report.verdict, big=True)}</div></header>
{''.join(cards)}
<section class="card"><h2>Circuits</h2>{circuits}</section>
<section class="card"><h2>Raw JSON</h2><details><summary>show</summary><pre>{raw}</pre></details></section>
<footer>Generated by Veriq &middot; {_e(versions)}</footer>
</div></body></html>"""


def render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2)
