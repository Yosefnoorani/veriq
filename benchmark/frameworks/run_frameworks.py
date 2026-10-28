"""Cross-framework evidence: translate the hard-round circuits into OpenQASM 3, Cirq and TKET with each
framework's own converter, load them back through veriq's frontends, and prove each translation equivalent to
the Qiskit original. Deliberate mis-translations (reversed qubit order, dropped controlled phase, wrong angle
convention) are generated in each framework's own API and must be caught.

    python benchmark/frameworks/run_frameworks.py            # writes results.json / results.md / translations/

Subjects: the 7 hard-round references and two assistants' submissions (chatgpt, claude), loaded read-only from
benchmark/hard (raw/ is never written: bytecode writing is disabled).
Converters:
  OpenQASM 3: qiskit.qasm3.dumps (loaded back with qiskit.qasm3 / qiskit-qasm3-import)
  Cirq:       qiskit.qasm2.dumps -> cirq.contrib.qasm_import.circuit_from_qasm -> cirq.to_json
              (circuit first unrolled at optimization level 0 to gates Cirq's QASM importer knows)
  TKET:       pytket.extensions.qiskit.qiskit_to_tk -> Circuit.to_dict (JSON)
Equivalence: veriq.scale.decide_equivalence in unitary mode (stronger than the task's own mode), up to global
phase; ground truth for the mistakes comes from the dense 2^n x 2^n operators (all circuits have <= 6 qubits).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never drop __pycache__ into benchmark/hard/raw

import importlib.util  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402
from importlib.metadata import version  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HARD = ROOT / "benchmark" / "hard"
sys.path.insert(0, str(ROOT / "src"))

import cirq  # noqa: E402
from cirq.contrib.qasm_import import circuit_from_qasm  # noqa: E402
from pytket import Circuit as TkCircuit  # noqa: E402
from pytket import OpType  # noqa: E402
from pytket.extensions.qiskit import qiskit_to_tk  # noqa: E402
from pytket.passes import DecomposeBoxes  # noqa: E402
from qiskit import QuantumCircuit, qasm2, qasm3, transpile  # noqa: E402
from qiskit.quantum_info import Operator  # noqa: E402

from veriq.loader import load_circuit  # noqa: E402
from veriq.scale import decide_equivalence  # noqa: E402

ASSISTANTS = ["chatgpt", "claude"]
GZIP_ABOVE = 64_000
CIRQ_BASIS = ["u3", "u2", "u1", "cx", "cz", "cp", "crz", "ccx", "cswap", "swap", "h", "x", "y", "z", "s", "sdg",
              "t", "tdg", "rx", "ry", "rz", "id", "sx"]
CPHASE_QASM = re.compile(r"^\s*(cp|crz|cu1|cz)\b")


def _refs():
    spec = importlib.util.spec_from_file_location("veriq_hard_references", HARD / "references.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _strip(qc: QuantumCircuit) -> QuantumCircuit:
    return qc.remove_final_measurements(inplace=False)


def truly_equal(a: QuantumCircuit, b: QuantumCircuit) -> tuple[bool, bool]:
    """(equal up to global phase, exactly equal) from dense operators."""
    A, B = Operator(_strip(a)).data, Operator(_strip(b)).data
    if A.shape != B.shape:
        return False, False
    i = np.unravel_index(np.argmax(abs(A)), A.shape)
    if abs(B[i]) < 1e-9:
        return False, False
    ph = B[i] / A[i]
    up = abs(abs(ph) - 1) < 1e-8 and np.allclose(A * ph, B, atol=1e-8)
    return bool(up), bool(np.allclose(A, B, atol=1e-8))


# ----------------------------------------------------------------------------- translations (framework tools)

def to_qasm3(qc: QuantumCircuit) -> str:
    return qasm3.dumps(qc)


def flatten(qc: QuantumCircuit) -> QuantumCircuit:
    # qubits_initially_zero=False: Qiskit >= 2's default lets synthesis assume |0> inputs (e.g. for mcx), which
    # changes the unitary -- exactly the zero-init hazard veriq reports. A translation must keep the unitary.
    return transpile(qc, basis_gates=CIRQ_BASIS, optimization_level=0, qubits_initially_zero=False)


def to_cirq(qc: QuantumCircuit) -> cirq.Circuit:
    c = circuit_from_qasm(qasm2.dumps(flatten(qc)))
    # Cirq circuits have no register width: qubits that no gate touches vanish. Keep the declared width by
    # adding identities (Cirq orders NamedQubit q_0..q_n naturally, so q_i stays qubit i).
    idle = [cirq.NamedQubit(f"q_{i}") for i in range(qc.num_qubits)
            if cirq.NamedQubit(f"q_{i}") not in c.all_qubits()]
    return c + cirq.Circuit(cirq.I(q) for q in idle) if idle else c


def to_tket(qc: QuantumCircuit) -> TkCircuit:
    return qiskit_to_tk(qc)


# ----------------------------------------------------------------------------- deliberate mistakes

def qasm3_reversed(qc: QuantumCircuit) -> str:
    """Author maps QASM q[i] to qubit n-1-i (reads the register big-endian)."""
    return qasm3.dumps(qc.reverse_bits())


def qasm3_drop_cphase(qc: QuantumCircuit) -> str | None:
    lines = qasm3.dumps(flatten(qc)).splitlines()
    for i, ln in enumerate(lines):
        if CPHASE_QASM.match(ln):
            return "\n".join(lines[:i] + lines[i + 1:]) + "\n"
    return None


def cirq_reversed(c: cirq.Circuit) -> cirq.Circuit:
    qs = sorted(c.all_qubits())
    m = {q: qs[len(qs) - 1 - i] for i, q in enumerate(qs)}
    return c.transform_qubits(lambda q: m[q])


def _is_cphase(op) -> bool:
    g = op.gate
    if isinstance(g, cirq.CZPowGate):
        return True
    return isinstance(g, cirq.ControlledGate) and isinstance(g.sub_gate, cirq.ZPowGate)


def cirq_drop_cphase(c: cirq.Circuit) -> cirq.Circuit | None:
    ops = list(c.all_operations())
    for i, op in enumerate(ops):
        if _is_cphase(op):
            return cirq.Circuit(ops[:i] + ops[i + 1:])
    return None


def cirq_angle_as_exponent(c: cirq.Circuit) -> cirq.Circuit | None:
    """Author passes the angle in radians where Cirq's `exponent` (half-turns) is expected."""
    ops = list(c.all_operations())
    for i, op in enumerate(ops):
        g = op.gate
        base = g.sub_gate if isinstance(g, cirq.ControlledGate) else g
        if isinstance(base, (cirq.ZPowGate, cirq.XPowGate, cirq.YPowGate)) and not float(base.exponent).is_integer():
            nb = type(base)(exponent=base.exponent * math.pi, global_shift=base.global_shift)
            ng = cirq.ControlledGate(nb, num_controls=g.num_controls()) if isinstance(g, cirq.ControlledGate) else nb
            return cirq.Circuit(ops[:i] + [ng.on(*op.qubits)] + ops[i + 1:])
    return None


def _tk_copy(t: TkCircuit, edit) -> TkCircuit | None:
    """Rebuild t command by command; edit(i, cmd) returns None (keep), 'drop', or (op, qubit indices)."""
    out = TkCircuit(t.n_qubits)
    out.add_phase(t.phase)
    idx = {q: i for i, q in enumerate(t.qubits)}
    changed = False
    for i, cmd in enumerate(t.get_commands()):
        e = edit(i, cmd)
        qs = [idx[q] for q in cmd.qubits]
        if e == "drop":
            changed = True
            continue
        if e is not None:
            op, qs = e
            changed = True
        else:
            op = cmd.op
        out.add_gate(op, qs)
    return out if changed else None


def tket_reversed(t: TkCircuit) -> TkCircuit:
    n = t.n_qubits
    idx = {q: i for i, q in enumerate(t.qubits)}
    out = TkCircuit(n)
    out.add_phase(t.phase)
    for cmd in t.get_commands():
        out.add_gate(cmd.op, [n - 1 - idx[q] for q in cmd.qubits])
    return out


def tket_drop_cphase(t: TkCircuit) -> TkCircuit | None:
    done = []

    def edit(i, cmd):
        if not done and cmd.op.type in (OpType.CU1, OpType.CRz, OpType.CZ):
            done.append(i)
            return "drop"
        return None

    return _tk_copy(t, edit)


def tket_radians_as_halfturns(t: TkCircuit) -> TkCircuit | None:
    """Author writes radians where TKET expects half-turns (TKET angles are in units of pi)."""
    from pytket.circuit import Op

    done = []
    idx = {q: i for i, q in enumerate(t.qubits)}

    def edit(i, cmd):
        ps = cmd.op.params
        if not done and ps and any(abs(float(p) - round(float(p))) > 1e-9 for p in ps):
            done.append(i)
            return Op.create(cmd.op.type, [float(p) * math.pi for p in ps]), [idx[q] for q in cmd.qubits]
        return None

    return _tk_copy(t, edit)


def tket_extra_global_phase(t: TkCircuit) -> TkCircuit:
    """Control: only a global phase differs -> must be reported EQUIVALENT (whole-circuit phase is unobservable)."""
    out = t.copy()
    out.add_phase(0.5)
    return out


# ----------------------------------------------------------------------------- harness

def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def judge(orig: QuantumCircuit, path: Path, framework: str) -> dict:
    t0 = time.perf_counter()
    try:
        qc = load_circuit(path, None, framework)
    except Exception as exc:  # noqa: BLE001
        return {"loaded": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    load_s = time.perf_counter() - t0
    d = decide_equivalence(_strip(orig), _strip(qc), mode="unitary", timeout=60)
    up, exact = truly_equal(orig, qc)
    meta = (qc.metadata or {}).get("veriq_frontend", {})
    import gzip
    import hashlib

    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    stored = path
    if len(raw) > GZIP_ABOVE:  # keep the repo small: large files are stored gzipped (gunzip to re-check)
        stored = path.with_name(path.name + ".gz")
        stored.write_bytes(gzip.compress(raw, mtime=0))
        path.unlink()
    return {"sha256": sha, "stored_as": str(stored.relative_to(HERE)),"loaded": True, "status": d["status"], "method": d.get("method"), "seconds": round(d["seconds"] + load_s, 3),
            "truth_equivalent": up, "exact_global_phase": exact, "opaque_ops": meta.get("opaque_ops", 0),
            "file": str(path.relative_to(HERE)), "bytes": len(raw)}


def main() -> int:
    R = _refs()
    tr_dir = HERE / "translations"
    subjects = []
    for task, spec in R.TASKS.items():
        subjects.append((f"ref_{task}", task, getattr(R, spec["fn"])()))
    for a in ASSISTANTS:
        for task, spec in R.TASKS.items():
            subjects.append((f"{a}_{task}", task, load_circuit(HARD / "raw" / f"{a}.py", spec["fn"])))
    rows = []
    hazards = []
    t_all = time.perf_counter()
    for sid, task, qc in subjects:
        d = tr_dir / sid
        naive = transpile(qc, basis_gates=CIRQ_BASIS, optimization_level=0)  # Qiskit default (zero-init assumed)
        hazards.append({"subject": sid, "naive_flatten_equivalent": truly_equal(qc, naive)[0]})
        cz = to_cirq(qc)
        tk = to_tket(qc)
        files = {
            "qasm3": write(d / "translation.qasm", to_qasm3(qc)),
            "cirq": write(d / "translation.cirq.json", cirq.to_json(cz)),
            "tket": write(d / "translation.tket.json", json.dumps(tk.to_dict())),
        }
        for fw, p in files.items():
            rows.append({"subject": sid, "task": task, "qubits": qc.num_qubits, "framework": fw,
                         "kind": "translation", "variant": "faithful", **judge(qc, p, fw)})
        tkm = tk.copy()
        DecomposeBoxes().apply(tkm)  # edit plain gates, not boxes (qiskit_to_tk keeps sub-circuits as CircBox)
        mistakes = {
            ("qasm3", "reversed_qubit_order"): qasm3_reversed(qc),
            ("qasm3", "dropped_controlled_phase"): qasm3_drop_cphase(qc),
            ("cirq", "reversed_qubit_order"): cirq_reversed(cz),
            ("cirq", "dropped_controlled_phase"): cirq_drop_cphase(cz),
            ("cirq", "radians_as_exponent"): cirq_angle_as_exponent(cz),
            ("tket", "reversed_qubit_order"): tket_reversed(tkm),
            ("tket", "dropped_controlled_phase"): tket_drop_cphase(tkm),
            ("tket", "radians_as_halfturns"): tket_radians_as_halfturns(tkm),
            ("tket", "extra_global_phase_control"): tket_extra_global_phase(tkm),
        }
        for (fw, var), obj in mistakes.items():
            base = {"subject": sid, "task": task, "qubits": qc.num_qubits, "framework": fw,
                    "kind": "control" if var.endswith("_control") else "mistake", "variant": var}
            if obj is None:
                rows.append({**base, "applicable": False, "note": "circuit has no gate this mistake applies to"})
                continue
            if fw == "qasm3":
                p = write(d / f"mistake_{var}.qasm", obj)
            elif fw == "cirq":
                p = write(d / f"mistake_{var}.cirq.json", cirq.to_json(obj))
            else:
                p = write(d / f"mistake_{var}.tket.json", json.dumps(obj.to_dict()))
            rows.append({**base, "applicable": True, **judge(qc, p, fw)})
        print(sid, "done", flush=True)
    res = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"),
           "versions": {k: version(k) for k in ("qiskit", "qiskit-qasm3-import", "cirq-core", "pytket",
                                                 "pytket-qiskit", "mqt.qcec")},
           "subjects": [s[0] for s in subjects], "seconds_total": round(time.perf_counter() - t_all, 1),
           "rows": rows, "summary": summarize(rows),
           "naive_flatten": {"changed_unitary": [h["subject"] for h in hazards if not h["naive_flatten_equivalent"]],
                             "total": len(hazards)}}
    (HERE / "results.json").write_text(json.dumps(res, indent=1))
    (HERE / "results.md").write_text(render(res))
    print(json.dumps(res["summary"], indent=1))
    return 0


def summarize(rows: list[dict]) -> dict:
    out: dict = {"translations": {}, "mistakes": {}, "controls": {}}
    for r in rows:
        if r["kind"] == "translation":
            s = out["translations"].setdefault(r["framework"], {"total": 0, "loaded": 0, "proven": 0,
                                                                 "exact_global_phase": 0, "opaque_ops": 0})
            s["total"] += 1
            s["loaded"] += r.get("loaded", False)
            s["proven"] += r.get("status") == "PROVEN_EQUIVALENT"
            s["exact_global_phase"] += bool(r.get("exact_global_phase"))
            s["opaque_ops"] += r.get("opaque_ops", 0) or 0
        elif r["kind"] == "mistake":
            key = f'{r["framework"]}/{r["variant"]}'
            s = out["mistakes"].setdefault(key, {"applicable": 0, "actually_wrong": 0, "caught": 0,
                                                 "harmless_for_circuit": 0, "harmless_reported_equivalent": 0,
                                                 "missed": 0, "false_alarm": 0})
            if not r.get("applicable"):
                continue
            s["applicable"] += 1
            wrong = not r.get("truth_equivalent")
            st = r.get("status")
            if wrong:
                s["actually_wrong"] += 1
                s["caught"] += st == "NOT_EQUIVALENT"
                s["missed"] += st == "PROVEN_EQUIVALENT"
            else:
                s["harmless_for_circuit"] += 1
                s["harmless_reported_equivalent"] += st == "PROVEN_EQUIVALENT"
                s["false_alarm"] += st == "NOT_EQUIVALENT"
        else:
            s = out["controls"].setdefault(f'{r["framework"]}/{r["variant"]}', {"total": 0, "proven": 0})
            s["total"] += 1
            s["proven"] += r.get("status") == "PROVEN_EQUIVALENT"
    tot = out["mistakes"].values()
    out["mistakes_total"] = {"actually_wrong": sum(s["actually_wrong"] for s in tot),
                             "caught": sum(s["caught"] for s in tot), "missed": sum(s["missed"] for s in tot),
                             "harmless_for_circuit": sum(s["harmless_for_circuit"] for s in tot),
                             "false_alarm": sum(s["false_alarm"] for s in tot)}
    return out


def render(res: dict) -> str:
    s = res["summary"]
    v = res["versions"]
    L = ["# Cross-framework translations (Stage 5)", "",
         f"Generated {res['generated']}; {len(res['subjects'])} circuits (7 hard-round references + "
         f"{', '.join(ASSISTANTS)} submissions), {res['seconds_total']} s total.",
         f"Versions: " + ", ".join(f"{k} {x}" for k, x in v.items()) + ".", "",
         "Each circuit is translated with the framework's own tool (qiskit.qasm3.dumps; qasm2 -> "
         "cirq.contrib.qasm_import -> cirq JSON; pytket qiskit_to_tk -> TKET JSON), loaded back through "
         "veriq's frontend, and checked against the Qiskit original with `decide_equivalence` in unitary mode "
         "(up to global phase). Ground truth comes from dense operators (all circuits <= 6 qubits).", "",
         "## Faithful translations", "",
         "| framework | translations | loaded | proven equivalent | exact incl. global phase | opaque ops |",
         "|---|---|---|---|---|---|"]
    for fw, x in s["translations"].items():
        L.append(f"| {fw} | {x['total']} | {x['loaded']} | {x['proven']} | {x['exact_global_phase']} | {x['opaque_ops']} |")
    L += ["", "## Deliberate mis-translations", "",
          "| framework / mistake | applicable | actually wrong | caught (NOT_EQUIVALENT) | missed | "
          "harmless for that circuit | false alarms |", "|---|---|---|---|---|---|---|"]
    for k, x in s["mistakes"].items():
        L.append(f"| {k} | {x['applicable']} | {x['actually_wrong']} | {x['caught']} | {x['missed']} | "
                 f"{x['harmless_for_circuit']} | {x['false_alarm']} |")
    t = s["mistakes_total"]
    L += ["", f"**Total: {t['caught']}/{t['actually_wrong']} actually-wrong translations caught, {t['missed']} "
              f"missed, {t['false_alarm']} false alarms.** {t['harmless_for_circuit']} mistakes did not change "
              "the unitary of that particular circuit (e.g. reversing the qubits of a palindromic circuit such as "
              "reverse6_nn) and were correctly reported equivalent.", "",
          "## Controls", "", "| control | total | proven equivalent |", "|---|---|---|"]
    for k, x in s["controls"].items():
        L.append(f"| {k} | {x['total']} | {x['proven']} |")
    L += ["", "An extra whole-circuit global phase is unobservable, so it must not be flagged; a *controlled* phase "
              "is observable and dropping it is caught (table above).", "",
          "## Per circuit", "", "| subject | framework | variant | status | truth | seconds |", "|---|---|---|---|---|---|"]
    for r in res["rows"]:
        if r.get("applicable") is False:
            L.append(f"| {r['subject']} | {r['framework']} | {r['variant']} | n/a | n/a | |")
            continue
        truth = "equiv" if r.get("truth_equivalent") else "differs"
        L.append(f"| {r['subject']} | {r['framework']} | {r['variant']} | {r.get('status', r.get('error'))} | "
                 f"{truth} | {r.get('seconds', '')} |")
    nf = res["naive_flatten"]
    L += ["", "## Finding: flattening for Cirq's QASM importer", "",
          f"Unrolling with Qiskit's default `transpile(..., optimization_level=0)` (qubits_initially_zero=True) "
          f"changed the unitary of {len(nf['changed_unitary'])}/{nf['total']} circuits "
          f"({', '.join(nf['changed_unitary']) or 'none'}): mcx synthesis may assume |0> helper qubits. The "
          "harness flattens with qubits_initially_zero=False; an unchecked converter pipeline would have shipped a "
          "wrong translation. Cirq circuits also drop qubits no gate touches, so the harness pads idle register "
          "qubits with `cirq.I`."]
    L += ["", "## Limitations", "",
          "- OpenQASM 2 (the Cirq route) has no global phase; the proofs are up to global phase and the 'exact' "
          "column reports the dense-operator check including phase.",
          "- Files over 64 kB are stored gzipped (`*.gz`); `stored_as`/`sha256` in results.json identify them.",
          "- Equivalence is checked in unitary mode for every circuit, including the state-mode tasks (qpe_t, bv22): "
          "a translation must preserve the whole unitary.",
          "- Mistakes are single, targeted edits of the first applicable gate; they are illustrations, not a "
          "random mutation study.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
