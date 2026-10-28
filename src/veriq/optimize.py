"""Verified CX optimizer: many compilations, each one PROVEN equivalent before it may win.

`optimize_circuit` builds candidates from Qiskit's transpiler (optimization levels 0-3, several seeds,
approximation OFF, `qubits_initially_zero=False` so no pass may assume |0> inputs, plus an extra
resynthesis/cancellation round on top of level 3, and for <= 6 qubits a rebuild from the exact matrix by
quantum Shannon decomposition, or from the exact output state in state mode), ranks them by two-qubit-gate count and then depth, and
proves them cheapest-first with `scale.decide_equivalence`. The first candidate whose status is
PROVEN_EQUIVALENT is returned. A candidate that is only PROBABLY_EQUIVALENT (falsification), UNKNOWN or
NOT_EQUIVALENT is never returned; if nothing is proven, `best` is None.

Without a coupling map every candidate is compared as a plain circuit on the same qubits (any layout or
output permutation a pass recorded is dropped first, so a pass that silently permutes outputs fails the
proof instead of slipping through). With a coupling map the routed circuit keeps its layout and the proof
is "equal up to the recorded initial/final layout", which is how a routed circuit is meant to be used;
`allow_permutation=True` opts into the same layout-aware proof without a coupling map (then a candidate
may end with its qubits permuted, as recorded in `circuit.layout`).
In state mode the proof is "same state from |0..0>", and candidates compiled with
`qubits_initially_zero=True` are allowed too (they are still proven).
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from qiskit import QuantumCircuit, transpile

from . import scale
from .checks import parse_coupling, unitary_part

DEFAULT_BASIS = ["cx", "rz", "sx", "x"]


def two_qubit_count(qc: QuantumCircuit) -> int:
    return sum(1 for inst in qc.data if inst.operation.num_qubits == 2 and inst.operation.name != "barrier")


def _metrics(qc: QuantumCircuit) -> dict[str, Any]:
    return {"cx": two_qubit_count(qc), "depth": qc.depth(), "size": qc.size()}


def _plain(qc: QuantumCircuit, n: int) -> QuantumCircuit | None:
    """The same gates on qubits 0..n-1 with no layout attached (None if the circuit is wider)."""
    if qc.num_qubits != n:
        return None
    out = QuantumCircuit(n, global_phase=qc.global_phase)
    for inst in qc.data:
        out.append(inst.operation, [qc.find_bit(q).index for q in inst.qubits])
    return out


def _extra_round(qc: QuantumCircuit, basis: list[str], rounds: int = 4) -> QuantumCircuit:
    """Block consolidation + exact two-qubit resynthesis + commutation cancellation until no CX is saved."""
    from qiskit.transpiler import PassManager
    from qiskit.transpiler.passes import (Collect2qBlocks, CommutativeCancellation, ConsolidateBlocks,
                                          Optimize1qGatesDecomposition, UnitarySynthesis)

    pm = PassManager([Collect2qBlocks(), ConsolidateBlocks(basis_gates=basis, approximation_degree=1.0),
                      UnitarySynthesis(basis_gates=basis, approximation_degree=1.0),
                      Optimize1qGatesDecomposition(basis=basis), CommutativeCancellation(basis_gates=basis),
                      Optimize1qGatesDecomposition(basis=basis)])
    best = qc
    for _ in range(rounds):
        nxt = pm.run(best)
        if (two_qubit_count(nxt), nxt.depth()) >= (two_qubit_count(best), best.depth()):
            break
        best = nxt
    return best


def _no_elide(level: int, basis: list[str], seed: int, zero: bool):
    """Preset pass manager whose init stage drops ElidePermutations and Split2QUnitaries (both may turn
    gates into a virtual output permutation)."""
    from qiskit.transpiler import PassManager, generate_preset_pass_manager

    pm = generate_preset_pass_manager(level, basis_gates=basis, seed_transpiler=seed, approximation_degree=1.0,
                                      qubits_initially_zero=zero)
    keep = []
    for task in pm.init._tasks:
        group = [p for p in task if type(p).__name__ not in ("ElidePermutations", "Split2QUnitaries")]
        keep += group
    pm.init = PassManager(keep)
    return pm


RESYNTH_MAX_QUBITS = 6


def _resynthesized(qc: QuantumCircuit, mode: str) -> QuantumCircuit | None:
    """Rebuild a small circuit from its exact matrix (unitary mode: quantum Shannon decomposition) or its
    exact output state (state mode: StatePreparation). Numerically exact, still proven like any candidate."""
    from qiskit.quantum_info import Operator, Statevector

    n = qc.num_qubits
    if n > RESYNTH_MAX_QUBITS or n < 2:
        return None
    if mode == "state":
        from qiskit.circuit.library import StatePreparation

        out = QuantumCircuit(n)
        out.append(StatePreparation(Statevector(qc).data), range(n))
        return out
    from qiskit.synthesis import qs_decomposition

    return qs_decomposition(Operator(qc).data)


def candidates(qc: QuantumCircuit, basis: list[str], coupling: list | None, seeds: int, mode: str,
               budget: float, t0: float):
    seed_list = [2026 + 17 * k for k in range(max(1, seeds))]
    try:
        rs = _resynthesized(qc, mode)
    except Exception as exc:  # noqa: BLE001
        rs, err = None, f"{type(exc).__name__}: {exc}"[:200]
        yield {"optimization_level": 3, "seed": seed_list[0], "qubits_initially_zero": False,
               "variant": "resynthesis"}, None, err
    if rs is not None:
        for level in (1, 3):
            cfg = {"optimization_level": level, "seed": seed_list[0], "qubits_initially_zero": False,
                   "variant": "state-resynthesis" if mode == "state" else "unitary-resynthesis (QSD)"}
            try:
                yield cfg, transpile(rs, basis_gates=basis, coupling_map=coupling, optimization_level=level,
                                     seed_transpiler=seed_list[0], approximation_degree=1.0,
                                     qubits_initially_zero=False), None
            except Exception as exc:  # noqa: BLE001
                yield cfg, None, f"{type(exc).__name__}: {exc}"[:200]
    zero_flags = [False, True] if mode == "state" else [False]
    for zero in zero_flags:
        for level in (0, 1, 2, 3):
            for seed in (seed_list if level >= 1 else seed_list[:1]):
                if time.perf_counter() - t0 > budget:
                    return
                cfg = {"optimization_level": level, "seed": seed, "qubits_initially_zero": zero}
                try:
                    out = transpile(qc, basis_gates=basis, coupling_map=coupling, optimization_level=level,
                                    seed_transpiler=seed, approximation_degree=1.0, qubits_initially_zero=zero)
                except Exception as exc:  # noqa: BLE001 - one bad configuration must not stop the search
                    yield cfg, None, f"{type(exc).__name__}: {exc}"[:200]
                    continue
                yield cfg, out, None
                if level >= 2 and coupling is None:
                    # Levels 2-3 may elide SWAPs into a recorded output permutation; a plain circuit then
                    # differs from the source. Also compile with those layout-changing passes removed.
                    try:
                        yield dict(cfg, variant="no-permutation-elision"), \
                            _no_elide(level, basis, seed, zero).run(qc), None
                    except Exception as exc:  # noqa: BLE001
                        yield dict(cfg, variant="no-permutation-elision"), None, f"{type(exc).__name__}: {exc}"[:200]
                if level == 3 and coupling is None:
                    try:
                        ex = _extra_round(_plain(out, qc.num_qubits) or out, basis)
                        yield dict(cfg, extra="consolidate+resynthesize+commutative-cancel"), ex, None
                    except Exception as exc:  # noqa: BLE001
                        yield dict(cfg, extra="failed"), None, f"{type(exc).__name__}: {exc}"[:200]


def _to_qasm(qc: QuantumCircuit) -> str | None:
    try:
        from qiskit import qasm2

        return qasm2.dumps(qc)
    except Exception:  # noqa: BLE001
        return None


def optimize_circuit(circuit: QuantumCircuit, mode: str = "unitary", basis_gates: list[str] | None = None,
                     coupling: str | list | None = None, seeds: int = 4, timeout: float = 30.0,
                     budget: float = 300.0, max_proofs: int = 12,
                     allow_permutation: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    basis = list(basis_gates or DEFAULT_BASIS)
    src = unitary_part(circuit)
    n = src.num_qubits
    edges = parse_coupling(coupling, n) if coupling else None
    cmap = [list(e) for e in edges] + [[b, a] for a, b in edges] if edges else None
    baseline = transpile(src, basis_gates=basis, optimization_level=0, approximation_degree=1.0,
                         qubits_initially_zero=False)
    ref_l3 = None
    pool: dict[str, dict[str, Any]] = {}
    errors = []
    for cfg, out, err in candidates(src, basis, cmap, seeds, mode, budget * 0.5, t0):
        if out is None:
            errors.append({"config": cfg, "error": err})
            continue
        keep_layout = bool(cmap) or (allow_permutation and getattr(out, "layout", None) is not None)
        cand = out if keep_layout else _plain(out, n)
        if cand is None:
            errors.append({"config": cfg, "error": "candidate is wider than the source"})
            continue
        if (cfg["optimization_level"] == 3 and "extra" not in cfg and not cfg["qubits_initially_zero"]
                and ref_l3 is None):
            ref_l3 = dict(_metrics(cand), config=cfg, circuit=cand)
        key = hashlib.sha1((_to_qasm(cand) or repr(cand.data)).encode()).hexdigest()
        if key in pool:
            pool[key]["configs"].append(cfg)
            continue
        pool[key] = dict(_metrics(cand), config=cfg, configs=[cfg], circuit=cand)
    ranked = sorted(pool.values(), key=lambda c: (c["cx"], c["depth"], c["size"]))
    tried: list[dict[str, Any]] = []
    best = None
    for c in ranked[:max_proofs]:
        left = budget - (time.perf_counter() - t0)
        if left <= 1:
            break
        r = scale.decide_equivalence(c["circuit"], src, mode=mode, timeout=min(timeout, left))
        rec = {k: v for k, v in c.items() if k not in ("circuit", "configs")}
        rec.update(status=r["status"], method=r["method"], proof_seconds=r["seconds"], same_as=len(c["configs"]))
        tried.append(rec)
        if r["status"] == scale.PROVEN:
            best = dict(rec, circuit=c["circuit"])
            break
    if ref_l3 is not None:
        r = scale.decide_equivalence(ref_l3.pop("circuit"), src, mode=mode, timeout=min(timeout, 10.0))
        ref_l3["status"] = r["status"]
        ref_l3["note"] = ("plain `transpile(optimization_level=3)` output, proven for the record; it is NOT a "
                          "drop-in replacement when status != PROVEN_EQUIVALENT (e.g. it elided SWAPs into an "
                          "output permutation)")
    out: dict[str, Any] = {
        "mode": mode, "basis": basis, "coupling": coupling, "qubits": n,
        "source": _metrics(src), "baseline": dict(_metrics(baseline), config="optimization_level=0"),
        "qiskit_level3": ref_l3,
        "counts": {"compiled": sum(len(c["configs"]) for c in pool.values()), "distinct": len(pool),
                   "proof_attempts": len(tried), "errors": len(errors)},
        "tried": tried, "errors": errors[:5],
        "best": {k: v for k, v in best.items() if k != "circuit"} if best else None,
        "best_circuit": best["circuit"] if best else None,
        "best_qasm": _to_qasm(best["circuit"]) if best else None,
        "proof_scope": ("plain circuit, same qubits" if not (cmap or allow_permutation)
                        else "up to the initial/final layout recorded on the circuit")
                       + ("; same state from |0..0>" if mode == "state" else "; every input"),
        "seconds": round(time.perf_counter() - t0, 3),
    }
    if best:
        out["cx_saved_vs_baseline"] = out["baseline"]["cx"] - best["cx"]
        lay = getattr(best["circuit"], "layout", None)
        if lay is not None:
            try:
                out["best"]["final_index_layout"] = list(lay.final_index_layout())
            except Exception:  # noqa: BLE001
                pass
            out["best"]["note"] = ("equal up to the layout recorded on the circuit (see final_index_layout); "
                                   "the QASM text does not carry that permutation")
        if ref_l3 and ref_l3.get("status") == scale.PROVEN:
            out["cx_saved_vs_qiskit_level3"] = ref_l3["cx"] - best["cx"]
    return out
