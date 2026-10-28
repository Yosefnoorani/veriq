"""Stage-4 evidence: `veriq preflight` on the 28 hard-round LLM circuits, as written and after `veriq optimize`.

Usage:  .venv/bin/python benchmark/preflight/run_preflight.py [--backends fake_torino,fake_brisbane]
Inputs: benchmark/hard/raw/<assistant>.py (verbatim LLM output, read-only), benchmark/hard/references.py
Output: benchmark/preflight/results.json, results.md

For every circuit and backend: compile for the backend (several seeds / levels, noise-aware choice), prove the
compiled circuit equivalent to the input up to the layout/routing permutation, check it against the trusted
reference, estimate ESP / two-qubit gates / duration, and run a small noisy Aer simulation (TVD vs ideal).
The "optimized" version is the cheapest PROVEN-equivalent all-to-all compilation from `veriq optimize`
(stage 1), which is then preflighted the same way.

HONESTY: ESP, duration and TVD are ESTIMATES from frozen calibration snapshots shipped with
qiskit-ibm-runtime (fake backends), using a simple depolarizing + readout model. They are not hardware
measurements and say nothing about crosstalk, leakage, drift or today's calibration.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARD = ROOT / "benchmark" / "hard"
sys.path.insert(0, str(ROOT / "src"))

from veriq.loader import load_circuit  # noqa: E402
from veriq.optimize import optimize_circuit  # noqa: E402
from veriq.preflight import load_backend, preflight, to_json  # noqa: E402

ASSISTANTS = ["chatgpt", "claude", "gemini", "perplexity"]


def _refs():
    spec = importlib.util.spec_from_file_location("veriq_hard_references", HARD / "references.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(res: dict) -> dict:
    j = to_json(res)
    est = j.get("estimate") or {}
    ns = j.get("noisy_simulation") or {}
    ck = {c["name"]: c["status"] for c in j["checks"]}
    return {"gate": j["gate"], "verdict": j["verdict"], "esp": est.get("esp"), "esp_with_idle": est.get("esp_with_idle"),
            "two_qubit_gates": est.get("two_qubit_gates"), "depth": est.get("depth"),
            "duration_us": None if est.get("duration_s") is None else est["duration_s"] * 1e6,
            "proof": (j.get("proof") or {}).get("status"), "proof_method": (j.get("proof") or {}).get("method"),
            "vs_reference": ck.get("Input vs reference"), "tvd": ns.get("tvd"),
            "physical_qubits": (j.get("layout") or {}).get("physical_qubits"), "chosen": j.get("chosen"),
            "layout_esp_range": [(j.get("layout_selection") or {}).get("worst_esp"),
                                 (j.get("layout_selection") or {}).get("best_esp")],
            "failing_checks": [c["name"] for c in j["checks"] if c["status"] not in ("PASS", "SKIPPED")],
            "seconds": j.get("seconds")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-only", action="store_true", help="re-render results.md from results.json")
    ap.add_argument("--backends", default="fake_torino,fake_brisbane")
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--opt-budget", type=float, default=60.0)
    args = ap.parse_args()
    if args.render_only:
        (HERE / "results.md").write_text(render_md(json.loads((HERE / "results.json").read_text())))
        return
    R = _refs()
    backends = [load_backend(b) for b in args.backends.split(",")]
    rows = []
    t0 = time.perf_counter()
    for task, spec in R.TASKS.items():
        ref = getattr(R, spec["fn"])()
        for a in ASSISTANTS:
            rec = {"assistant": a, "task": task, "mode": spec["mode"], "qubits": spec["qubits"]}
            try:
                qc = load_circuit(HARD / "raw" / f"{a}.py", spec["fn"])
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"does not build: {type(exc).__name__}: {exc}"[:300]
                rows.append(rec)
                print(f"{a:10s} {task:12s} BUILD ERROR", flush=True)
                continue
            opt = optimize_circuit(qc, mode=spec["mode"], coupling=None, seeds=4, timeout=30,
                                   budget=args.opt_budget)
            oc = opt.get("best_circuit")
            rec["optimize"] = {"proven": oc is not None, "cx_before": (opt.get("baseline") or {}).get("cx"),
                               "cx_after": (opt.get("best") or {}).get("cx")}
            rec["backends"] = {}
            for be in backends:
                kw = dict(reference=ref, mode=spec["mode"], seeds=args.seeds, levels=(1, 3), noisy_sim=True,
                          shots=4000, timeout=60, keep_circuits=False)
                before = _row(preflight(qc, be, **kw))
                after = _row(preflight(oc, be, **kw)) if oc is not None else None
                rec["backends"][be.name] = {"as_written": before, "optimized": after}
                print(f"{a:10s} {task:12s} {be.name:14s} {before['gate']:6s} ESP {before['esp'] or 0:.3f} "
                      f"-> {after['esp'] if after else float('nan'):.3f}  2q {before['two_qubit_gates']} -> "
                      f"{after['two_qubit_gates'] if after else '-'}  proof {before['proof']}/"
                      f"{after['proof'] if after else '-'}", flush=True)
            rows.append(rec)
    out = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"),
           "backends": [b.info() for b in backends], "seeds": args.seeds, "levels": [1, 3],
           "disclaimer": "ESP / duration / TVD are estimates from frozen calibration snapshots (qiskit-ibm-runtime "
                         "fake backends) with a depolarizing + readout noise model; NOT hardware measurements.",
           "seconds": round(time.perf_counter() - t0, 1), "rows": rows}
    (HERE / "results.json").write_text(json.dumps(out, indent=1, default=str))
    (HERE / "results.md").write_text(render_md(out))
    print(f"done in {out['seconds']} s")


def _f(x, nd=3):
    return "–" if x is None else f"{x:.{nd}f}"


def render_md(out: dict) -> str:
    names = [b["name"] for b in out["backends"]]
    L = ["# Preflight evidence: 28 hard-round circuits on offline IBM fake backends", "",
         f"Generated {out['generated']} by `benchmark/preflight/run_preflight.py` in {out['seconds']} s.", "",
         "> **ESP is an estimate, not a hardware measurement.** ESP = product of (1 − gate error) over all compiled "
         "gates × (1 − readout error) of each measured qubit (all logical qubits are assumed measured when the circuit "
         "has no measurements), taken from frozen calibration snapshots shipped with qiskit-ibm-runtime. TVD comes "
         "from a noisy Aer simulation with a depolarizing + readout model built from the same snapshot (no idle "
         "decoherence, crosstalk, leakage or drift). Use the numbers to compare compilations, not to predict a "
         "real run.", "", "## Backends", ""]
    for b in out["backends"]:
        L.append(f"- **{b['name']}** ({b['num_qubits']} qubits): {b.get('source')}, calibration date "
                 f"{b.get('calibration_date', '?')}, data sha256 `{(b.get('data_sha256') or '')[:16]}…`")
    rows = out["rows"]
    L += ["", "## Summary", ""]
    for n in names:
        pairs = [(r["backends"][n]["as_written"], r["backends"][n]["optimized"]) for r in rows if "backends" in r]
        both = [(b, a) for b, a in pairs if a is not None and b["esp"] is not None and a["esp"] is not None]
        gates = {}
        for b, _ in pairs:
            gates[b["gate"]] = gates.get(b["gate"], 0) + 1
        gates_o = {}
        for _, a in pairs:
            if a:
                gates_o[a["gate"]] = gates_o.get(a["gate"], 0) + 1
        proofs = sum(1 for b, a in pairs for x in (b, a) if x and x["proof"] == "proven")
        nproof = sum(1 for b, a in pairs for x in (b, a) if x)
        better = sum(1 for b, a in both if a["esp"] > b["esp"] + 1e-12)
        same = sum(1 for b, a in both if abs(a["esp"] - b["esp"]) <= 1e-12)
        mb = sorted(b["esp"] for b, _ in both)
        ma = sorted(a["esp"] for _, a in both)
        c2b = sum(b["two_qubit_gates"] for b, _ in both)
        c2a = sum(a["two_qubit_gates"] for _, a in both)
        L += [f"**{n}**: compiled-circuit proofs PROVEN {proofs}/{nproof}; gate as written {gates}, optimized "
              f"{gates_o}; on {len(both)} circuits with an optimized version, ESP improved on {better}, unchanged on "
              f"{same}, worse on {len(both) - better - same}; median ESP {_f(mb[len(mb)//2] if mb else None)} → "
              f"{_f(ma[len(ma)//2] if ma else None)}; total two-qubit gates {c2b} → {c2a}.", ""]
        why = {}
        for b, a in pairs:
            for x in (b, a):
                for c in (x or {}).get("failing_checks") or []:
                    why[c] = why.get(c, 0) + 1
        if why:
            L += [f"  Non-go reasons (as written + optimized, a circuit can have several): "
                  + ", ".join(f"{k} ×{v}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])) + ".", ""]
    L += ["## Per circuit", "",
          "Gate: go / warn / no-go (no-go includes circuits that are NOT equivalent to the trusted reference). "
          "Proof = compiled vs input, layout-aware.", ""]
    hdr = "| Assistant | Task | vs ref |"
    sep = "|---|---|---|"
    for n in names:
        hdr += f" {n} gate | ESP written → opt | 2q written → opt | µs written → opt | TVD written → opt | proof |"
        sep += "---|---|---|---|---|---|"
    L += [hdr, sep]
    for r in rows:
        if "backends" not in r:
            L.append(f"| {r['assistant']} | {r['task']} | build error |" + " – |" * (6 * len(names)))
            continue
        first = r["backends"][names[0]]["as_written"]
        line = f"| {r['assistant']} | {r['task']} | {first['vs_reference']} |"
        for n in names:
            b, a = r["backends"][n]["as_written"], r["backends"][n]["optimized"]
            ga = f"{b['gate']} → {a['gate']}" if a else f"{b['gate']} → (no proven opt)"
            line += (f" {ga} | {_f(b['esp'])} → {_f(a and a['esp'])} | {b['two_qubit_gates']} → "
                     f"{a['two_qubit_gates'] if a else '–'} | {_f(b['duration_us'], 1)} → "
                     f"{_f(a and a['duration_us'], 1)} | {_f(b['tvd'])} → {_f(a and a['tvd'])} | "
                     f"{b['proof']}/{a['proof'] if a else '–'} |")
        L.append(line)
    L += ["", "## Limitations", "",
          "- Calibration snapshots are frozen files inside qiskit-ibm-runtime, months old; real devices drift daily.",
          "- ESP ignores idle decoherence (reported separately as `esp_with_idle` = ESP × Π exp(−idle/T2)), "
          "crosstalk, leakage, non-Markovian and coherent errors; it is usually optimistic for deep circuits.",
          "- 'Optimized' means fewer gates on the generic all-to-all basis; after routing to a backend that can "
          "translate into slightly *lower* ESP (more SWAPs or a worse layout), which is why some rows get worse.",
          "- The noisy simulation uses the same simplified model, so TVD and ESP are not independent evidence.",
          "- The 'optimized' circuit is optimized for an all-to-all device with the generic basis; the backend "
          "compile then routes it. A backend-aware optimizer could do better.",
          "- Proofs are full unitary equivalence (qubits_initially_zero=False) on the active physical qubits, "
          "with the layout and final routing permutation made explicit.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
