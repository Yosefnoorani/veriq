"""Scaling benchmark for veriq.scale.decide_equivalence.

Every case runs in a fresh subprocess that is hard-killed at its cap, and results.json is rewritten after
every case, so an interrupted run keeps everything finished so far (re-running resumes and skips done cases).

    python benchmark/scale/run.py                 # auto pipeline + per-method sweeps
    python benchmark/scale/run.py --only auto     # just the auto pipeline
    python benchmark/scale/run.py --case qft 24 0 qcec-zx   # one case, prints a JSON line (used internally)

Statuses: PROVEN_EQUIVALENT, NOT_EQUIVALENT (both decided), PROBABLY_EQUIVALENT (falsification only, never
a proof), UNKNOWN (method gave up / not applicable), TIMEOUT (killed at the cap).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

SIZES = [8, 12, 16, 20, 24, 32, 40, 50]
EXTRA = {"clifford": [100, 200], "ghz": [100, 200]}
AUTO_CAP = 120.0          # hard kill (s); the engine gets AUTO_CAP - 10 as its own budget
SWEEP_CAP = 75.0          # per-method sweeps are capped lower to keep the full grid tractable
METHODS = {                # method label -> decide_equivalence strategies
    "auto": None,
    "clifford-tableau": ["clifford"],
    "qcec-zx": ["zx"],
    "qcec-alternating": ["alternating"],
    "qcec-construction": ["construction"],
    "qcec-simulation": ["simulation"],
    "mps-falsify": ["falsify"],
}
CLIFFORD_FAMILIES = {"ghz", "clifford"}


def run_case(family: str, n: int, bug: bool, method: str, cap: float) -> dict:
    """Child-process body: build circuits, decide, return a record."""
    import warnings
    warnings.filterwarnings("ignore")
    from families import build
    from veriq import scale
    t = time.perf_counter()
    a, b, mode = build(family, n, bug)
    build_s = time.perf_counter() - t
    strategies = METHODS[method]
    import psutil
    started = time.time() - psutil.Process().create_time()  # imports + build already used part of the cap
    budget = cap - (10 if method == "auto" else 8) - started
    r = scale.decide_equivalence(a, b, mode, timeout=budget,
                                 strategies=strategies, use_partition=(method == "auto"))
    ev = r.get("evidence", {})
    ce = ev.get("counterexample") or {}
    return {"status": r["status"], "method": r["method"], "seconds": r["seconds"], "build_seconds": round(build_s, 3),
            "mode": mode, "gates": [sum(a.count_ops().values()), sum(b.count_ops().values())],
            "counterexample": {k: ce[k] for k in ("input", "fidelity") if k in ce} or None,
            "note": (ev.get("note") or "")[:160]}


def spawn(family: str, n: int, bug: bool, method: str, cap: float) -> dict:
    import psutil
    env = dict(os.environ, OMP_NUM_THREADS="2", PYTHONWARNINGS="ignore")
    t0 = time.perf_counter()
    p = subprocess.Popen([sys.executable, "-u", __file__, "--case", family, str(n), str(int(bug)), method,
                          "--cap", str(cap)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
    proc = psutil.Process(p.pid)
    peak = 0
    killed = False
    while p.poll() is None:
        try:
            rss = proc.memory_info().rss + sum(c.memory_info().rss for c in proc.children(recursive=True))
            peak = max(peak, rss)
        except psutil.Error:
            pass
        if time.perf_counter() - t0 > cap:
            for c in proc.children(recursive=True):
                c.kill()
            p.kill()
            killed = True
            break
        time.sleep(0.2)
    out = p.communicate()[0] if not killed else ""
    wall = time.perf_counter() - t0
    rec = {"family": family, "n": n, "variant": "bug" if bug else "correct", "method_requested": method,
           "wall_seconds": round(wall, 2), "peak_rss_mb": round(peak / 2**20, 1), "cap_seconds": cap}
    line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("{")), None)
    if killed:
        rec.update(status="TIMEOUT", method=method)
    elif line is None:
        rec.update(status="ERROR", method=method, note=f"exit code {p.returncode}")
    else:
        rec.update(json.loads(line))
    return rec


def key(r: dict) -> tuple:
    return (r["family"], r["n"], r["variant"], r["method_requested"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", nargs=4)
    ap.add_argument("--cap", type=float, default=AUTO_CAP)
    ap.add_argument("--only", choices=["auto", "sweep"])
    ap.add_argument("--families", default=None)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", default=str(HERE / "results.json"))
    args = ap.parse_args()
    if args.case:
        f, n, bug, m = args.case
        print(json.dumps(run_case(f, int(n), bool(int(bug)), m, args.cap)), flush=True)
        return

    from families import FAMILIES
    fams = args.families.split(",") if args.families else FAMILIES
    out = Path(args.out)
    results = json.loads(out.read_text())["results"] if out.exists() else []
    done = {key(r) for r in results}

    def save() -> None:
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d %H:%M:%S %z"), "cpus": os.cpu_count(),
                                   "auto_cap_s": AUTO_CAP, "sweep_cap_s": SWEEP_CAP, "results": results}, indent=1))
        tmp.replace(out)

    # A "series" is one (family, variant, method) over increasing n; it stops after the first TIMEOUT.
    series = []
    if args.only in (None, "auto"):
        series += [(f, bug, "auto", AUTO_CAP) for f in fams for bug in (False, True)]
    if args.only in (None, "sweep"):
        for m in METHODS:
            if m == "auto":
                continue
            for f in fams:
                if f == "blocks" or (m == "clifford-tableau" and f not in CLIFFORD_FAMILIES):
                    continue
                series += [(f, bug, m, SWEEP_CAP) for bug in (False, True)]

    def run_series(s) -> None:
        f, bug, m, cap = s
        for n in SIZES + EXTRA.get(f, []):
            if n > 50 and m not in ("auto", "clifford-tableau"):
                continue
            k = (f, n, "bug" if bug else "correct", m)
            prev = next((r for r in results if key(r) == k), None)
            if prev is None:
                prev = spawn(f, n, bug, m, cap)
                results.append(prev)
                save()
                print(f"{time.strftime('%H:%M:%S')} {f:10s} n={n:<3d} {k[2]:7s} {m:17s} -> {prev['status']:20s} "
                      f"{prev.get('method', '')[:30]:30s} {prev['wall_seconds']:6.1f}s {prev['peak_rss_mb']:7.0f}MB",
                      flush=True)
            if prev["status"] in ("TIMEOUT", "ERROR"):
                break

    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(run_series, series))
    save()
    print("done", len(results), flush=True)


if __name__ == "__main__":
    main()
