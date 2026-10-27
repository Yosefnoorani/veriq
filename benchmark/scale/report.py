"""Turn results.json into results.md and time_vs_qubits.png (works on partial results)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHORT = {"PROVEN_EQUIVALENT": "PROVEN", "NOT_EQUIVALENT": "NOT", "PROBABLY_EQUIVALENT": "PROBABLY*",
         "UNKNOWN": "unknown", "TIMEOUT": "timeout", "ERROR": "error"}
DECIDED = {"PROVEN_EQUIVALENT", "NOT_EQUIVALENT"}
ORDER = ["ghz", "clifford", "clifford_t", "cuccaro", "qft", "qft_approx", "oracle", "blocks"]
METHODS = ["clifford-tableau", "qcec-zx", "qcec-alternating", "qcec-construction", "qcec-simulation", "mps-falsify"]


def cell(r: dict | None) -> str:
    if r is None:
        return "not run"
    t = r.get("seconds", r["wall_seconds"]) if r["status"] not in ("TIMEOUT", "ERROR") else r["wall_seconds"]
    m = r.get("method", "")
    m = m.replace("partition+", "part+").replace("qcec-", "")
    flag = " †" if "earlier engine revision" in (r.get("note") or "") else ""
    return f"{SHORT[r['status']]} · {m} · {t:.1f}s · {r['peak_rss_mb']:.0f}MB{flag}"


def main() -> None:
    data = json.loads((HERE / "results.json").read_text())
    res = data["results"]
    idx = {(r["family"], r["n"], r["variant"], r["method_requested"]): r for r in res}
    fams = [f for f in ORDER if any(r["family"] == f for r in res)]
    lines = ["# Scaling benchmark", "",
             f"Generated from `results.json` ({len(res)} runs, data written {data['generated']}). "
             f"{data['cpus']} CPUs, 3 cases in parallel, each in a fresh process hard-killed at "
             f"{data['auto_cap_s']:.0f}s (auto) / {data['sweep_cap_s']:.0f}s (single-method sweeps). "
             "Memory is peak RSS of the case process tree (≈135 MB is the Python + Qiskit baseline).", "",
             "**Legend.** `PROVEN` = equivalence proven (Clifford tableau, QCEC, exact MPS state overlap). "
             "`NOT` = non-equivalence decided (proof or concrete witness). "
             "`PROBABLY*` = **falsification only**: no difference found on the simulated inputs; veriq reports this "
             "as INCONCLUSIVE and never as a proof. `unknown` = method not applicable / gave up. "
             "`timeout` = killed at the cap. `not run` = cell not reached (series stopped or session cut short). "
             "`†` = measured with the earlier engine revision 6b1420b (oracle correct n≥12; the rerun was interrupted).", "",
             "## Auto pipeline (what `verify`/`compare` use)", ""]
    sizes = sorted({r["n"] for r in res if r["method_requested"] == "auto"})
    for variant in ("correct", "bug"):
        lines += [f"### {variant} version", "", "| family | " + " | ".join(f"n={n}" for n in sizes) + " |",
                  "|---|" + "---|" * len(sizes)]
        for f in fams:
            lines.append(f"| {f} | " + " | ".join("n/a" if n > 50 and f not in ("ghz", "clifford") else
                                                     cell(idx.get((f, n, variant, "auto"))) for n in sizes) + " |")
        lines.append("")
    # honesty summary
    summ = defaultdict(lambda: defaultdict(int))
    for r in res:
        if r["method_requested"] != "auto":
            continue
        cls = "decided" if r["status"] in DECIDED else "falsification-only" if r["status"] == "PROBABLY_EQUIVALENT" \
            else "inconclusive"
        summ[(r["family"], r["variant"])][cls] += 1
    lines += ["### Summary: decided vs falsification-only vs inconclusive (auto)", "",
              "| family | variant | decided | falsification-only | inconclusive |", "|---|---|---|---|---|"]
    for f in fams:
        for v in ("correct", "bug"):
            s = summ[(f, v)]
            lines.append(f"| {f} | {v} | {s['decided']} | {s['falsification-only']} | {s['inconclusive']} |")
    ran = sorted({r["method_requested"] for r in res} - {"auto"})
    missing = [m for m in METHODS if m not in ran]
    lines += ["", "## Single-method sweeps", "",
              "Each method alone (no partitioning), same circuits. A series stops after its first timeout, so "
              "cells after a timeout read `not run`."
              + (f" **Not run at all (session cut short):** {', '.join(missing)}." if missing else ""), ""]
    for f in fams:
        rows = [m for m in METHODS if any(k[0] == f and k[3] == m for k in idx)]
        if not rows:
            continue
        ns = sorted({k[1] for k in idx if k[0] == f and k[3] in rows})
        lines += [f"### {f}", "", "| method | variant | " + " | ".join(f"n={n}" for n in ns) + " |",
                  "|---|---|" + "---|" * len(ns)]
        for m in rows:
            for v in ("correct", "bug"):
                lines.append(f"| {m} | {v} | " + " | ".join(cell(idx.get((f, n, v, m))) for n in ns) + " |")
        lines.append("")
    lines += ["![time vs qubits](time_vs_qubits.png)", ""]
    (HERE / "results.md").write_text("\n".join(lines))
    plot(res, fams)


def plot(res: list[dict], fams: list[str]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cols = 4
    rows = (len(fams) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.6 * rows), squeeze=False)
    colors = dict(zip(["auto"] + METHODS, plt.cm.tab10.colors))
    for ax, f in zip(axes.flat, fams):
        for m in ["auto"] + METHODS:
            for v, ls in (("correct", "-"), ("bug", "--")):
                pts = sorted((r["n"], r) for r in res if r["family"] == f and r["method_requested"] == m
                             and r["variant"] == v and r["n"] <= 50)
                if not pts:
                    continue
                xs = [n for n, _ in pts]
                ys = [r["wall_seconds"] for _, r in pts]
                ax.plot(xs, ys, ls, color=colors[m], lw=1.4, label=m if v == "correct" else None)
                for n, r in pts:
                    st = r["status"]
                    mk, fill = ("o", True) if st in DECIDED else ("o", False) if st == "PROBABLY_EQUIVALENT" \
                        else ("x", True)
                    ax.plot([n], [r["wall_seconds"]], mk, color=colors[m], ms=5,
                            mfc=colors[m] if fill else "none")
        ax.set_title(f)
        ax.set_yscale("log")
        ax.set_xlabel("qubits")
        ax.set_ylabel("wall time (s)")
        ax.grid(alpha=0.3)
    for ax in list(axes.flat)[len(fams):]:
        ax.axis("off")
    h, l = axes.flat[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower right", fontsize=9, title="solid=correct, dashed=bug\n● decided  ○ PROBABLY  × timeout/unknown")
    fig.suptitle("veriq scale: wall time vs qubits per method (log scale)")
    fig.tight_layout()
    fig.savefig(HERE / "time_vs_qubits.png", dpi=110)


if __name__ == "__main__":
    main()
