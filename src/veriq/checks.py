"""The four Veriq week-1 checks.

Every check returns a CheckResult with PASS / FAIL / INCONCLUSIVE (or SKIPPED when it
does not apply) plus machine-readable evidence.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Operator, Statevector
from scipy import stats

from .models import CheckResult, Status

GENERIC_BASIS = ["rz", "sx", "x", "cx"]
OPERATOR_FALLBACK_MAX_QUBITS = 10
COUNTEREXAMPLE_MAX_QUBITS = 12
NON_UNITARY = {"measure", "reset", "barrier", "delay", "initialize"}


# --------------------------------------------------------------------------- helpers


def unitary_part(qc: QuantumCircuit) -> QuantumCircuit:
    """Strip final measurements/barriers; the rest must be unitary for equivalence checks."""
    u = qc.remove_final_measurements(inplace=False)
    return u


def non_unitary_ops(qc: QuantumCircuit) -> list[str]:
    bad = []
    for inst in qc.data:
        op = inst.operation
        if op.name in ("barrier",):
            continue
        if op.name in NON_UNITARY or getattr(op, "condition", None) is not None or op.name in (
            "if_else",
            "while_loop",
            "for_loop",
            "switch_case",
        ):
            bad.append(op.name)
    return sorted(set(bad))


def _qcec_verify(a: QuantumCircuit, b: QuantumCircuit, timeout: float) -> tuple[str, dict[str, Any]]:
    """Return (verdict, evidence) where verdict in {'equivalent','not_equivalent','unknown'}."""
    from mqt import qcec

    res = qcec.verify(a, b, timeout=timeout)
    name = res.equivalence.name
    ev = {"engine": "mqt.qcec", "qcec_result": name, "qcec_check_time_s": round(res.check_time, 4)}
    if name in ("equivalent", "equivalent_up_to_global_phase"):
        return "equivalent", ev
    if name == "not_equivalent":
        return "not_equivalent", ev
    return "unknown", ev  # probably_equivalent / probably_not_equivalent / no_information / timeout


def _operator_verify(a: QuantumCircuit, b: QuantumCircuit) -> tuple[str, dict[str, Any]]:
    oa = Operator.from_circuit(a) if a.layout is not None else Operator(a)
    ob = Operator.from_circuit(b) if b.layout is not None else Operator(b)
    if oa.dim != ob.dim:
        return "unknown", {"engine": "qiskit.Operator", "note": f"dimension mismatch {oa.dim} vs {ob.dim}"}
    eq = oa.equiv(ob)
    return ("equivalent" if eq else "not_equivalent"), {"engine": "qiskit.Operator (up to global phase)"}


def prove_equivalence(a: QuantumCircuit, b: QuantumCircuit, timeout: float = 30.0) -> tuple[str, dict[str, Any]]:
    """QCEC first; fall back to dense Operator comparison for small circuits."""
    evidence: dict[str, Any] = {}
    try:
        verdict, evidence = _qcec_verify(a, b, timeout)
        if verdict != "unknown":
            return verdict, evidence
    except Exception as exc:  # QCEC may not support some instruction
        evidence = {"qcec_error": repr(exc)[:300]}
    if max(a.num_qubits, b.num_qubits) <= OPERATOR_FALLBACK_MAX_QUBITS:
        v, ev = _operator_verify(a, b)
        evidence.update(ev)
        evidence["fallback"] = True
        return v, evidence
    return "unknown", evidence


def equivalence_status(a: QuantumCircuit, b: QuantumCircuit, timeout: float = 30.0) -> dict[str, Any]:
    """Honest four-way status: PROVEN_EQUIVALENT | NOT_EQUIVALENT | PROBABLY_EQUIVALENT | UNKNOWN.

    PROBABLY_EQUIVALENT means only that simulations found no difference; it is never reported as a proof.
    """
    verdict, ev = prove_equivalence(a, b, timeout)
    method = ev.get("method") or ev.get("engine")
    if verdict == "equivalent":
        return {"status": "PROVEN_EQUIVALENT", "method": method, "evidence": ev}
    if verdict == "not_equivalent":
        return {"status": "NOT_EQUIVALENT", "method": method, "evidence": ev}
    if ev.get("qcec_result") == "probably_equivalent" or ev.get("probably_equivalent"):
        return {"status": "PROBABLY_EQUIVALENT", "method": method, "evidence": ev}
    return {"status": "UNKNOWN", "method": method, "evidence": ev}


def zero_input_equal(a: QuantumCircuit, b: QuantumCircuit, max_qubits: int = 20) -> bool | None:
    """Do a and b prepare the same state from |0...0> (up to global phase)? None if too large."""
    if a.num_qubits > max_qubits:
        return None
    try:
        sa = Statevector(a).data
        if b.layout is not None:  # compiled circuit: undo the layout permutation exactly
            if b.num_qubits > OPERATOR_FALLBACK_MAX_QUBITS + 2:
                return None
            sb = Operator.from_circuit(b).data[:, 0]
        else:
            sb = Statevector(b).data
        return bool(abs(np.vdot(sa, sb)) ** 2 > 1 - 1e-8)
    except Exception:
        return None


def is_clifford(qc: QuantumCircuit) -> bool:
    try:
        from qiskit.quantum_info import Clifford

        Clifford(unitary_part(qc))
        return True
    except Exception:
        return False


def _top(probs: dict[str, float], k: int = 4) -> dict[str, float]:
    items = sorted(((s, p) for s, p in probs.items() if p > 1e-9), key=lambda t: -t[1])[:k]
    return {s: round(p, 6) for s, p in items}


def find_counterexample(cand: QuantumCircuit, ref: QuantumCircuit) -> dict[str, Any] | None:
    """Search computational-basis inputs (then |+>^n) for an input where the output states differ."""
    n = cand.num_qubits
    if n > COUNTEREXAMPLE_MAX_QUBITS:
        return None
    labels = [format(i, f"0{n}b") for i in range(2**n)]
    for label in labels:
        sa = Statevector.from_label(label).evolve(cand)
        sb = Statevector.from_label(label).evolve(ref)
        fid = float(abs(np.vdot(sa.data, sb.data)) ** 2)
        if fid < 1 - 1e-8:
            return {
                "input_state": f"|{label}>",
                "fidelity": round(fid, 6),
                "candidate_output_top": _top(sa.probabilities_dict()),
                "reference_output_top": _top(sb.probabilities_dict()),
            }
    # Every basis input maps to the same state up to a phase -> relative phases differ.
    label = "+" * n
    sa = Statevector.from_label(label).evolve(cand)
    sb = Statevector.from_label(label).evolve(ref)
    fid = float(abs(np.vdot(sa.data, sb.data)) ** 2)
    if fid < 1 - 1e-8:
        return {
            "input_state": f"|{label}>",
            "fidelity": round(fid, 6),
            "note": "basis inputs agree up to phase; the circuits differ in relative phases",
            "candidate_output_top": _top(sa.probabilities_dict()),
            "reference_output_top": _top(sb.probabilities_dict()),
        }
    return None


def circuit_metrics(qc: QuantumCircuit) -> dict[str, Any]:
    ops = {k: int(v) for k, v in qc.count_ops().items()}
    two_q = sum(1 for inst in qc.data if inst.operation.num_qubits == 2 and inst.operation.name != "barrier")
    multi_q = sum(1 for inst in qc.data if inst.operation.num_qubits > 2 and inst.operation.name != "barrier")
    return {
        "qubits": qc.num_qubits,
        "clbits": qc.num_clbits,
        "depth": qc.depth(),
        "size": qc.size(),
        "two_qubit_gates": two_q,
        "multi_qubit_gates": multi_q,
        "gate_counts": dict(sorted(ops.items())),
    }


# --------------------------------------------------------------------------- 1. transpile integrity


def make_targets(qc: QuantumCircuit, backend: str | None, seed: int) -> list[tuple[str, dict[str, Any]]]:
    n = max(qc.num_qubits, 1)
    targets: list[tuple[str, dict[str, Any]]] = []
    coupling = [[i, i + 1] for i in range(n - 1)] + [[i + 1, i] for i in range(n - 1)]
    targets.append(
        (
            f"generic basis {GENERIC_BASIS} + linear coupling ({n}q), opt=3",
            dict(basis_gates=GENERIC_BASIS, coupling_map=coupling or None, optimization_level=3, seed_transpiler=seed),
        )
    )
    if backend:
        from qiskit.providers.fake_provider import GenericBackendV2

        size = max(n, 5) if backend == "generic" else int(backend.split(":", 1)[1])
        be = GenericBackendV2(num_qubits=size, seed=seed)
        targets.append(
            (f"GenericBackendV2 ({size}q, seed={seed}), opt=3", dict(backend=be, optimization_level=3, seed_transpiler=seed))
        )
    return targets


def transpile_integrity(qc: QuantumCircuit, backend: str | None = None, seed: int = 1234,
                        timeout: float = 30.0, mode: str = "unitary"
                        ) -> tuple[CheckResult, list[tuple[str, QuantumCircuit]]]:
    """Compile the circuit and prove the result equivalent to the source.

    mode="unitary": the circuit is a block (oracle, adder, ...) that must be correct for EVERY input, so it is
    compiled with qubits_initially_zero=False. Qiskit's default (True) lets the synthesis borrow qubits that
    are still untouched as *clean* ancillas, which is only valid when the block runs first, on |0...0>.
    Veriq also compiles once with the default and records `zero_init_hazard` when that output is not a valid
    standalone block (informational: the source is fine, but `transpile(block).to_gate()` would be wrong).
    mode="state": only the state prepared from |0...0> matters, so the default is kept.
    """
    t0 = time.perf_counter()
    name = "Transpile integrity"
    u = unitary_part(qc)
    nu = non_unitary_ops(u)
    compiled: list[tuple[str, QuantumCircuit]] = []
    runs = []
    statuses = []
    zero_init = mode != "unitary"
    for label, kwargs in make_targets(u, backend, seed):
        kwargs = dict(kwargs, qubits_initially_zero=zero_init)
        label = label + ("" if zero_init else ", qubits_initially_zero=False")
        try:
            tq = transpile(u, **kwargs)
        except Exception as exc:
            runs.append({"target": label, "result": "transpile error", "error": repr(exc)[:300]})
            statuses.append("unknown")
            continue
        compiled.append((label, tq))
        if nu:
            runs.append({"target": label, "result": "not checked", "note": f"non-unitary ops {nu}"})
            statuses.append("unknown")
            continue
        verdict, ev = prove_equivalence(u, tq, timeout)
        runs.append({"target": label, "result": verdict, **ev})
        statuses.append(verdict)
    hazard = None
    if not zero_init and not nu and compiled:
        label0, kwargs0 = make_targets(u, backend, seed)[0]
        try:
            tq0 = transpile(u, **kwargs0)
            v0, ev0 = prove_equivalence(u, tq0, timeout)
            hazard = v0 == "not_equivalent"
            runs.append({"target": label0 + " [qiskit default qubits_initially_zero=True, informational]",
                         "result": v0, **ev0})
        except Exception as exc:  # informational only
            runs.append({"target": "default-transpile probe", "result": "error", "error": repr(exc)[:200]})
    if "not_equivalent" in statuses:
        status, summary = Status.FAIL, "Compiled circuit is NOT equivalent to the source circuit."
    elif statuses and all(s == "equivalent" for s in statuses):
        status, summary = Status.PASS, f"Proved equivalent after transpilation on {len(statuses)} target(s)."
    else:
        status, summary = Status.INCONCLUSIVE, "Could not prove equivalence after transpilation."
    if hazard:
        summary += (" Note: Qiskit's default transpile (qubits_initially_zero=True) borrows untouched qubits as"
                    " clean ancillas, so its output is only valid on |0...0> input, not as a standalone block.")
    res = CheckResult(name, status, summary, {"targets": runs, "mode": mode, "zero_init_hazard": hazard})
    res.seconds = round(time.perf_counter() - t0, 4)
    return res, compiled


# --------------------------------------------------------------------------- 2. reference equivalence


def reference_equivalence(cand: QuantumCircuit, ref: QuantumCircuit | None, timeout: float = 30.0) -> CheckResult:
    t0 = time.perf_counter()
    name = "Reference equivalence"
    if ref is None:
        return CheckResult(name, Status.SKIPPED, "No --reference given.")
    a, b = unitary_part(cand), unitary_part(ref)
    ev: dict[str, Any] = {}
    if a.num_qubits != b.num_qubits:
        res = CheckResult(name, Status.FAIL,
                          f"Qubit count differs: candidate {a.num_qubits} vs reference {b.num_qubits}.",
                          {"candidate_qubits": a.num_qubits, "reference_qubits": b.num_qubits})
    elif non_unitary_ops(a) or non_unitary_ops(b):
        res = CheckResult(name, Status.INCONCLUSIVE, "Circuits contain mid-circuit non-unitary operations.",
                          {"candidate_non_unitary": non_unitary_ops(a), "reference_non_unitary": non_unitary_ops(b)})
    else:
        verdict, ev = prove_equivalence(a, b, timeout)
        if verdict == "equivalent":
            res = CheckResult(name, Status.PASS, "Candidate is formally equivalent to the reference.", ev)
        elif verdict == "not_equivalent":
            cex = find_counterexample(a, b)
            if cex:
                ev["counterexample"] = cex
                summary = (f"NOT equivalent. Counterexample: on input {cex['input_state']} the outputs "
                           f"overlap only {cex['fidelity']:.4f}.")
            else:
                summary = "NOT equivalent (no small counterexample searched/found)."
            res = CheckResult(name, Status.FAIL, summary, ev)
        else:
            res = CheckResult(name, Status.INCONCLUSIVE, "Equivalence could not be decided.", ev)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res


def state_equivalence(cand: QuantumCircuit, ref: QuantumCircuit | None, tol: float = 1e-8) -> CheckResult:
    """State-preparation mode: compare the states both circuits prepare from |0...0>, up to global phase.

    Use this when the spec is about the prepared state (GHZ, W, Grover output) rather than the full unitary:
    two different but valid preparation circuits generally have different unitaries.
    """
    t0 = time.perf_counter()
    name = "State equivalence (from |0...0>)"
    if ref is None:
        return CheckResult(name, Status.SKIPPED, "No --reference given.")
    a, b = unitary_part(cand), unitary_part(ref)
    if a.num_qubits != b.num_qubits:
        return CheckResult(name, Status.FAIL,
                           f"Qubit count differs: candidate {a.num_qubits} vs reference {b.num_qubits}.",
                           {"candidate_qubits": a.num_qubits, "reference_qubits": b.num_qubits})
    if non_unitary_ops(a) or non_unitary_ops(b):
        return CheckResult(name, Status.INCONCLUSIVE, "Circuits contain mid-circuit non-unitary operations.",
                           {"candidate_non_unitary": non_unitary_ops(a), "reference_non_unitary": non_unitary_ops(b)})
    if a.num_qubits > 20:
        return CheckResult(name, Status.INCONCLUSIVE, "Too many qubits for exact statevector comparison.")
    sa, sb = Statevector(a), Statevector(b)
    fid = float(abs(np.vdot(sa.data, sb.data)) ** 2)
    ev = {"engine": "qiskit.Statevector (exact)", "fidelity": round(fid, 10), "tolerance": tol,
          "candidate_state_top": _top(sa.probabilities_dict(), 8),
          "reference_state_top": _top(sb.probabilities_dict(), 8)}
    if fid >= 1 - tol:
        res = CheckResult(name, Status.PASS, f"Prepares the reference state up to global phase (fidelity {fid:.6f}).", ev)
    else:
        res = CheckResult(name, Status.FAIL, f"Prepared state differs from the reference: fidelity {fid:.6f}.", ev)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res


def gate_set_check(qc: QuantumCircuit, allowed: list[str] | None) -> CheckResult:
    """FAIL if the circuit uses any instruction outside the allowed gate list (as written, not decomposed)."""
    t0 = time.perf_counter()
    name = "Gate-set constraint"
    if not allowed:
        return CheckResult(name, Status.SKIPPED, "No --allowed-gates given.")
    allow = set(allowed) | {"barrier"}
    used = {k: int(v) for k, v in unitary_part(qc).count_ops().items()}
    bad = {k: v for k, v in sorted(used.items()) if k not in allow}
    ev = {"allowed": sorted(set(allowed)), "used": dict(sorted(used.items())), "violations": bad}
    if bad:
        res = CheckResult(name, Status.FAIL,
                          "Uses gates outside the allowed set: " + ", ".join(f"{k} x{v}" for k, v in bad.items()) + ".", ev)
    else:
        res = CheckResult(name, Status.PASS, "All gates are inside the allowed set.", ev)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res


# --------------------------------------------------------------------------- 3. statistical test


def ideal_distribution(qc: QuantumCircuit) -> dict[str, float]:
    sv = Statevector(unitary_part(qc))
    return {k: float(v) for k, v in sv.probabilities_dict().items() if v > 1e-12}


def sample(qc: QuantumCircuit, shots: int, seed: int) -> dict[str, int]:
    from qiskit_aer import AerSimulator

    m = unitary_part(qc)
    m.measure_all()
    sim = AerSimulator()
    counts = sim.run(transpile(m, sim), shots=shots, seed_simulator=seed).result().get_counts()
    # measure_all may add a space-separated register if other cregs remain
    out: dict[str, int] = {}
    for k, v in counts.items():
        key = k.split(" ")[0]
        out[key] = out.get(key, 0) + v
    return out


def statistical_test(cand: QuantumCircuit, expect: dict[str, Any] | None, ref: QuantumCircuit | None,
                     shots: int = 4096, seed: int = 7, tvd_threshold: float = 0.05,
                     alpha: float = 0.001) -> CheckResult:
    t0 = time.perf_counter()
    name = "Statistical test (Aer)"
    expect = dict(expect or {})
    shots = int(expect.pop("shots", shots))
    tvd_threshold = float(expect.pop("tvd_threshold", tvd_threshold))
    support = expect.pop("support", None)
    dist = expect.pop("distribution", None)
    if dist is None and expect and all(isinstance(v, (int, float)) for v in expect.values()):
        dist = expect  # bare {"bitstring": prob} mapping
    source = "--expect"
    if dist is None and support is None:
        if ref is None:
            return CheckResult(name, Status.SKIPPED, "No --expect and no --reference to compare against.")
        dist, source = ideal_distribution(ref), "reference ideal distribution"
    n = cand.num_qubits

    try:
        counts = sample(cand, shots, seed)
    except Exception as exc:
        return CheckResult(name, Status.INCONCLUSIVE, f"Simulation failed: {exc!r}"[:300])

    ev: dict[str, Any] = {"shots": shots, "seed": seed, "expected_source": source, "observed_counts": counts}

    if dist is not None:
        total = sum(dist.values())
        dist = {k.replace(" ", "").zfill(n): float(v) / total for k, v in dist.items()}
        if any(len(k) != n for k in dist):
            res = CheckResult(name, Status.FAIL, f"Expected bitstrings do not match circuit width {n}.", ev)
            res.seconds = round(time.perf_counter() - t0, 4)
            return res
        keys = sorted(set(dist) | set(counts))
        obs = np.array([counts.get(k, 0) for k in keys], dtype=float)
        exp_p = np.array([dist.get(k, 0.0) for k in keys])
        tvd = 0.5 * float(np.abs(obs / shots - exp_p).sum())
        impossible = {k: counts[k] for k in counts if dist.get(k, 0.0) == 0.0}
        mask = exp_p > 0
        if mask.sum() > 1:
            exp_counts = exp_p[mask] * shots
            obs_in = obs[mask]
            # rescale so totals match (outcomes outside the support are handled separately)
            if obs_in.sum() > 0:
                exp_counts = exp_counts * obs_in.sum() / exp_counts.sum()
                chi2, p = stats.chisquare(obs_in, exp_counts)
            else:
                chi2, p = float("inf"), 0.0
        else:
            chi2, p = 0.0, 1.0
        ev.update({
            "expected_distribution": {k: round(v, 6) for k, v in sorted(dist.items())},
            "tvd": round(tvd, 5), "tvd_threshold": tvd_threshold,
            "chi2": round(float(chi2), 4), "p_value": float(f"{p:.4g}"), "alpha": alpha,
            "impossible_outcomes": impossible,
        })
        impossible_frac = sum(impossible.values()) / shots
        if impossible_frac > 0.01 or (tvd > tvd_threshold and p < alpha):
            why = []
            if impossible:
                why.append(f"{sum(impossible.values())} shots on outcomes with expected p=0")
            why.append(f"TVD={tvd:.3f} (>{tvd_threshold})" if tvd > tvd_threshold else f"TVD={tvd:.3f}")
            why.append(f"chi2 p={p:.2g}")
            status, summary = Status.FAIL, "Measured distribution disagrees with expectation: " + ", ".join(why) + "."
        elif tvd <= tvd_threshold and p >= alpha and not impossible:
            status, summary = Status.PASS, f"Consistent with expectation: TVD={tvd:.3f}, chi2 p={p:.2g}."
        else:
            status, summary = Status.INCONCLUSIVE, f"Borderline: TVD={tvd:.3f}, chi2 p={p:.2g}."
    else:
        allowed = {s.replace(" ", "").zfill(n) for s in support}
        outside = {k: v for k, v in counts.items() if k not in allowed}
        ev.update({"expected_support": sorted(allowed), "outside_support": outside})
        if outside:
            status, summary = Status.FAIL, f"{sum(outside.values())} shots landed outside the expected support."
        else:
            status, summary = Status.PASS, "All shots landed inside the expected support."
    res = CheckResult(name, status, summary, ev)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res


# --------------------------------------------------------------------------- 4. metrics


def metrics_check(qc: QuantumCircuit, compiled: list[tuple[str, QuantumCircuit]]) -> tuple[CheckResult, dict[str, Any]]:
    t0 = time.perf_counter()
    m = {"source": circuit_metrics(qc), "compiled": {label: circuit_metrics(tq) for label, tq in compiled}}
    src = m["source"]
    multi = f" + {src['multi_qubit_gates']} 3+-qubit gates" if src["multi_qubit_gates"] else ""
    parts = [f"{src['qubits']} qubits, depth {src['depth']}, {src['two_qubit_gates']} two-qubit gates{multi}"]
    for label, cm in m["compiled"].items():
        parts.append(f"compiled: depth {cm['depth']}, {cm['two_qubit_gates']} 2q gates")
        break
    res = CheckResult("Metrics", Status.PASS, "; ".join(parts) + ".", m)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res, m


# --------------------------------------------------------------------------- week 3: structural constraints

# Instructions that hide the logic inside a matrix / vector / library block. A circuit that uses one of
# these is not "written by hand" and the spec usually forbids them.
KNOWN_BLACK_BOXES = {
    "unitary": "UnitaryGate (explicit matrix)",
    "initialize": "Initialize (state vector + reset)",
    "state_preparation": "StatePreparation (state vector)",
    "isometry": "Isometry (explicit matrix)",
    "permutation": "PermutationGate (explicit permutation)",
    "qft": "QFTGate (library algorithm)",
    "diagonal": "DiagonalGate (explicit diagonal)",
    "hamiltonian": "HamiltonianGate (explicit matrix)",
    "linear_function": "LinearFunction (explicit matrix)",
    "pauli_evolution": "PauliEvolutionGate (library)",
}
HAND_WRITTEN_EXTRA = {"mcx", "mcphase", "mcp", "mcu1", "barrier"}


def _standard_names() -> set[str]:
    from qiskit.circuit.library import get_standard_gate_name_mapping

    return set(get_standard_gate_name_mapping()) | HAND_WRITTEN_EXTRA


def black_box_check(qc: QuantumCircuit, enabled: bool) -> CheckResult:
    """FAIL if the circuit (as written, not decomposed) contains a matrix/vector/library black box:
    UnitaryGate, Initialize, StatePreparation, PermutationGate, QFTGate, any other non-standard
    composite instruction (e.g. a library circuit appended with .to_gate()). mcx/mcphase are allowed."""
    t0 = time.perf_counter()
    name = "No black boxes"
    if not enabled:
        return CheckResult(name, Status.SKIPPED, "Black-box check not requested (--no-black-boxes).")
    std = _standard_names()
    found: dict[str, int] = {}
    for inst in qc.data:
        n = inst.operation.name
        if n not in std:
            found[n] = found.get(n, 0) + 1
    ev = {"black_boxes": found,
          "explanations": {k: KNOWN_BLACK_BOXES.get(k, "non-standard / library instruction") for k in found}}
    if found:
        res = CheckResult(name, Status.FAIL, "Uses black-box / library instructions: " +
                          ", ".join(f"{k} x{v} ({ev['explanations'][k]})" for k, v in found.items()) + ".", ev)
    else:
        res = CheckResult(name, Status.PASS, "Only standard gates (plus mcx/mcphase); no matrices, vectors or "
                                             "library blocks.", ev)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res


def parse_coupling(spec: str | list | None, num_qubits: int) -> list[tuple[int, int]] | None:
    """'linear' -> 0-1,1-2,...; 'ring' -> linear + (n-1)-0; '0-1,1-2' or [[0,1],[1,2]] -> explicit.
    Edges are undirected (cx direction is free)."""
    if spec is None:
        return None
    if isinstance(spec, (list, tuple)):
        edges = [tuple(int(x) for x in e) for e in spec]
    else:
        s = spec.strip().lower()
        if s == "linear":
            edges = [(i, i + 1) for i in range(num_qubits - 1)]
        elif s == "ring":
            edges = [(i, i + 1) for i in range(num_qubits - 1)] + ([(num_qubits - 1, 0)] if num_qubits > 2 else [])
        else:
            edges = []
            for part in s.replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                bits = part.replace(":", "-").split("-")
                if len(bits) != 2:
                    raise ValueError(f"bad coupling edge {part!r}; use 'a-b' pairs, 'linear' or 'ring'")
                edges.append((int(bits[0]), int(bits[1])))
    for a, b in edges:
        if a == b or min(a, b) < 0 or max(a, b) >= num_qubits:
            raise ValueError(f"bad coupling edge {a}-{b} for a {num_qubits}-qubit circuit")
    return sorted({tuple(sorted(e)) for e in edges})


def coupling_check(qc: QuantumCircuit, coupling: str | list | None) -> CheckResult:
    """Check the ORIGINAL circuit (before any transpilation): every 2-qubit gate must act on a coupling
    edge (either direction), and no gate may act on 3+ qubits (it cannot be native on the device)."""
    t0 = time.perf_counter()
    name = "Coupling-map constraint"
    edges = parse_coupling(coupling, qc.num_qubits)
    if edges is None:
        return CheckResult(name, Status.SKIPPED, "No --coupling given.")
    eset = set(edges)
    bad_2q: dict[str, int] = {}
    multi: dict[str, int] = {}
    first: list[dict[str, Any]] = []
    checked = 0
    for pos, inst in enumerate(unitary_part(qc).data):
        op = inst.operation
        if op.name == "barrier":
            continue
        qs = [qc.find_bit(q).index for q in inst.qubits]
        if len(qs) == 2:
            checked += 1
            if tuple(sorted(qs)) not in eset:
                key = f"{op.name}({qs[0]},{qs[1]})"
                bad_2q[key] = bad_2q.get(key, 0) + 1
                if len(first) < 5:
                    first.append({"position": pos, "gate": op.name, "qubits": qs})
        elif len(qs) > 2:
            key = f"{op.name}{tuple(qs)}"
            multi[key] = multi.get(key, 0) + 1
            if len(first) < 5:
                first.append({"position": pos, "gate": op.name, "qubits": qs})
    ev = {"edges": [list(e) for e in edges], "two_qubit_gates_checked": checked,
          "off_edge_two_qubit_gates": bad_2q, "multi_qubit_gates": multi, "first_violations": first}
    if bad_2q or multi:
        parts = []
        if bad_2q:
            parts.append(f"{sum(bad_2q.values())} two-qubit gate(s) off the coupling map: " +
                         ", ".join(f"{k} x{v}" for k, v in list(bad_2q.items())[:6]))
        if multi:
            parts.append(f"{sum(multi.values())} gate(s) on 3+ qubits: " +
                         ", ".join(f"{k} x{v}" for k, v in list(multi.items())[:6]))
        res = CheckResult(name, Status.FAIL, "; ".join(parts) + ".", ev)
    else:
        res = CheckResult(name, Status.PASS, f"All {checked} two-qubit gates act on coupling edges.", ev)
    res.seconds = round(time.perf_counter() - t0, 4)
    return res
