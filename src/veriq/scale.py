"""Equivalence checking that scales past the dense-matrix limit (30-50+ qubits).

`decide_equivalence` runs a tiered pipeline and reports one of four honest statuses:

* PROVEN_EQUIVALENT   - a sound proof: Clifford tableau equality, a decision-diagram / ZX proof from mqt.qcec,
                        a dense Operator comparison, or (state mode only) an exact, untruncated MPS overlap.
* NOT_EQUIVALENT      - a proof of difference: a concrete input whose outputs differ (counterexample), a
                        Clifford tableau mismatch, or a QCEC `not_equivalent` result.
* PROBABLY_EQUIVALENT - falsification only: K simulated inputs found no difference. This is NOT a proof; a bug
                        that touches one input in 2^n is easily missed. Callers map it to INCONCLUSIVE.
* UNKNOWN             - nothing could be decided within the budget.

Tiers (each one is skipped when it does not apply):

1. width mismatch -> NOT_EQUIVALENT.
2. partition into independent blocks (connected components of the joint interaction graph). A tensor product
   equals another up to global phase iff every factor does, so blocks are decided separately.
3. Clifford tableau (qiskit.quantum_info.Clifford / StabilizerState): exact, polynomial, hundreds of qubits.
4. dense Operator for n <= 10.
5. mqt.qcec with configurable checkers (alternating DD, construction, simulation, ZX) under a HARD timeout
   (killable worker process: QCEC's cooperative timeout does not stop some large checks).
6. falsification: exhaustive basis search for n <= 12, else random basis strings, |+...+> and random product
   states simulated with an untruncated matrix-product-state (Aer) in a killable worker.
"""

from __future__ import annotations

import json
import os
import pickle
import random
import subprocess
import sys
import time
from typing import Any

import numpy as np
from qiskit import QuantumCircuit

PROVEN = "PROVEN_EQUIVALENT"
NOT_EQ = "NOT_EQUIVALENT"
PROBABLY = "PROBABLY_EQUIVALENT"
UNKNOWN = "UNKNOWN"

OPERATOR_MAX_QUBITS = 10
EXHAUSTIVE_MAX_QUBITS = 12
INPROCESS_QCEC_MAX_QUBITS = 16  # below this QCEC is fast and its cooperative timeout is fine
QCEC_STRATEGIES = ("alternating", "construction", "simulation", "zx")
ALL_STRATEGIES = ("clifford", "operator", *QCEC_STRATEGIES, "falsify")
DEFAULT_STRATEGIES = ("clifford", "operator", "alternating", "zx", "simulation", "falsify")
FIDELITY_TOL = 1e-8


# --------------------------------------------------------------------------- small helpers

def _pack(*circs: QuantumCircuit) -> bytes:
    # pickle, not QPY: QPY rejects gates with more than 31 controls (e.g. a 50-qubit mcphase oracle).
    # The bytes only travel over a pipe to our own child process.
    return pickle.dumps(list(circs), protocol=pickle.HIGHEST_PROTOCOL)


def _unpack(data: bytes) -> list[QuantumCircuit]:
    return pickle.loads(data)  # noqa: S301 - produced by _pack in the parent process


def _has_layout(qc: QuantumCircuit) -> bool:
    return getattr(qc, "layout", None) is not None


def _strip_measure(qc: QuantumCircuit) -> QuantumCircuit:
    u = qc.remove_final_measurements(inplace=False)
    return u


def is_clifford(qc: QuantumCircuit) -> bool:
    from qiskit.quantum_info import Clifford

    try:
        Clifford(qc)
        return True
    except Exception:
        return False


def _restrict(qc: QuantumCircuit, qubits: list[int]) -> QuantumCircuit:
    idx = {q: i for i, q in enumerate(qubits)}
    out = QuantumCircuit(len(qubits), name=qc.name)
    for inst in qc.data:
        qs = [qc.find_bit(q).index for q in inst.qubits]
        if qs and qs[0] in idx:
            out.append(inst.operation, [idx[q] for q in qs])
    return out


def partition(a: QuantumCircuit, b: QuantumCircuit) -> list[list[int]]:
    """Connected components of the joint interaction graph (qubits linked by any multi-qubit gate)."""
    n = a.num_qubits
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for qc in (a, b):
        for inst in qc.data:
            if inst.operation.name == "barrier":
                continue
            qs = [qc.find_bit(q).index for q in inst.qubits]
            for q in qs[1:]:
                parent[find(q)] = find(qs[0])
    comps: dict[int, list[int]] = {}
    for q in range(n):
        comps.setdefault(find(q), []).append(q)
    return sorted(comps.values(), key=lambda c: c[0])


def _label(bits: int, n: int) -> str:
    return format(bits, f"0{n}b")


# --------------------------------------------------------------------------- tier: Clifford

def clifford_decide(a: QuantumCircuit, b: QuantumCircuit, mode: str = "unitary", seed: int = 7) -> dict[str, Any]:
    """Exact decision for two Clifford circuits (no layouts). Raises ValueError if either is not Clifford."""
    from qiskit.quantum_info import Clifford, StabilizerState

    t0 = time.perf_counter()
    ca, cb = Clifford(a), Clifford(b)  # raises if not Clifford
    n = a.num_qubits
    ev: dict[str, Any] = {"method": "clifford-tableau", "engine": "qiskit.quantum_info.Clifford (exact)"}
    if mode == "state":
        sa, sb = StabilizerState(ca), StabilizerState(cb)
        eq = sa.equiv(sb)
        ev["engine"] = "qiskit.quantum_info.StabilizerState.equiv (exact)"
        if not eq:
            fid = _stab_fidelity(ca.compose(cb.adjoint()), n)
            ev["counterexample"] = {"input_state": "|" + "0" * n + ">", "fidelity": fid}
    else:
        eq = ca == cb  # tableau equality: equal as unitaries up to global phase
        if not eq:
            cex = _clifford_counterexample(ca, cb, n, seed)
            if cex:
                ev["counterexample"] = cex
    ev["seconds"] = round(time.perf_counter() - t0, 4)
    return {"status": PROVEN if eq else NOT_EQ, "method": "clifford-tableau", "evidence": ev}


def _stab_fidelity(c, n: int) -> float:
    """|<0|C|0>|^2 for a Clifford C, exactly (it is 0 or 2^-k)."""
    from qiskit.quantum_info import StabilizerState

    return float(StabilizerState(c).probabilities_dict_from_bitstring("0" * n).get("0" * n, 0.0))


def _clifford_counterexample(ca, cb, n: int, seed: int) -> dict[str, Any] | None:
    from qiskit.quantum_info import Clifford

    rng = random.Random(seed)
    labels = ["0" * n, "+" * n]
    labels += ["".join(rng.choice("01") for _ in range(n)) for _ in range(16)]
    labels += ["".join(rng.choice("01+-rl") for _ in range(n)) for _ in range(32)]
    diff = ca.compose(cb.adjoint())  # apply A, then B^dagger
    for lab in labels:
        prep = QuantumCircuit(n)
        for q, ch in enumerate(reversed(lab)):
            if ch == "1":
                prep.x(q)
            elif ch == "+":
                prep.h(q)
            elif ch == "-":
                prep.x(q); prep.h(q)
            elif ch == "r":
                prep.h(q); prep.s(q)
            elif ch == "l":
                prep.h(q); prep.sdg(q)
        p = Clifford(prep)
        full = p.compose(diff).compose(p.adjoint())
        fid = _stab_fidelity(full, n)
        if fid < 1 - FIDELITY_TOL:
            return {"input_state": f"|{lab}>", "fidelity": round(fid, 6),
                    "note": "stabilizer input; outputs are distinct stabilizer states"}
    return None


# --------------------------------------------------------------------------- tier: dense operator

def operator_decide(a: QuantumCircuit, b: QuantumCircuit) -> dict[str, Any]:
    from qiskit.quantum_info import Operator

    oa = Operator.from_circuit(a) if _has_layout(a) else Operator(a)
    ob = Operator.from_circuit(b) if _has_layout(b) else Operator(b)
    if oa.dim != ob.dim:
        return {"status": UNKNOWN, "method": "operator",
                "evidence": {"engine": "qiskit.Operator", "note": f"dimension mismatch {oa.dim} vs {ob.dim}"}}
    eq = oa.equiv(ob)
    return {"status": PROVEN if eq else NOT_EQ, "method": "operator",
            "evidence": {"method": "operator", "engine": "qiskit.Operator (up to global phase)"}}


# --------------------------------------------------------------------------- tier: QCEC

def qcec_options(strategies: list[str] | tuple[str, ...]) -> dict[str, Any]:
    s = set(strategies)
    opts = {
        "run_alternating_checker": "alternating" in s,
        "run_construction_checker": "construction" in s,
        "run_simulation_checker": "simulation" in s,
        "run_zx_checker": "zx" in s,
    }
    if "simulation" in s:
        opts["max_sims"] = 16
    return opts


QCEC_SHARE = {"zx": 0.25, "alternating": 0.6, "construction": 0.6, "simulation": 0.5}


def _qcec_name(res_equivalence: str) -> str:
    if res_equivalence in ("equivalent", "equivalent_up_to_global_phase"):
        return PROVEN
    if res_equivalence == "not_equivalent":
        return NOT_EQ
    if res_equivalence == "probably_equivalent":
        return PROBABLY  # simulation checker only: random stimuli, not a proof
    return UNKNOWN  # probably_not_equivalent (ZX cannot prove a difference), no_information, timeout, error


def qcec_decide(a: QuantumCircuit, b: QuantumCircuit, strategies, timeout: float,
                hard: bool | None = None) -> dict[str, Any]:
    """Run mqt.qcec with the chosen checkers.

    Small circuits: one in-process call with all checkers. Large circuits: one checker at a time
    (ZX, alternating, construction, simulation), each in a killable worker with its share of the budget,
    because QCEC's cooperative timeout does not stop some large checks and one slow checker must not
    hide a fast proof from another.
    """
    strategies = [s for s in QCEC_STRATEGIES if s in strategies]
    order = [s for s in ("zx", "alternating", "construction", "simulation") if s in strategies]
    label = "qcec-" + "+".join(order)
    n = max(a.num_qubits, b.num_qubits)
    hard = n > INPROCESS_QCEC_MAX_QUBITS if hard is None else hard
    t0 = time.perf_counter()
    ev: dict[str, Any] = {"method": label, "engine": "mqt.qcec", "qcec_strategies": order,
                          "timeout_s": round(timeout, 2), "hard_timeout": hard}
    if not hard:
        from mqt import qcec

        try:
            res = qcec.verify(a, b, timeout=timeout, **qcec_options(order))
            name = res.equivalence.name
            ev["qcec_check_time_s"] = round(res.check_time, 4)
        except Exception as exc:
            name = "error"
            ev["qcec_error"] = repr(exc)[:300]
        ev["qcec_result"] = name
        ev["seconds"] = round(time.perf_counter() - t0, 4)
        return {"status": _qcec_name(name), "method": label, "evidence": ev}
    runs = []
    probable = None
    data = _pack(a, b)
    for i, strat in enumerate(order):
        left = timeout - (time.perf_counter() - t0)
        if left < 0.5:
            break
        share = left if i == len(order) - 1 else max(0.5, left * QCEC_SHARE[strat])
        name, secs, err = _qcec_worker_call(data, qcec_options([strat]), share)
        run = {"checker": strat, "result": name, "seconds": secs, "budget_s": round(share, 2)}
        if err:
            run["error"] = err[-300:]
        runs.append(run)
        st = _qcec_name(name)
        if st in (PROVEN, NOT_EQ):
            ev.update(qcec_result=name, qcec_runs=runs, seconds=round(time.perf_counter() - t0, 4))
            return {"status": st, "method": f"qcec-{strat}", "evidence": dict(ev, method=f"qcec-{strat}")}
        if st == PROBABLY:
            probable = strat
    ev.update(qcec_result=("probably_equivalent" if probable else (runs[-1]["result"] if runs else "timeout")),
              qcec_runs=runs, seconds=round(time.perf_counter() - t0, 4))
    if probable:
        return {"status": PROBABLY, "method": f"qcec-{probable}", "evidence": dict(ev, method=f"qcec-{probable}")}
    return {"status": UNKNOWN, "method": label, "evidence": ev}


def _qcec_worker_call(data: bytes, opts: dict[str, Any], deadline: float) -> tuple[str, float, str]:
    t0 = time.perf_counter()
    cmd = [sys.executable, "-c", "from veriq.scale import _qcec_worker_main; _qcec_worker_main()"]
    hdr = json.dumps(opts).encode() + b"\n"
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "PYTHONWARNINGS": "ignore"})
    try:
        out, errb = proc.communicate(hdr + data, timeout=deadline)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return "timeout", round(time.perf_counter() - t0, 3), ""
    secs = round(time.perf_counter() - t0, 3)
    lines = [x for x in out.decode(errors="replace").splitlines() if x.startswith("{")]
    if proc.returncode != 0 or not lines:
        return "error", secs, errb.decode(errors="replace")
    return json.loads(lines[-1])["equivalence"], secs, ""


def _qcec_worker_main() -> None:  # pragma: no cover - runs in a child process
    import warnings

    warnings.filterwarnings("ignore")
    from mqt import qcec

    opts = json.loads(sys.stdin.buffer.readline())
    a, b = _unpack(sys.stdin.buffer.read())
    res = qcec.verify(a, b, **opts)
    sys.stdout.write(json.dumps({"equivalence": res.equivalence.name, "check_time": res.check_time}) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- tier: falsification

def falsify(a: QuantumCircuit, b: QuantumCircuit, mode: str = "unitary", budget: float = 30.0,
            trials: int = 32, seed: int = 7) -> dict[str, Any]:
    """Search for an input where a and b differ. Never proves equivalence (except exact state overlap)."""
    n = a.num_qubits
    t0 = time.perf_counter()
    if _has_layout(a) or _has_layout(b):
        return {"status": UNKNOWN, "method": "falsify",
                "evidence": {"method": "falsify", "note": "compiled circuit with a layout: falsification skipped"}}
    if mode == "unitary" and n <= EXHAUSTIVE_MAX_QUBITS:
        from .checks import find_counterexample

        cex = find_counterexample(a, b)
        ev = {"method": "exhaustive-basis", "engine": "qiskit.Statevector",
              "inputs_tried": 2 ** n + 1, "seconds": round(time.perf_counter() - t0, 4)}
        if cex:
            ev["counterexample"] = cex
            return {"status": NOT_EQ, "method": "exhaustive-basis", "evidence": ev}
        ev["note"] = ("all 2^n basis inputs and |+...+> agree; equivalence is still not proven "
                      "(relative phases between basis inputs are only partly covered)")
        return {"status": PROBABLY, "method": "exhaustive-basis", "evidence": ev}
    payload = {"mode": mode, "trials": trials, "seed": seed}
    lines, killed, err = _run_mps_worker(_pack(a, b), payload, budget)
    tried = [json.loads(x) for x in lines if x.startswith("{")]
    ev = {"method": "mps-falsify" if mode == "unitary" else "mps-exact-overlap",
          "engine": "qiskit-aer matrix_product_state (untruncated)",
          "inputs_tried": len(tried), "budget_s": budget, "stopped_by_budget": killed,
          "seconds": round(time.perf_counter() - t0, 4)}
    if err:
        ev["worker_error"] = err[-400:]
    if tried:
        ev["min_fidelity"] = round(min(t["fidelity"] for t in tried), 10)
    bad = [t for t in tried if t["fidelity"] < 1 - FIDELITY_TOL]
    if bad:
        t = bad[0]
        ev["counterexample"] = {"input_state": t["input"], "fidelity": round(t["fidelity"], 6)}
        return {"status": NOT_EQ, "method": ev["method"], "evidence": ev}
    if mode == "state" and tried:
        ev["note"] = "exact (untruncated) MPS overlap from |0...0>; decided up to numerical tolerance 1e-8"
        return {"status": PROVEN, "method": ev["method"], "evidence": ev}
    if tried:
        ev["note"] = (f"{len(tried)} simulated inputs found no difference. This is falsification, NOT a proof: "
                      "a bug that affects few of the 2^n inputs can be missed.")
        return {"status": PROBABLY, "method": ev["method"], "evidence": ev}
    ev["note"] = "no simulation finished inside the budget"
    return {"status": UNKNOWN, "method": ev["method"], "evidence": ev}


def _run_mps_worker(data: bytes, payload: dict[str, Any], budget: float) -> tuple[list[str], bool, str]:
    """Stream one JSON line per trial from a killable worker; keep partial results on timeout."""
    cmd = [sys.executable, "-c", "from veriq.scale import _mps_worker_main; _mps_worker_main()"]
    hdr = json.dumps(payload).encode() + b"\n"
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "PYTHONWARNINGS": "ignore"})
    try:
        out, errb = proc.communicate(hdr + data, timeout=max(budget, 1.0))
        killed = False
    except subprocess.TimeoutExpired:
        proc.kill()
        out, errb = proc.communicate()
        killed = True
    err = errb.decode(errors="replace") if proc.returncode not in (0, None) and not killed else ""
    return out.decode(errors="replace").splitlines(), killed, err


def _lower(c: QuantumCircuit, sim) -> QuantumCircuit:
    """Prepare a circuit for Aer's MPS method once (lowering is the slow part, so it is not done per trial).

    Gates on 3+ qubits are decomposed first: Aer's MPS treats a wide gate (e.g. a 49-control mcphase) as one dense
    matrix. qubits_initially_zero=False so the synthesis never borrows a qubit as a clean ancilla.
    """
    from qiskit import transpile

    if any(inst.operation.num_qubits > 2 for inst in c.data):
        c = transpile(c, basis_gates=["u", "cx", "cp", "swap"], optimization_level=0, qubits_initially_zero=False)
    return transpile(c, sim, optimization_level=0)


def _mps_amp0(core: QuantumCircuit, prep: QuantumCircuit | None, sim) -> complex:
    from qiskit_aer.library import SaveAmplitudes

    n = core.num_qubits
    c = QuantumCircuit(n)
    if prep is not None:
        c.compose(prep, inplace=True)
    c.compose(core, inplace=True)
    if prep is not None:
        c.compose(prep.inverse(), inplace=True)
    c.append(SaveAmplitudes(n, [0]), c.qubits)
    res = sim.run(c, shots=1).result()
    return complex(res.data(0)["amplitudes"][0])


def _mps_worker_main() -> None:  # pragma: no cover - runs in a child process
    import warnings

    warnings.filterwarnings("ignore")
    from qiskit_aer import AerSimulator

    hdr = sys.stdin.buffer.readline()
    payload = json.loads(hdr)
    a, b = _unpack(sys.stdin.buffer.read())
    n = a.num_qubits
    sim = AerSimulator(method="matrix_product_state", matrix_product_state_truncation_threshold=1e-16)
    binv = b.inverse()
    rng = np.random.default_rng(payload["seed"])

    core = QuantumCircuit(n)
    core.compose(a, inplace=True)
    core.compose(binv, inplace=True)
    core = _lower(core, sim)

    def emit(label: str, prep: QuantumCircuit | None) -> None:
        amp = _mps_amp0(core, prep, sim)
        fid = float(abs(amp) ** 2)
        sys.stdout.write(json.dumps({"input": label, "fidelity": fid}) + "\n")
        sys.stdout.flush()
        if fid < 1 - FIDELITY_TOL:  # witness found: stop early
            sys.exit(0)

    if payload["mode"] == "state":
        emit("|" + "0" * n + ">", None)
        return
    trials = int(payload["trials"])
    k_basis = max(1, trials // 2)
    for t in range(k_basis):
        bits = 0 if t == 0 else int.from_bytes(rng.bytes((n + 7) // 8), "little") & ((1 << n) - 1)
        prep = QuantumCircuit(n)
        for q in range(n):
            if bits >> q & 1:
                prep.x(q)
        emit(f"|{_label(bits, n)}>", prep)
    prep = QuantumCircuit(n)
    prep.h(range(n))
    emit("|" + "+" * n + ">", prep)
    for t in range(trials - k_basis - 1):
        ang = rng.uniform(0, 2 * np.pi, size=(n, 3))
        prep = QuantumCircuit(n)
        for q in range(n):
            prep.u(*ang[q], q)
        emit(f"random product state #{t} (seed {payload['seed']}; u(theta,phi,lam) per qubit)", prep)


# --------------------------------------------------------------------------- the pipeline

def _combine(parts: list[dict[str, Any]]) -> str:
    st = [p["status"] for p in parts]
    if NOT_EQ in st:
        return NOT_EQ
    if all(s == PROVEN for s in st):
        return PROVEN
    if UNKNOWN in st:
        return UNKNOWN
    return PROBABLY


def decide_equivalence(a: QuantumCircuit, b: QuantumCircuit, mode: str = "unitary", timeout: float = 30.0,
                       strategies: list[str] | tuple[str, ...] | None = None, trials: int = 32,
                       seed: int = 7, use_partition: bool = True) -> dict[str, Any]:
    """Decide whether a and b are equivalent (mode='unitary') or prepare the same state from |0..0> (mode='state').

    Returns {"status", "method", "evidence", "seconds"}; evidence holds per-tier records and, for
    NOT_EQUIVALENT, a counterexample when one was found.
    """
    t0 = time.perf_counter()
    strategies = tuple(strategies or DEFAULT_STRATEGIES)
    unknown = set(strategies) - set(ALL_STRATEGIES)
    if unknown:
        raise ValueError(f"unknown strategies {sorted(unknown)}; choose from {list(ALL_STRATEGIES)}")
    a, b = _strip_measure(a), _strip_measure(b)
    layout = _has_layout(a) or _has_layout(b)
    if not layout and a.num_qubits != b.num_qubits:
        return _done(t0, {"status": NOT_EQ, "method": "width",
                          "evidence": {"method": "width", "note": f"{a.num_qubits} vs {b.num_qubits} qubits"}})
    if use_partition and not layout and a.num_qubits > 1:
        comps = partition(a, b)
        if len(comps) > 1:
            parts = []
            for comp in comps:
                deadline = max(1.0, timeout - (time.perf_counter() - t0))
                r = decide_equivalence(_restrict(a, comp), _restrict(b, comp), mode, deadline, strategies,
                                       trials, seed, use_partition=False)
                r["qubits"] = comp
                parts.append(r)
                if r["status"] == NOT_EQ:
                    break
            status = _combine(parts)
            methods = sorted({p["method"] for p in parts})
            ev = {"method": "partition", "blocks": len(comps), "block_sizes": [len(c) for c in comps],
                  "block_methods": methods,
                  "blocks_detail": [{"qubits": p["qubits"] if len(p["qubits"]) <= 8 else
                                     f"{len(p['qubits'])} qubits from {p['qubits'][0]}",
                                     "status": p["status"], "method": p["method"]} for p in parts[:12]]}
            bad = next((p for p in parts if p["status"] == NOT_EQ), None)
            if bad and bad["evidence"].get("counterexample"):
                ev["counterexample"] = dict(bad["evidence"]["counterexample"], on_qubits=bad["qubits"])
            return _done(t0, {"status": status, "method": "partition+" + "+".join(methods), "evidence": ev})
    return _done(t0, _decide_block(a, b, mode, timeout, strategies, trials, seed, layout, t0))


def _decide_block(a, b, mode, timeout, strategies, trials, seed, layout, t0) -> dict[str, Any]:
    n = max(a.num_qubits, b.num_qubits)
    tiers: list[dict[str, Any]] = []
    best_probable: dict[str, Any] | None = None
    proven_not: dict[str, Any] | None = None

    def left() -> float:
        return timeout - (time.perf_counter() - t0)

    def finish(r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["evidence"] = dict(r["evidence"], tiers=[{k: t[k] for k in ("method", "status")} for t in tiers])
        return r

    if "clifford" in strategies and not layout and is_clifford(a) and is_clifford(b):
        r = clifford_decide(a, b, mode, seed)
        tiers.append(r)
        return finish(r)
    if "operator" in strategies and n <= OPERATOR_MAX_QUBITS and mode == "unitary":
        try:
            r = operator_decide(a, b)
            tiers.append(r)
            if r["status"] != UNKNOWN:
                if r["status"] == NOT_EQ and "falsify" in strategies and not layout:
                    f = falsify(a, b, mode, max(1.0, left()), trials, seed)
                    if f["evidence"].get("counterexample"):
                        r["evidence"]["counterexample"] = f["evidence"]["counterexample"]
                return finish(r)
        except Exception as exc:
            tiers.append({"method": "operator", "status": UNKNOWN, "evidence": {"error": repr(exc)[:200]}})
    q = [s for s in strategies if s in QCEC_STRATEGIES]
    if q and (mode == "unitary" or a.num_qubits == b.num_qubits):
        # In state mode QCEC compares unitaries: "equivalent" proves the states equal; anything else is not used.
        frac = 0.6 if "falsify" in strategies else 1.0
        r = qcec_decide(a, b, q, max(0.5, left() * frac))
        tiers.append(r)
        if r["status"] == PROVEN:
            return finish(r)
        if r["status"] == NOT_EQ and mode == "unitary":
            proven_not = r
        elif r["status"] == PROBABLY and mode == "unitary":
            best_probable = r
    if "falsify" in strategies and left() > 0.5:
        f = falsify(a, b, mode, left(), trials, seed)
        tiers.append(f)
        if f["status"] == NOT_EQ:
            if proven_not:  # attach the concrete witness to the QCEC proof
                proven_not["evidence"]["counterexample"] = f["evidence"]["counterexample"]
                return finish(proven_not)
            return finish(f)
        if f["status"] == PROVEN:  # state mode exact overlap
            return finish(f)
        if f["status"] == PROBABLY and best_probable is None:
            best_probable = f
    if proven_not:
        proven_not["evidence"].setdefault("note", "QCEC proved a difference; no concrete counterexample "
                                                  "was found inside the budget")
        return finish(proven_not)
    if best_probable:
        return finish(best_probable)
    last = tiers[-1] if tiers else {"method": "none", "evidence": {}}
    return finish({"status": UNKNOWN, "method": last["method"], "evidence": dict(last["evidence"])})


def _done(t0: float, r: dict[str, Any]) -> dict[str, Any]:
    r["seconds"] = round(time.perf_counter() - t0, 4)
    return r
