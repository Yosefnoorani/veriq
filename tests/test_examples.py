"""End-to-end: every example gets the verdict it deserves, through the real CLI."""
import json

import pytest

from veriq.cli import main

CASES = [
    ("bell_correct.py", None, "expect/bell.json", "PASS"),
    ("bell.qasm", None, "expect/bell.json", "PASS"),
    ("ghz_correct.py", None, "expect/ghz3.json", "PASS"),
    ("ghz3.qasm3", "ghz_correct.py", None, "PASS"),
    ("ghz_buggy.py", "ghz_correct.py", "expect/ghz3.json", "FAIL"),
    ("qft_correct.py", "qft_reference.py", None, "PASS"),
    ("qft_buggy.py", "qft_reference.py", None, "FAIL"),
    ("grover_correct.py", "grover_reference.py", "expect/grover3_101.json", "PASS"),
    ("grover_buggy.py", "grover_reference.py", "expect/grover3_101.json", "FAIL"),
]


@pytest.mark.parametrize("cand,ref,expect,want", CASES)
def test_example_verdicts(ex, tmp_path, cand, ref, expect, want):
    out = tmp_path / "r.html"
    argv = ["check", ex(cand), "--report", str(out), "-q"]
    if ref:
        argv += ["--reference", ex(ref)]
    if expect:
        argv += ["--expect", ex(expect)]
    code = main(argv)
    data = json.loads(out.with_suffix(".json").read_text())
    assert data["verdict"] == want
    assert code == {"PASS": 0, "FAIL": 1}[want]
    html = out.read_text()
    assert html.startswith("<!doctype html>") and want in html
    assert "http://" not in html and "https://" not in html  # self-contained


def test_qft_bug_only_caught_by_equivalence(ex, tmp_path):
    """The subtle QFT bug passes the naive histogram test but fails the proof, with a counterexample."""
    out = tmp_path / "q.html"
    main(["check", ex("qft_buggy.py"), "--reference", ex("qft_reference.py"), "--report", str(out), "-q"])
    checks = {c["name"]: c for c in json.loads(out.with_suffix(".json").read_text())["checks"]}
    assert checks["Statistical test (Aer)"]["status"] == "PASS"
    ref = checks["Reference equivalence"]
    assert ref["status"] == "FAIL" and "counterexample" in ref["evidence"]


def test_inline_expect_json(ex, tmp_path):
    out = tmp_path / "i.html"
    code = main(["check", ex("bell_correct.py"), "--expect", '{"01": 1.0}', "--report", str(out), "-q"])
    assert code == 1


def test_bad_file_exit_code(tmp_path):
    assert main(["check", str(tmp_path / "nope.py"), "-q"]) == 3
