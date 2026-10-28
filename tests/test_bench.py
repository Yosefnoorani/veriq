"""Veriq Bench v0.1: data integrity, the run scorer, corpus-eval, leaderboard rendering, CLI."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from veriq import bench

ROOT = Path(__file__).resolve().parents[1]
V01 = ROOT / "benchmark" / "veriqbench" / "v0.1"
HARD = V01 / "submissions" / "hard-round-2026-10-27"
TASKS = ["maj5", "cmul7", "qpe_t", "c3x_linear", "reverse6_nn", "bv22", "add3"]


@pytest.fixture(scope="module")
def tasks():
    return bench.load_tasks(V01)


def test_manifest_matches_files():
    man = json.loads((V01 / "MANIFEST.json").read_text())
    files = man["files"] if "files" in man else man
    assert len(files) >= 7 + 2 + 3
    for rel, digest in files.items():
        d = digest["sha256"] if isinstance(digest, dict) else digest
        assert hashlib.sha256((V01 / rel).read_bytes()).hexdigest() == d, rel


def test_tasks_and_references(tasks):
    assert sorted(tasks) == sorted(TASKS)
    refs = bench.load_references(V01, tasks)
    for t, spec in tasks.items():
        assert spec["version"] == "0.1"
        assert spec["mode"] in ("unitary", "state")
        assert refs[t].num_qubits == spec["qubits"]
        assert spec["cost_model"]["qubits_initially_zero"] == (spec["mode"] == "state")
    assert tasks["c3x_linear"]["constraints"]["coupling"] == "linear"
    assert tasks["reverse6_nn"]["constraints"]["allowed_gates"] == ["cx"]


def test_corpus_counts_and_fields():
    rows = bench.load_corpus(V01)
    mut = [r for r in rows if r["id"].startswith("vb01-")]
    ok = [r for r in rows if not r["id"].startswith("vb01-")]
    assert len(mut) == 1036 and len(ok) == 28
    assert len({r["id"] for r in rows}) == len(rows)
    assert sum(r["equivalent"] for r in mut) == 70
    assert all(r["equivalent"] for r in ok)
    classes = {}
    for r in mut:
        classes[r["study_class"]] = classes.get(r["study_class"], 0) + 1
        assert r["mutation_class"] in {"delete_gate", "negate_angle", "pi_as_3.14", "flip_cx", "cp_to_crz", "p_to_rz"}
        assert set(r["detected_by"]) == {"histogram", "zero_state_exact", "all_basis", "proof"}
        assert r["detected_by"]["proof"] == (not r["equivalent"])
    assert classes == {"caught_by_histogram": 327, "missed_by_histogram_caught_by_truth_table": 596,
                       "proof_only_sampling_too_weak": 4, "proof_only_invisible_to_sampling": 39,
                       "equivalent_mutant": 70}
    assert bench.load_corpus(V01, negatives=False) == mut


def test_corpus_qasm_roundtrips():
    rows = bench.load_corpus(V01)
    for r in rows[::97]:
        qc = bench.qasm_circuit(r["qasm"])
        assert qc.num_qubits >= 4


def test_best_known_and_provenance():
    bk = json.loads((V01 / "best_known.json").read_text())["tasks"]
    assert {t: v["cx"] for t, v in bk.items()} == {"maj5": 239, "cmul7": 60, "qpe_t": 9, "c3x_linear": 24,
                                                     "reverse6_nn": 45, "bv22": 3, "add3": 25}
    assert all(v["status"] == "PROVEN_EQUIVALENT" for v in bk.values())
    prov = json.loads((HARD / "provenance.json").read_text())
    assert sorted(prov["models"]) == ["chatgpt", "claude", "gemini", "perplexity"]
    for m, p in prov["models"].items():
        assert p["model_version"].startswith("unknown")
        assert hashlib.sha256((HARD / f"{m}.py").read_bytes()).hexdigest() == p["source_sha256"]


def test_discover_layouts(tmp_path, tasks):
    (tmp_path / "flat.py").write_text("# all functions\n")
    (tmp_path / "_ignored.py").write_text("")
    d = tmp_path / "pertask"
    d.mkdir()
    (d / "maj5.py").write_text("")
    (d / "bv22.qasm").write_text("")
    s = tmp_path / "sol"
    s.mkdir()
    (s / "solution.py").write_text("")
    (s / "add3.qasm").write_text("")
    subs = bench.discover_submissions(tmp_path, tasks)
    assert sorted(subs) == ["flat", "pertask", "sol"]
    assert len(subs["flat"]) == 7
    assert sorted(subs["pertask"]) == ["bv22", "maj5"]
    assert subs["sol"]["add3"].suffix == ".qasm" and subs["sol"]["maj5"].name == "solution.py"
    with pytest.raises(FileNotFoundError):
        bench.discover_submissions(tmp_path / "nope", tasks)


GOOD_BV = """from qiskit import QuantumCircuit
def build_bv22():
    qc = QuantumCircuit(6)
    for q in (1, 2, 4):
        qc.x(q)
    return qc
"""
WRONG_BV = """from qiskit import QuantumCircuit
def build():
    qc = QuantumCircuit(6)
    qc.x(1); qc.x(2)
    return qc
"""
MEASURING_BV = """from qiskit import QuantumCircuit
circuit = QuantumCircuit(6)
for q in (1, 2, 4):
    circuit.x(q)
circuit.reset(5)
"""


@pytest.fixture(scope="module")
def tiny_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("outs")
    for name, src in {"good": GOOD_BV, "wrong": WRONG_BV, "reset": MEASURING_BV}.items():
        (d / name).mkdir()
        (d / name / "bv22.py").write_text(src)
    (d / "crash").mkdir()
    (d / "crash" / "bv22.py").write_text("raise RuntimeError('boom')\n")
    (d / "provenance.json").write_text(json.dumps({"round": "test", "models": {}}))
    return bench.run_bench(d, bench=V01, optimize=False, only_tasks=["bv22"])


def test_run_scores(tiny_run):
    r = {x["model"]: x for x in tiny_run["results"]}
    assert tiny_run["schema"] == "veriq.bench_run/1" and tiny_run["bench_version"] == "0.1"
    assert tiny_run["provenance"]["round"] == "test"
    assert r["good"]["status"] == "PASS" and r["good"]["correct"] and r["good"]["compliant"]
    assert r["good"]["cost"]["cx"] == 0
    assert r["good"]["gap"] == {"best_cx": 3, "cx_gap": -3, "cx_ratio": 0.0}
    assert r["wrong"]["status"] == "FAIL" and not r["wrong"]["correct"] and "gap" not in r["wrong"]
    assert r["reset"]["status"] != "PASS" and r["reset"]["constraints"]["no_measurements"] == "FAIL"
    assert r["crash"]["status"] == "BUILD_ERROR" and "boom" in r["crash"]["error"]
    s = tiny_run["summary"]
    assert s["good"]["pass"] == 1 and s["wrong"]["pass"] == 0 and s["good"]["tasks"] == 1


def test_run_missing_task(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "bv22.py").write_text(GOOD_BV)
    res = bench.run_bench(tmp_path, bench=V01, optimize=False, only_tasks=["bv22", "qpe_t"])
    st = {x["task"]: x["status"] for x in res["results"]}
    assert st == {"bv22": "PASS", "qpe_t": "MISSING"}


def test_run_hard_round_one_task_with_optimizer():
    res = bench.run_bench(HARD, bench=V01, optimize=True, budget=10, seeds=1, only_tasks=["bv22"],
                          only_models=["claude", "gemini"])
    assert all(x["status"] == "PASS" for x in res["results"])
    for x in res["results"]:
        assert x["optimized"]["status"] == "PROVEN_EQUIVALENT"
        assert x["optimized"]["cx"] <= x["cost"]["cx"]
        assert x["gap"]["best_cx"] <= 3


@pytest.mark.parametrize("det", ["histogram", "zero-state", "all-basis", "proof"])
def test_corpus_eval_builtin_matches_recorded(det):
    res = bench.corpus_eval(det, bench=V01, limit=24, only_tasks=["bv22", "c3x_linear", "qpe_t"])
    s = res["summary"]
    assert res["schema"] == "veriq.corpus_eval/1"
    assert s["wrong_mutants"] >= 10 and s["negatives"] >= 1 and s["errors"] == 0
    assert s["agreement_with_recorded_labels"] == 1.0
    assert s["false_positives"] == 0
    if det == "proof":
        assert s["recall"] == 1.0


def test_corpus_eval_custom_detectors(tmp_path):
    p = tmp_path / "dets.py"
    p.write_text("def always(c, r, mode, **kw):\n    return True\n"
                 "def never(c, r, mode, **kw):\n    return None\n"
                 "def crash(c, r, mode, **kw):\n    raise ValueError('x')\n")
    a = bench.corpus_eval(f"{p}:always", bench=V01, limit=8, only_tasks=["bv22"])["summary"]
    assert a["recall"] == 1.0 and a["false_positive_rate"] == 1.0 and a["agreement_with_recorded_labels"] is None
    n = bench.corpus_eval(f"{p}:never", bench=V01, limit=8, only_tasks=["bv22"])["summary"]
    assert n["detected"] == 0 and n["undecided_on_wrong"] == n["wrong_mutants"]
    c = bench.corpus_eval(f"{p}:crash", bench=V01, limit=8, only_tasks=["bv22"])["summary"]
    assert c["errors"] > 0 and c["detected"] == 0
    with pytest.raises(ValueError):
        bench.load_detector("no-such-detector")


def test_leaderboard_render(tiny_run):
    ev = bench.corpus_eval("zero-state", bench=V01, limit=8, only_tasks=["bv22"])
    md = bench.render_leaderboard_md(tiny_run, [ev])
    html = bench.render_leaderboard_html(tiny_run, [ev])
    assert "good" in md and "zero-state" in md
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "<script src" not in html and "<link " not in html  # self-contained
    assert "good" in html and "zero-state" in html


def test_committed_leaderboard_and_results_consistent():
    res = ROOT / "benchmark" / "veriqbench" / "results"
    run_f = res / "run_hard-round-2026-10-27.json"
    if not run_f.exists():
        pytest.skip("hard-round run not generated")
    run = json.loads(run_f.read_text())
    assert all(s["pass"] == 7 for s in run["summary"].values()) and len(run["summary"]) == 4
    for d, recall in {"histogram": 0.3385, "all-basis": 0.9596, "proof": 1.0}.items():
        s = json.loads((res / f"corpus_eval_{d}.json").read_text())["summary"]
        assert s["recall"] == recall and s["false_positives"] == 0 and s["wrong_mutants"] == 966


def test_cli_bench_smoke(tmp_path):
    out = tmp_path / "ce.json"
    r = subprocess.run([sys.executable, "-m", "veriq.cli", "bench", "corpus-eval", "-d", "all-basis", "--limit", "8",
                        "--tasks", "bv22", "--bench", str(V01), "-o", str(out)], capture_output=True, text=True,
                       cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text())["detector"] == "all-basis"
    d = tmp_path / "outs" / "good"
    d.mkdir(parents=True)
    (d / "bv22.py").write_text(GOOD_BV)
    run = tmp_path / "run.json"
    r = subprocess.run([sys.executable, "-m", "veriq.cli", "bench", "run", "-m", str(tmp_path / "outs"),
                        "--no-optimize", "--tasks", "bv22", "--bench", str(V01), "-o", str(run)],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "pass 1/1" in r.stdout
    r = subprocess.run([sys.executable, "-m", "veriq.cli", "bench", "leaderboard", "--run", str(run), "--corpus-eval",
                        str(out), "--out-dir", str(tmp_path / "lb")], capture_output=True, text=True, cwd=ROOT,
                       timeout=120)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "lb" / "leaderboard.html").exists()
