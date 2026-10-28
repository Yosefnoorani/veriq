"""Pre-submission hardware gate: `veriq preflight`.

Compile a circuit for a concrete backend, PROVE the compiled circuit equivalent to the input (up to the
initial layout and the routing permutation), check that every instruction is native and on a coupled pair,
and estimate quality from the backend's calibration snapshot:

* ESP (expected success probability) = prod(1 - gate error) * prod(1 - readout error). This is the usual
  first-order *estimate* (no crosstalk, leakage, coherent or correlated errors); it is NOT a hardware
  measurement.
* duration (ASAP schedule from calibrated gate durations) vs T1/T2 of the qubits used, plus an idle-dephasing
  factor prod_q exp(-idle_q / T2_q) (gate errors already include decoherence during gates).
* two-qubit gate count.
* optionally a noisy Aer simulation (depolarizing gate noise matched to the calibrated error rates + readout
  error) and its total-variation distance to the ideal output distribution, for small circuits.

Several transpiler seeds / optimisation levels are compiled; the candidate with the best ESP (ties: fewer
2q gates) is kept - this is noise-aware layout selection on top of Qiskit's own VF2 noise-aware layout.

Backends are loaded OFFLINE: `qiskit_ibm_runtime.fake_provider` snapshot calibrations (e.g. fake_torino) or a
JSON profile ("veriq.backend/1", see docs/preflight.md and src/veriq/profiles/).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qiskit import QuantumCircuit, transpile

from .checks import non_unitary_ops, unitary_part

PROFILE_SCHEMA = "veriq.backend/1"
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
SKIP_OPS = {"barrier", "delay"}
NOISY_SIM_MAX_QUBITS = 12
DEFAULTS = {"min_esp": 0.05, "warn_esp": 0.5, "max_cx": None, "max_duration": None, "warn_t2_fraction": 0.5,
            "max_tvd": None}


class PreflightError(Exception):
    """Input problem: unknown backend, invalid profile, circuit too wide."""


# ============================================================================ backends

@dataclass
class Backend:
    name: str
    target: Any
    num_qubits: int
    source: dict[str, Any]
    t1: list[float | None] = field(default_factory=list)
    t2: list[float | None] = field(default_factory=list)

    def info(self) -> dict[str, Any]:
        return {"name": self.name, "num_qubits": self.num_qubits, **self.source}


def _norm(s: str) -> str:
    s = s.lower().replace("-", "").replace("_", "")
    s = re.sub(r"^fake", "", s)
    return re.sub(r"v2$", "", s)


def fake_backend_names() -> list[str]:
    try:
        from qiskit_ibm_runtime import fake_provider as fp
    except ImportError:
        return []
    out = []
    for n in dir(fp):
        if n.startswith("Fake") and "Provider" not in n and n != "FakeFractionalBackend":
            out.append(n)
    return sorted(out)


def builtin_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.json"))


def load_backend(spec: str | dict | Path) -> Backend:
    """`spec`: a fake IBM backend name (fake_torino / FakeTorino / torino), a built-in profile name
    (see `builtin_profiles()`), a path to a JSON profile, or an already-parsed profile dict."""
    if isinstance(spec, dict):
        return profile_backend(spec, origin="inline profile")
    s = str(spec)
    p = Path(s)
    if s.endswith(".json") or p.is_file():
        if not p.is_file():
            raise PreflightError(f"backend profile not found: {s}")
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            raise PreflightError(f"backend profile {s} is not valid JSON: {exc}") from None
        return profile_backend(data, origin=str(p), raw=p.read_bytes())
    if (PROFILES_DIR / f"{s}.json").is_file():
        q = PROFILES_DIR / f"{s}.json"
        return profile_backend(json.loads(q.read_text()), origin=f"builtin:{s}", raw=q.read_bytes())
    return fake_backend(s)


def fake_backend(name: str) -> Backend:
    try:
        from qiskit_ibm_runtime import fake_provider as fp
    except ImportError:
        raise PreflightError("fake IBM backends need qiskit-ibm-runtime (pip install 'veriq[preflight]')") from None
    want = _norm(name)
    match = [n for n in fake_backend_names() if _norm(n) == want]
    if not match:
        raise PreflightError(f"unknown backend {name!r}: not a fake IBM backend "
                             f"({', '.join(fake_backend_names()[:12])}, ...), not a built-in profile "
                             f"({', '.join(builtin_profiles())}) and not a .json file")
    be = getattr(fp, match[0])()
    tg = be.target
    props_file = Path(be.dirname) / be.props_filename if getattr(be, "props_filename", None) else None
    cal_date = None
    sha = None
    if props_file and props_file.is_file():
        raw = props_file.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        try:
            cal_date = json.loads(raw).get("last_update_date")
        except Exception:  # noqa: BLE001
            cal_date = None
    try:
        from importlib.metadata import version
        rt = version("qiskit-ibm-runtime")
    except Exception:  # noqa: BLE001
        rt = "?"
    qp = tg.qubit_properties or [None] * tg.num_qubits
    source = {"kind": "ibm-fake-backend", "illustrative": False,
              "source": f"qiskit-ibm-runtime {rt} fake_provider snapshot ({be.props_filename})",
              "calibration_date": cal_date, "backend_version": getattr(be, "backend_version", None),
              "data_sha256": sha,
              "note": "a frozen snapshot of past IBM calibration data, not today's device"}
    return Backend(be.name, tg, tg.num_qubits, source,
                   t1=[getattr(p, "t1", None) for p in qp], t2=[getattr(p, "t2", None) for p in qp])


def _per_qubit(v: Any, n: int, what: str) -> list[float | None]:
    if v is None:
        return [None] * n
    if isinstance(v, (int, float)):
        return [float(v)] * n
    if isinstance(v, list) and len(v) == n:
        return [None if x is None else float(x) for x in v]
    raise PreflightError(f"profile: {what} must be a number or a list of {n} numbers")


def _edges(coupling: Any, n: int, directed: bool) -> list[tuple[int, int]]:
    if coupling in (None, "all", "full", "all-to-all"):
        return list(itertools.permutations(range(n), 2))
    if coupling in ("linear", "line"):
        base = [(i, i + 1) for i in range(n - 1)]
    elif isinstance(coupling, dict) and "grid" in coupling:
        r, c = coupling["grid"]
        if r * c != n:
            raise PreflightError("profile: grid rows*cols must equal num_qubits")
        base = [(i * c + j, i * c + j + 1) for i in range(r) for j in range(c - 1)]
        base += [(i * c + j, (i + 1) * c + j) for i in range(r - 1) for j in range(c)]
    elif isinstance(coupling, list):
        base = [(int(a), int(b)) for a, b in coupling]
    else:
        raise PreflightError("profile: coupling must be 'all', 'linear', {'grid': [r, c]} or an edge list")
    for a, b in base:
        if not (0 <= a < n and 0 <= b < n) or a == b:
            raise PreflightError(f"profile: bad coupling edge {(a, b)}")
    if directed:
        return sorted(set(base))
    return sorted(set(base) | {(b, a) for a, b in base})


def profile_backend(data: dict, origin: str = "profile", raw: bytes | None = None) -> Backend:
    """Build a qiskit Target from a "veriq.backend/1" JSON profile.

    {"schema": "veriq.backend/1", "name": ..., "illustrative": true, "source": "...", "num_qubits": 11,
     "coupling": "all" | "linear" | {"grid": [r, c]} | [[0, 1], ...], "directed": false,
     "gates": {"rz": {"error": 0, "duration": 0}, "rxx": {"error": 0.004, "duration": 6e-4,
               "overrides": {"0,1": {"error": 0.006}}}},
     "readout": {"error": 0.004 | [...], "duration": 3e-4}, "t1": 10.0 | [...], "t2": 1.0 | [...], "dt": null}
    Times are in seconds; errors are average gate infidelities (EPG), as in IBM calibration data.
    """
    from qiskit.circuit import Measure, Parameter
    from qiskit.circuit.library import get_standard_gate_name_mapping
    from qiskit.transpiler import InstructionProperties, QubitProperties, Target

    if not isinstance(data, dict):
        raise PreflightError("profile must be a JSON object")
    if data.get("schema") != PROFILE_SCHEMA:
        raise PreflightError(f"profile schema must be {PROFILE_SCHEMA!r} (got {data.get('schema')!r})")
    try:
        n = int(data["num_qubits"])
        gates = dict(data["gates"])
    except (KeyError, TypeError, ValueError):
        raise PreflightError("profile needs num_qubits and gates") from None
    if n < 1 or n > 1000:
        raise PreflightError("profile: num_qubits out of range")
    std = get_standard_gate_name_mapping()
    t1 = _per_qubit(data.get("t1"), n, "t1")
    t2 = _per_qubit(data.get("t2"), n, "t2")
    tg = Target(num_qubits=n, dt=data.get("dt"),
                qubit_properties=[QubitProperties(t1=a, t2=b) for a, b in zip(t1, t2)])
    edges = _edges(data.get("coupling", "all"), n, bool(data.get("directed", False)))
    for gname, spec in gates.items():
        if gname not in std:
            raise PreflightError(f"profile: unknown gate {gname!r} (use Qiskit standard gate names)")
        spec = spec or {}
        g = std[gname]
        if g.params:
            g = type(g)(*[Parameter(f"_{gname}_{i}") for i in range(len(g.params))])
        if g.num_qubits == 1:
            qargs = [(q,) for q in range(n)]
        elif g.num_qubits == 2:
            qargs = edges
        else:
            raise PreflightError(f"profile: gate {gname!r} acts on {g.num_qubits} qubits; only 1q/2q supported")
        ov = {}
        for k, v in (spec.get("overrides") or {}).items():
            ov[tuple(int(x) for x in re.split(r"[,\-\s]+", k.strip()) if x)] = v
        props = {}
        for qa in qargs:
            o = ov.get(qa) or (ov.get(qa[::-1]) if not data.get("directed") and len(qa) == 2 else None) or {}
            props[qa] = InstructionProperties(error=float(o.get("error", spec.get("error", 0.0)) or 0.0),
                                              duration=float(o.get("duration", spec.get("duration", 0.0)) or 0.0))
        tg.add_instruction(g, props)
    ro = data.get("readout") or {}
    rerr = _per_qubit(ro.get("error", 0.0), n, "readout.error")
    rdur = float(ro.get("duration", 0.0) or 0.0)
    tg.add_instruction(Measure(), {(q,): InstructionProperties(error=rerr[q] or 0.0, duration=rdur)
                                   for q in range(n)})
    illustrative = bool(data.get("illustrative", True))
    source = {"kind": "profile", "illustrative": illustrative, "profile": origin,
              "source": data.get("source") or ("illustrative values, not vendor data" if illustrative else None),
              "calibration_date": data.get("calibration_date"),
              "data_sha256": hashlib.sha256(raw or json.dumps(data, sort_keys=True).encode()).hexdigest()}
    if data.get("disclaimer"):
        source["note"] = data["disclaimer"]
    return Backend(str(data.get("name") or "profile"), tg, n, source, t1=t1, t2=t2)


# ============================================================================ layout-aware proof

def _qi(qc: QuantumCircuit, q) -> int:
    return qc.find_bit(q).index


def compact(tc: QuantumCircuit, num_virtual: int) -> dict[str, Any]:
    """Restrict a transpiled (physical, width = backend) circuit to the physical qubits it uses.

    Returns {"circuit", "physical" (sorted physical qubits), "initial" (local index of each virtual qubit
    at the start), "final" (local index where each virtual qubit's state ends), "perm" (full local routing
    permutation: state at local i ends at local perm[i])}.
    """
    L = tc.layout
    n_phys = tc.num_qubits
    if L is None:
        init = list(range(num_virtual))
        rp = list(range(n_phys))
    else:
        init = list(L.initial_index_layout(filter_ancillas=True))[:num_virtual]
        rp = L.routing_permutation()
    touched = {_qi(tc, q) for ins in tc.data for q in ins.qubits}
    moved = {i for i, p in enumerate(rp) if p != i}
    phys = sorted(set(init) | touched | moved | {rp[i] for i in moved})
    loc = {p: i for i, p in enumerate(phys)}
    k = len(phys)
    out = QuantumCircuit(k, global_phase=tc.global_phase)
    for creg in tc.cregs:
        out.add_register(creg)
    if not tc.cregs and tc.clbits:
        out.add_bits(tc.clbits)
    for ins in tc.data:
        out.append(ins.operation, [out.qubits[loc[_qi(tc, q)]] for q in ins.qubits],
                   [out.clbits[tc.find_bit(c).index] for c in ins.clbits])
    perm = [loc[rp[p]] for p in phys]
    initial = [loc[p] for p in init]
    final = [perm[i] for i in initial]
    return {"circuit": out, "physical": phys, "initial": initial, "final": final, "perm": perm}


def expected_circuit(qc: QuantumCircuit, k: int, initial: list[int], perm: list[int]) -> QuantumCircuit:
    """What the compacted compiled circuit must equal: the input on its initial positions, then the routing
    permutation (state at local i moves to local perm[i]) as explicit SWAPs. Width k (ancillas included)."""
    e = QuantumCircuit(k, global_phase=0)
    e.compose(qc, qubits=list(initial), inplace=True)
    # content[x] = original position whose state is at x now; want content[perm[i]] == i
    want = [0] * k
    for i, j in enumerate(perm):
        want[j] = i
    content = list(range(k))
    where = list(range(k))
    for x in range(k):
        if content[x] != want[x]:
            y = where[want[x]]
            e.swap(x, y)
            content[x], content[y] = content[y], content[x]
            where[content[x]], where[content[y]] = x, y
    return e


def prove_compiled(qc: QuantumCircuit, comp: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    """PROVE compiled == input (any input state, up to global phase, layout + routing permutation undone)."""
    from . import scale

    u = unitary_part(qc)
    bad = non_unitary_ops(u)
    if bad:
        return {"status": "undecided", "result": scale.UNKNOWN, "method": None, "seconds": 0.0,
                "note": f"non-unitary operations {bad} (mid-circuit measurement/reset): no unitary proof"}
    cu = unitary_part(comp["circuit"])
    bad = non_unitary_ops(cu)
    if bad:
        return {"status": "undecided", "result": scale.UNKNOWN, "method": None, "seconds": 0.0,
                "note": f"compiled circuit has non-unitary operations {bad}"}
    cu = _strip_clbits(cu)
    exp = expected_circuit(_strip_clbits(u), cu.num_qubits, comp["initial"], comp["perm"])
    r = scale.decide_equivalence(cu, exp, mode="unitary", timeout=timeout)
    status = {scale.PROVEN: "proven", scale.NOT_EQ: "refuted"}.get(r["status"], "undecided")
    out = {"status": status, "result": r["status"], "method": r.get("method"), "seconds": r.get("seconds")}
    cex = (r.get("evidence") or {}).get("counterexample")
    if cex:
        out["counterexample"] = cex
    return out


def _strip_clbits(qc: QuantumCircuit) -> QuantumCircuit:
    out = QuantumCircuit(qc.num_qubits, global_phase=qc.global_phase)
    for ins in qc.data:
        if ins.operation.name == "barrier":
            continue
        out.append(ins.operation, [_qi(qc, q) for q in ins.qubits])
    return out


# ============================================================================ quality estimates

def _props(tg, name: str, qargs: tuple[int, ...]):
    try:
        return tg[name].get(qargs)
    except KeyError:
        return None


def native_violations(tc: QuantumCircuit, tg) -> list[str]:
    bad = []
    for ins in tc.data:
        name = ins.operation.name
        if name in ("barrier",):
            continue
        qa = tuple(_qi(tc, q) for q in ins.qubits)
        if not tg.instruction_supported(name, qa):
            bad.append(f"{name}{list(qa)}")
    return bad


def estimate(tc: QuantumCircuit, backend: Backend, num_virtual: int, final_phys: list[int]) -> dict[str, Any]:
    """ESP, duration (ASAP), T1/T2 ratios, 2q count for a physical circuit."""
    tg = backend.target
    log_esp_gates = 0.0
    log_esp_ro = 0.0
    busy: dict[int, float] = {}
    ready: dict[int, float] = {}
    n2q = 0
    n1q = 0
    measured: list[int] = []
    for ins in tc.data:
        name = ins.operation.name
        qa = tuple(_qi(tc, q) for q in ins.qubits)
        if name == "barrier":
            t = max((ready.get(q, 0.0) for q in qa), default=0.0)
            for q in qa:
                ready[q] = t
            continue
        p = _props(tg, name, qa)
        err = (p.error if p is not None and p.error is not None else 0.0)
        dur = (p.duration if p is not None and p.duration is not None else 0.0)
        if name == "delay":
            dur = float(ins.operation.duration or 0) * (tg.dt or 1.0) if ins.operation.unit == "dt" else 0.0
            err = 0.0
        if name == "measure":
            measured.extend(qa)
            log_esp_ro += math.log(max(1e-300, 1.0 - err))
        elif name != "delay":
            log_esp_gates += math.log(max(1e-300, 1.0 - err))
            if len(qa) >= 2:
                n2q += 1
            else:
                n1q += 1
        start = max((ready.get(q, 0.0) for q in qa), default=0.0)
        for q in qa:
            ready[q] = start + dur
            busy[q] = busy.get(q, 0.0) + dur
    readout_assumed = False
    if not measured:  # a circuit without measurements is assumed to be read out on every logical qubit
        readout_assumed = True
        D0 = max(ready.values(), default=0.0)
        for q in final_phys[:num_virtual]:
            p = _props(tg, "measure", (q,))
            err = p.error if p is not None and p.error is not None else 0.0
            dur = p.duration if p is not None and p.duration is not None else 0.0
            log_esp_ro += math.log(max(1e-300, 1.0 - err))
            ready[q] = max(D0, ready.get(q, 0.0)) + dur
            busy[q] = busy.get(q, 0.0) + dur
            measured.append(q)
    D = max(ready.values(), default=0.0)
    active = sorted(busy) or sorted(set(final_phys))
    t1s = [backend.t1[q] for q in active if q < len(backend.t1) and backend.t1[q]]
    t2s = [backend.t2[q] for q in active if q < len(backend.t2) and backend.t2[q]]
    log_idle = 0.0
    for q in active:
        t2 = backend.t2[q] if q < len(backend.t2) else None
        if t2:
            log_idle -= max(0.0, D - busy.get(q, 0.0)) / t2
    esp_g = math.exp(log_esp_gates)
    esp_r = math.exp(log_esp_ro)
    esp = esp_g * esp_r
    return {
        "esp": esp, "esp_gates": esp_g, "esp_readout": esp_r, "idle_factor": math.exp(log_idle),
        "esp_with_idle": esp * math.exp(log_idle),
        "two_qubit_gates": n2q, "one_qubit_gates": n1q, "depth": tc.depth(lambda i: i.operation.name not in SKIP_OPS),
        "duration_s": D, "min_t1_s": min(t1s) if t1s else None, "min_t2_s": min(t2s) if t2s else None,
        "duration_over_t1": D / min(t1s) if t1s else None, "duration_over_t2": D / min(t2s) if t2s else None,
        "measured_qubits": len(measured), "readout_assumed": readout_assumed,
        "ops": {k: int(v) for k, v in tc.count_ops().items()},
    }


# ============================================================================ noisy simulation

def noisy_tvd(qc: QuantumCircuit, comp: dict[str, Any], backend: Backend, shots: int = 4000,
              seed: int = 11) -> dict[str, Any]:
    """Aer run of the compacted compiled circuit with a calibration-derived noise model, TVD vs ideal.

    Noise model: depolarizing error on every gate with lambda = EPG * d/(d-1) (so the average gate infidelity
    matches the calibration), plus symmetric readout error. No T1/T2 idle noise, crosstalk or leakage.
    Every logical qubit is measured (logical order), for both the ideal and the noisy distribution.
    """
    from qiskit.quantum_info import Statevector
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

    k = comp["circuit"].num_qubits
    if k > NOISY_SIM_MAX_QUBITS:
        return {"ran": False, "note": f"{k} active qubits > {NOISY_SIM_MAX_QUBITS}: noisy simulation skipped"}
    u = _strip_clbits(unitary_part(qc))
    if non_unitary_ops(u):
        return {"ran": False, "note": "mid-circuit measurement/reset: noisy TVD not computed"}
    cu = _strip_clbits(unitary_part(comp["circuit"]))
    nv = qc.num_qubits
    tg = backend.target
    phys = comp["physical"]
    nm = NoiseModel()
    seen: set[tuple] = set()
    for ins in cu.data:
        name = ins.operation.name
        qa = [_qi(cu, q) for q in ins.qubits]
        if (name, tuple(qa)) in seen:
            continue
        seen.add((name, tuple(qa)))
        p = _props(tg, name, tuple(phys[i] for i in qa))
        e = p.error if p is not None and p.error is not None else 0.0
        if e > 0:
            d = 2 ** len(qa)
            nm.add_quantum_error(depolarizing_error(min(1.0, e * d / (d - 1)), len(qa)), name, qa, warnings=False)
    for v in range(nv):
        q = comp["final"][v]
        p = _props(tg, "measure", (phys[q],))
        r = p.error if p is not None and p.error is not None else 0.0
        if r > 0:
            nm.add_readout_error(ReadoutError([[1 - r, r], [r, 1 - r]]), [q], warnings=False)
    meas = QuantumCircuit(k, nv)
    meas.compose(cu, inplace=True)
    meas.measure([comp["final"][v] for v in range(nv)], list(range(nv)))
    sim = AerSimulator(noise_model=nm, seed_simulator=seed)
    counts = sim.run(meas, shots=shots).result().get_counts()
    ideal = Statevector(u).probabilities_dict()
    keys = set(ideal) | set(counts)
    tvd = 0.5 * sum(abs(ideal.get(b, 0.0) - counts.get(b, 0) / shots) for b in keys)
    top = max(ideal, key=ideal.get)
    return {"ran": True, "tvd": tvd, "shots": shots, "seed": seed, "ideal_top": top,
            "ideal_top_p": ideal[top], "noisy_top_p": counts.get(top, 0) / shots,
            "noise_model": "depolarizing(EPG-matched) + readout; no idle T1/T2, crosstalk or leakage"}


# ============================================================================ the gate

def _check(name: str, status: str, summary: str, evidence: dict | None = None) -> dict[str, Any]:
    return {"name": name, "status": status, "summary": summary, "evidence": evidence or {}}


def preflight(qc: QuantumCircuit, backend: Backend | str | dict, *, reference: QuantumCircuit | None = None,
              mode: str = "unitary", seeds: int = 4, levels: tuple[int, ...] = (1, 3), min_esp: float | None = None,
              warn_esp: float | None = None, max_cx: int | None = None, max_duration: float | None = None,
              warn_t2_fraction: float | None = None, noisy_sim: bool = False, max_tvd: float | None = None,
              shots: int = 4000, timeout: float = 60.0, seed: int = 2026, keep_circuits: bool = True) -> dict[str, Any]:
    """Run the hardware gate. Returns a JSON-able dict (+ "compiled_circuit"/"compact" when keep_circuits)."""
    t0 = time.perf_counter()
    be = backend if isinstance(backend, Backend) else load_backend(backend)
    th = {"min_esp": DEFAULTS["min_esp"] if min_esp is None else float(min_esp),
          "warn_esp": DEFAULTS["warn_esp"] if warn_esp is None else float(warn_esp),
          "max_cx": max_cx, "max_duration_s": max_duration,
          "warn_t2_fraction": DEFAULTS["warn_t2_fraction"] if warn_t2_fraction is None else float(warn_t2_fraction),
          "max_tvd": max_tvd}
    th["warn_esp"] = max(th["warn_esp"], th["min_esp"])
    res: dict[str, Any] = {"backend": be.info(), "thresholds": th, "num_qubits": qc.num_qubits,
                           "qubits_initially_zero": False, "checks": [], "candidates": []}
    checks = res["checks"]
    if qc.num_qubits > be.num_qubits:
        checks.append(_check("Fits backend", "FAIL", f"{qc.num_qubits} qubits > {be.num_qubits} on {be.name}"))
        return _finish(res, t0)
    if reference is not None:
        from . import scale

        r = scale.decide_equivalence(_strip_clbits(unitary_part(qc)), _strip_clbits(unitary_part(reference)),
                                     mode=mode, timeout=timeout)
        st = {scale.PROVEN: "PASS", scale.NOT_EQ: "FAIL"}.get(r["status"], "INCONCLUSIVE")
        ev = {"result": r["status"], "method": r.get("method"), "mode": mode}
        if (r.get("evidence") or {}).get("counterexample"):
            ev["counterexample"] = r["evidence"]["counterexample"]
        checks.append(_check("Input vs reference", st, f"{r['status']} ({r.get('method')}, mode={mode})", ev))
    cands = []
    for lvl in levels:
        for i in range(max(1, seeds)):
            s = seed + i
            tc = transpile(qc, target=be.target, optimization_level=lvl, seed_transpiler=s,
                           qubits_initially_zero=False)
            comp = compact(tc, qc.num_qubits)
            est = estimate(tc, be, qc.num_qubits, [comp["physical"][j] for j in comp["final"]])
            cands.append({"config": f"opt{lvl} seed {s}", "level": lvl, "seed": s, "tc": tc, "comp": comp,
                          "est": est})
    cands.sort(key=lambda c: (-c["est"]["esp_with_idle"], c["est"]["two_qubit_gates"], c["est"]["duration_s"]))
    res["candidates"] = [{"config": c["config"], "esp": c["est"]["esp"], "esp_with_idle": c["est"]["esp_with_idle"],
                          "two_qubit_gates": c["est"]["two_qubit_gates"], "duration_s": c["est"]["duration_s"],
                          "physical_qubits": c["comp"]["physical"]} for c in cands]
    best = cands[0]
    est, comp, tc = best["est"], best["comp"], best["tc"]
    res["chosen"] = best["config"]
    res["layout"] = {"physical_qubits": comp["physical"],
                     "initial_physical": [comp["physical"][i] for i in comp["initial"]],
                     "final_physical": [comp["physical"][i] for i in comp["final"]],
                     "initial": comp["initial"], "final": comp["final"], "perm": comp["perm"]}
    res["estimate"] = est
    worst = cands[-1]["est"]
    res["layout_selection"] = {"candidates": len(cands), "best_esp": est["esp_with_idle"],
                               "worst_esp": worst["esp_with_idle"],
                               "median_esp": sorted(c["est"]["esp_with_idle"] for c in cands)[len(cands) // 2]}
    # 1. proof
    pr = prove_compiled(qc, comp, timeout=timeout)
    res["proof"] = pr
    st = {"proven": "PASS", "refuted": "FAIL"}.get(pr["status"], "INCONCLUSIVE")
    checks.append(_check("Compiled circuit proven equivalent", st,
                         f"compiled ({best['config']}) vs input up to layout+routing permutation: "
                         f"{pr['result']} ({pr.get('method')})" + (f"; {pr['note']}" if pr.get("note") else ""), pr))
    # 2. native gates + coupling
    bad = native_violations(tc, be.target)
    checks.append(_check("Native gates and coupling", "FAIL" if bad else "PASS",
                         f"{len(bad)} unsupported instruction(s): {', '.join(bad[:6])}" if bad else
                         f"every instruction is native on a coupled qubit set of {be.name}",
                         {"violations": bad[:50]}))
    # 3. ESP
    esp = est["esp"]
    st = "FAIL" if esp < th["min_esp"] else ("INCONCLUSIVE" if esp < th["warn_esp"] else "PASS")
    checks.append(_check("Estimated success probability", st,
                         f"ESP {esp:.4g} (gates {est['esp_gates']:.4g} x readout {est['esp_readout']:.4g}; "
                         f"with idle dephasing {est['esp_with_idle']:.4g}); no-go < {th['min_esp']}, "
                         f"warn < {th['warn_esp']} - an estimate, not a hardware measurement",
                         {k: est[k] for k in ("esp", "esp_gates", "esp_readout", "idle_factor", "esp_with_idle")}))
    # 4. 2q count
    n2 = est["two_qubit_gates"]
    if max_cx is not None:
        checks.append(_check("Two-qubit gate count", "FAIL" if n2 > max_cx else "PASS",
                             f"{n2} two-qubit gates (max {max_cx})", {"two_qubit_gates": n2}))
    # 5. duration
    D = est["duration_s"]
    t2 = est["min_t2_s"]
    st, why = "PASS", []
    if max_duration is not None and D > max_duration:
        st = "FAIL"
        why.append(f"> max {max_duration:.3g}s")
    if t2 and D > th["warn_t2_fraction"] * t2 and st != "FAIL":
        st = "INCONCLUSIVE"
        why.append(f"> {th['warn_t2_fraction']} x min T2 ({t2:.3g}s)")
    checks.append(_check("Duration vs coherence", st,
                         f"duration {D:.4g}s (ASAP estimate)" +
                         (f"; D/T1 {est['duration_over_t1']:.3g}, D/T2 {est['duration_over_t2']:.3g}"
                          if est["duration_over_t2"] is not None else "; no T1/T2 data") +
                         (f"; {'; '.join(why)}" if why else ""),
                         {k: est[k] for k in ("duration_s", "min_t1_s", "min_t2_s", "duration_over_t1",
                                              "duration_over_t2")}))
    # 6. noisy sim
    if noisy_sim:
        ns = noisy_tvd(qc, comp, be, shots=shots)
        res["noisy_simulation"] = ns
        if not ns.get("ran"):
            checks.append(_check("Noisy simulation", "SKIPPED", ns["note"], ns))
        else:
            st = "FAIL" if (max_tvd is not None and ns["tvd"] > max_tvd) else "PASS"
            checks.append(_check("Noisy simulation", st,
                                 f"TVD(noisy, ideal) = {ns['tvd']:.3f} over {shots} shots"
                                 + (f" (max {max_tvd})" if max_tvd is not None else " (informational)"), ns))
    if keep_circuits:
        res["compiled_circuit"] = tc
        res["compact"] = comp
    return _finish(res, t0)


def _finish(res: dict[str, Any], t0: float) -> dict[str, Any]:
    st = {c["status"] for c in res["checks"] if c["status"] != "SKIPPED"}
    verdict = "FAIL" if "FAIL" in st else ("INCONCLUSIVE" if "INCONCLUSIVE" in st else "PASS")
    res["verdict"] = verdict
    res["gate"] = {"PASS": "go", "INCONCLUSIVE": "warn", "FAIL": "no-go"}[verdict]
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res


def to_json(res: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in res.items() if k not in ("compiled_circuit", "compact")}


def render_text(res: dict[str, Any]) -> str:
    b = res["backend"]
    lines = [f"veriq preflight  ->  {res['gate'].upper()}  ({res['verdict']})",
             f"backend: {b['name']} ({b['num_qubits']} qubits) - {b.get('source')}"
             + (f", calibration {b['calibration_date']}" if b.get("calibration_date") else "")]
    if b.get("illustrative"):
        lines.append("  NOTE: illustrative profile, not vendor data")
    if res.get("chosen"):
        e = res["estimate"]
        ls = res["layout_selection"]
        lines.append(f"chosen: {res['chosen']} of {ls['candidates']} compiles (ESP x idle best {ls['best_esp']:.4g}, "
                     f"median {ls['median_esp']:.4g}, worst {ls['worst_esp']:.4g}); physical qubits "
                     f"{res['layout']['initial_physical']}")
        lines.append(f"ESP {e['esp']:.4g} (estimate)  2q {e['two_qubit_gates']}  1q {e['one_qubit_gates']}  "
                     f"depth {e['depth']}  duration {e['duration_s'] * 1e6:.3g} us")
    for c in res["checks"]:
        lines.append(f"  [{c['status']:<12}] {c['name']}: {c['summary']}")
    return "\n".join(lines)
