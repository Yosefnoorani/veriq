"""Unit tests for the real-bugs comparison tooling (benchmark/real_bugs/quanbench_veriq.py)."""
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark" / "real_bugs"))
import quanbench_veriq as qv  # noqa: E402


def test_compare_detects_same_state_but_different_unitary():
    # CH vs the ry/cx/ry/cx "CH" (controlled-(H.Z)): identical from |00>, different on control=1, target=|+>
    ref = QuantumCircuit(2); ref.ch(0, 1)
    cand = QuantumCircuit(2); cand.ry(math.pi / 4, 1); cand.cx(0, 1); cand.ry(-math.pi / 4, 1); cand.cx(0, 1)
    r = qv.compare(ref, cand)
    assert r["status"] == "decided"
    assert r["dist"] is True and r["state"] is True and r["unitary"] is False
    assert r["basis_inputs_max_tvd"] < 1e-6  # every basis input gives the same distribution


def test_compare_bit_reversal_and_inverse_flags():
    ref = QuantumCircuit(2); ref.cx(0, 1)
    cand = QuantumCircuit(2); cand.cx(1, 0)
    r = qv.compare(ref, cand)
    assert r["unitary"] is False and r["unitary_equal_after_bit_reversal"] is True
    ref = QuantumCircuit(1); ref.s(0)
    cand = QuantumCircuit(1); cand.sdg(0)
    r = qv.compare(ref, cand)
    assert r["unitary_equal_to_inverse"] is True and r["state"] is True


def test_measured_all_inputs_ignores_diagonal_phase_before_measurement():
    a = QuantumCircuit(2); a.h(0); a.cx(0, 1)
    b = a.copy(); b.cz(0, 1); b.t(1)
    assert qv.measured_all_inputs(Operator(a).data, Operator(b).data, [0, 1])
    c = a.copy(); c.h(1)
    assert not qv.measured_all_inputs(Operator(a).data, Operator(c).data, [0, 1])


def test_initial_prep_to_unitary_makes_initialize_decidable():
    a = QuantumCircuit(1); a.initialize([1 / np.sqrt(2), 1 / np.sqrt(2)], 0)
    b = QuantumCircuit(1); b.h(0)
    r = qv.compare(a, b)
    assert r["status"] == "decided" and r["state"] is True and r["initialize_rewritten"]


def test_pair_calls_ignores_object_addresses():
    calls = [{"role": "solution", "args": "(<Foo object at 0x7f00aa>,)", "kwargs": "{}"},
             {"role": "generated", "args": "(<Foo object at 0x7f11bb>,)", "kwargs": "{}"},
             {"role": "generated", "args": "(3,)", "kwargs": "{}"}]
    pairs, ns, ng = qv.pair_calls(calls)
    assert len(pairs) == 1 and (ns, ng) == (1, 2)
    # QuanBench117 style: canonical calls come from a separate capture
    pairs, _, _ = qv.pair_calls([calls[2]], [{"role": "generated", "args": "(3,)", "kwargs": "{}"}])
    assert len(pairs) == 1


def test_open_jsonl_falls_back_to_gzip(tmp_path):
    p = tmp_path / "x.capture.jsonl"
    with gzip.open(str(p) + ".gz", "wt") as f:
        f.write(json.dumps({"a": 1}) + "\n")
    assert [json.loads(l) for l in qv.open_jsonl(p)] == [{"a": 1}]


def test_committed_headline_is_consistent():
    root = Path(__file__).resolve().parents[1] / "benchmark" / "real_bugs" / "results"
    h = json.loads((root / "headline.json").read_text())
    c = h["combined"]
    assert c["tests_passed"] == sum(v["tests_passed"] for k, v in h.items() if k != "combined")
    assert c["wrong_strict"] <= c["wrong_incl_superposed_inputs"] <= c["tests_passed"]
    assert abs(c["share_wrong_strict_of_passed"] - c["wrong_strict"] / c["tests_passed"]) < 1e-3
