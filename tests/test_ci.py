"""`veriq ci`, the .veriq.yml format, the PR markdown, changed-only selection, and the composite action."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from veriq import ci
from veriq.cli import main
from veriq.models import Status

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


def _cfg(tmp_path, body: str, name=".veriq.yml") -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


@pytest.fixture
def repo(tmp_path):
    """A tiny project: one correct + one buggy QFT, Bell with a distribution, a shared helper."""
    for f in ("qft_correct.py", "qft_buggy.py", "qft_reference.py", "bell_correct.py"):
        (tmp_path / f).write_text((EX / f).read_text())
    (tmp_path / "bell.json").write_text((EX / "expect" / "bell.json").read_text())
    (tmp_path / "helper.py").write_text("# shared helper\n")
    return tmp_path


BASIC = """
version: 1
report-dir: out
checks:
  - name: qft_ok
    file: qft_correct.py
    reference: qft_reference.py
  - name: qft_bug
    file: qft_buggy.py
    reference: qft_reference.py
    expect: fail
  - name: bell
    file: bell_correct.py
    distribution: bell.json
    watch: [helper.py]
"""


# ----------------------------------------------------------------------------- config parsing

def test_parse_basic(repo):
    cfg = ci.load_config(_cfg(repo, BASIC))
    assert [e.name for e in cfg.entries] == ["qft_ok", "qft_bug", "bell"]
    assert cfg.entries[1].expect == Status.FAIL
    assert cfg.entries[2].paths() == ["bell_correct.py", "helper.py", "bell.json"]
    assert cfg.report_dir == "out" and cfg.changed_only is False


def test_defaults_and_name_from_stem(repo):
    cfg = ci.load_config(_cfg(repo, "defaults: {shots: 128, seed: 3, mode: state}\nchecks:\n  - file: bell_correct.py\n"))
    e = cfg.entries[0]
    assert (e.name, e.shots, e.seed, e.mode) == ("bell_correct", 128, 3, "state")


def test_allowed_gates_string_and_coupling_list(repo):
    cfg = ci.load_config(_cfg(repo, "checks:\n  - file: bell_correct.py\n    allowed-gates: 'h, cx'\n"
                                    "    coupling: [[0, 1]]\n    no-black-boxes: true\n"))
    e = cfg.entries[0]
    assert e.allowed_gates == ["h", "cx"] and e.coupling == [[0, 1]] and e.no_black_boxes


@pytest.mark.parametrize("body, msg", [
    ("", "config is empty"),
    ("- a\n", "top level must be a mapping"),
    ("checks: []\n", "non-empty list"),
    ("version: 2\nchecks: [{file: bell_correct.py}]\n", "unsupported version"),
    ("chekcs: []\n", "did you mean 'checks'"),
    ("checks:\n  - file: bell_correct.py\n    refrence: x.py\n", "did you mean 'reference'"),
    ("checks:\n  - name: x\n", "missing required key 'file'"),
    ("checks:\n  - file: nope.py\n", "file 'nope.py' not found"),
    ("checks:\n  - file: bell_correct.py\n    reference: nope.py\n", "reference 'nope.py' not found"),
    ("checks:\n  - file: bell_correct.py\n    distribution: nope.json\n", "distribution 'nope.json' not found"),
    ("checks:\n  - file: bell_correct.py\n    expect: maybe\n", "'expect' must be one of"),
    ("checks:\n  - file: bell_correct.py\n    mode: density\n", "'mode' must be"),
    ("checks:\n  - file: bell_correct.py\n    shots: many\n", "'shots' must be int"),
    ("checks:\n  - file: bell_correct.py\n    shots: 0\n", "'shots' must be positive"),
    ("checks:\n  - file: bell_correct.py\n    no-black-boxes: yes please\n", "'no-black-boxes' must be bool"),
    ("checks:\n  - file: bell_correct.py\n  - file: bell_correct.py\n", "duplicate check names"),
    ("changed-only: sometimes\nchecks: [{file: bell_correct.py}]\n", "'changed-only' must be true or false"),
    ("defaults: {file: x.py}\nchecks: [{file: bell_correct.py}]\n", "defaults: unknown key 'file'"),
    ("checks: [{file: bell_correct.py}]\nrun-all-on: 3\n", "'run-all-on' must be"),
    ("checks: [\n", "invalid YAML"),
])
def test_invalid_config_messages(repo, body, msg):
    with pytest.raises(ci.ConfigError, match=msg.replace("(", r"\(").replace("[", r"\[")):
        ci.load_config(_cfg(repo, body))


def test_invalid_config_exit_3_with_summary(repo, capsys):
    p = _cfg(repo, "checks:\n  - file: bell_correct.py\n    shotz: 10\n")
    md, go = repo / "s.md", repo / "go"
    assert main(["ci", "-c", str(p), "--markdown", str(md), "--github-output", str(go)]) == 3
    assert "did you mean 'shots'" in capsys.readouterr().err
    assert ci.MARKER in md.read_text() and "Config error" in md.read_text()
    assert "exit-code=3" in go.read_text()


def test_missing_config_exit_3(tmp_path):
    assert main(["ci", "-c", str(tmp_path / "absent.yml"), "-q"]) == 3


# ----------------------------------------------------------------------------- the ci subcommand

def test_ci_end_to_end(repo):
    p = _cfg(repo, BASIC)
    md, js, go = repo / "s.md", repo / "s.json", repo / "go"
    code = main(["ci", "-c", str(p), "-q", "--markdown", str(md), "--json", str(js), "--github-output", str(go)])
    assert code == 0
    data = json.loads(js.read_text())
    assert [(r["name"], r["verdict"], r["ok"]) for r in data["results"]] == [
        ("qft_ok", "PASS", True), ("qft_bug", "FAIL", True), ("bell", "PASS", True)]
    assert data["results"][1]["report"]["verdict"] == "FAIL"
    outs = dict(l.split("=", 1) for l in go.read_text().splitlines())
    assert outs["exit-code"] == "0" and outs["ran"] == "3" and outs["unexpected"] == "0"
    assert Path(outs["report-dir"]) == (repo / "out").resolve()
    assert {f.name for f in (repo / "out").iterdir()} >= {"qft_ok.html", "qft_bug.html", "bell.json"}


def test_unexpected_fail_exit_1(repo):
    p = _cfg(repo, BASIC.replace("    expect: fail\n", ""))
    md = repo / "s.md"
    assert main(["ci", "-c", str(p), "-q", "--markdown", str(md)]) == 1
    text = md.read_text()
    assert "❌ **Veriq: 1 of 3 checks did not give the expected verdict.**" in text
    assert "| `qft_bug` | ❌ FAIL ⟵ | PASS |" in text and "expected PASS" in text


def test_expected_fail_that_passes_is_exit_1(repo):
    p = _cfg(repo, BASIC.replace("    file: qft_buggy.py", "    file: qft_correct.py"))
    assert main(["ci", "-c", str(p), "-q"]) == 1


def test_candidate_that_does_not_build_is_a_fail(repo):
    """A crashing candidate is a FAIL verdict (the Build check), like `veriq check`; not an input error."""
    (repo / "broken.py").write_text("raise RuntimeError('boom')\n")
    p = _cfg(repo, "checks:\n  - file: broken.py\n")
    md = repo / "s.md"
    assert main(["ci", "-c", str(p), "-q", "--markdown", str(md)]) == 1
    assert "Build failed" in md.read_text()


def test_run_entry_input_error_is_exit_3(repo, monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad distribution")
    monkeypatch.setattr(ci, "run_checks", boom)
    cfg = ci.load_config(_cfg(repo, "checks:\n  - file: bell_correct.py\n"))
    o = ci.run_entry(cfg.entries[0], cfg.root)
    assert o.error == "bad distribution" and ci.exit_code([o]) == 3
    assert "error: bad distribution" in ci.render_markdown([o])


# ----------------------------------------------------------------------------- exit codes / expect

def _o(verdict, expect="pass", error=None):
    e = ci.Entry(name="x", file="x.py", expect=ci.VERDICTS[expect])
    return ci.Outcome(e, None, verdict, error is None and verdict == ci.VERDICTS[expect].value, error)


@pytest.mark.parametrize("outs, fail_on, code", [
    ([("PASS", "pass")], "fail", 0),
    ([("FAIL", "fail")], "fail", 0),
    ([("INCONCLUSIVE", "inconclusive")], "inconclusive", 0),
    ([("FAIL", "pass")], "fail", 1),
    ([("PASS", "fail")], "fail", 1),
    ([("INCONCLUSIVE", "pass")], "fail", 0),
    ([("INCONCLUSIVE", "pass")], "inconclusive", 2),
    ([("INCONCLUSIVE", "pass"), ("FAIL", "pass")], "inconclusive", 1),
    ([("FAIL", "pass"), ("INCONCLUSIVE", "pass")], "inconclusive", 1),
])
def test_exit_code_matrix(outs, fail_on, code):
    assert ci.exit_code([_o(v, e) for v, e in outs], fail_on) == code


def test_error_beats_everything():
    assert ci.exit_code([_o("FAIL", "pass"), _o("ERROR", error="boom")], "fail") == 3


def test_inconclusive_warning_headline():
    md = ci.render_markdown([_o("PASS"), _o("INCONCLUSIVE")], fail_on="fail")
    assert "⚠️ **Veriq: 1 of 2 checks inconclusive (not failing the build).**" in md


# ----------------------------------------------------------------------------- markdown

def test_markdown_sample_from_dogfood_config():
    """The repo's own .veriq.yml: every example gives its expected verdict, with the hazard note."""
    cfg = ci.load_config(ROOT / ".veriq.yml")
    by = {e.name: e for e in cfg.entries}
    picks = ["hazard_block", "hazard_compiled", "hazard_safe", "ghz_buggy"]
    outs = [ci.run_entry(by[n], cfg.root) for n in picks]
    assert all(o.ok for o in outs), [(o.entry.name, o.verdict) for o in outs]
    md = ci.render_markdown(outs, artifact_hint="veriq-reports", versions=outs[0].report.versions)
    lines = md.splitlines()
    assert lines[0] == ci.MARKER and lines[1] == "## Veriq"
    assert "| Check | Verdict | Expected | CX as written → compiled¹ | Notes |" in md
    assert "| `hazard_block` | ✅ PASS | PASS ✓ |" in md and "zero_init_hazard |" in md
    assert "| `hazard_compiled` | ❌ FAIL | FAIL ✓ | 12 → " in md
    assert r"counterexample \|10100>" in md          # pipe escaped inside the table
    assert "> **zero_init_hazard**" in md
    assert "workflow artifact `veriq-reports`" in md and "qiskit 2.6.1" in md
    assert "</sub><br>\n<sub>" in md                  # footer lines don't collapse into one paragraph


def test_markdown_no_checks_affected():
    md = ci.render_markdown([], skipped=[ci.Entry(name="a", file="a.py")], why="1 changed file(s)")
    assert "no checks affected" in md and "skipped: `a`" in md


# ----------------------------------------------------------------------------- changed-only

def test_select_entries(repo):
    cfg = ci.load_config(_cfg(repo, BASIC + "run-all-on: ['lib/**', pyproject.toml]\n"))
    names = lambda es: [e.name for e in es]
    run, skipped, why = ci.select_entries(cfg, ["qft_reference.py"])
    assert names(run) == ["qft_ok", "qft_bug"] and names(skipped) == ["bell"] and "2 of 3" in why
    assert names(ci.select_entries(cfg, ["./helper.py"])[0]) == ["bell"]           # watch + normpath
    assert names(ci.select_entries(cfg, ["bell.json"])[0]) == ["bell"]             # distribution file
    assert ci.select_entries(cfg, ["README.md"])[0] == []
    assert len(ci.select_entries(cfg, [".veriq.yml"])[0]) == 3                     # config changed
    assert len(ci.select_entries(cfg, ["lib/a/b.py"])[0]) == 3                     # run-all-on glob
    assert len(ci.select_entries(cfg, None)[0]) == 3                               # git unknown


def test_watch_glob(repo):
    cfg = ci.load_config(_cfg(repo, "checks:\n  - file: bell_correct.py\n    watch: ['lib/*.py']\n"))
    assert ci.select_entries(cfg, ["lib/x.py"])[0] and not ci.select_entries(cfg, ["other/x.py"])[0]


def test_changed_only_cli_with_file(repo):
    p = _cfg(repo, BASIC)
    ch = repo / "changed.txt"
    ch.write_text("helper.py\nREADME.md\n")
    js, md = repo / "s.json", repo / "s.md"
    assert main(["ci", "-c", str(p), "-q", "--changed-only", "--changed-files", str(ch),
                 "--json", str(js), "--markdown", str(md)]) == 0
    data = json.loads(js.read_text())
    assert [r["name"] for r in data["results"]] == ["bell"] and data["skipped"] == ["qft_ok", "qft_bug"]
    assert "Not affected, skipped: `qft_ok`, `qft_bug`" in md.read_text()


def test_all_overrides_config_changed_only(repo):
    p = _cfg(repo, "changed-only: true\n" + BASIC)
    ch = repo / "changed.txt"
    ch.write_text("README.md\n")
    js = repo / "s.json"
    main(["ci", "-c", str(p), "-q", "--all", "--changed-files", str(ch), "--json", str(js)])
    assert len(json.loads(js.read_text())["results"]) == 3


def test_changed_files_from_git(repo):
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    g("init", "-q", "-b", "main")
    g("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    g("checkout", "-qb", "feature")
    (repo / "helper.py").write_text("# changed\n")
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "change")
    assert ci.changed_files("main", repo) == ["helper.py"]
    assert ci.changed_files("no-such-ref", repo) is None
    p = _cfg(repo, BASIC)
    js = repo / "s.json"
    assert main(["ci", "-c", str(p), "-q", "--changed-only", "--base", "main", "--json", str(js)]) == 0
    assert [r["name"] for r in json.loads(js.read_text())["results"]] == ["bell"]


# ----------------------------------------------------------------------------- action + workflows

def test_action_yml_shape():
    a = yaml.safe_load((ROOT / "action.yml").read_text())
    assert a["runs"]["using"] == "composite"
    assert {"config", "python-version", "fail-on", "comment", "qiskit-version"} <= set(a["inputs"])
    assert a["inputs"]["config"]["default"] == ".veriq.yml"
    uses = [s.get("uses", "") for s in a["runs"]["steps"]]
    assert "actions/upload-artifact@v4" in uses and "actions/github-script@v7" in uses
    for s in a["runs"]["steps"]:
        if "run" in s:
            assert s["shell"] == "bash"
            assert "${{ inputs." not in s["run"], f"step {s['name']!r}: pass inputs via env (injection)"
    script = next(s for s in a["runs"]["steps"] if s.get("uses") == "actions/github-script@v7")["with"]["script"]
    assert ci.MARKER in script and "updateComment" in script and "createComment" in script


def test_dogfood_workflows():
    w = yaml.safe_load((ROOT / ".github/workflows/veriq.yml").read_text())
    on = w[True] if True in w else w["on"]          # YAML 1.1 reads `on:` as True
    assert "pull_request" in on and on["push"]["branches"] == ["main"]
    steps = w["jobs"]["veriq"]["steps"]
    assert steps[0]["with"]["fetch-depth"] == 0 and steps[1]["uses"] == "./"
    assert w["permissions"]["pull-requests"] == "write"
    t = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    assert any("pytest" in s.get("run", "") for s in t["jobs"]["pytest"]["steps"])


def _simulate(tmp_path, *args):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/simulate_action.py"), "--tmp", str(tmp_path), *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, json.loads(r.stdout)


def test_simulated_action_run(tmp_path):
    code, d = _simulate(tmp_path / "sim")
    assert code == 0 and d["final_exit_code"] == 0
    assert d["outputs"]["exit-code"] == "0" and d["outputs"]["unexpected"] == "0"
    summary = Path(d["step_summary"]).read_text()
    assert summary.startswith(ci.MARKER) and "| `hazard_compiled` | ❌ FAIL | FAIL ✓ |" in summary
    up = next(s for s in d["steps"] if s.get("uses") == "actions/upload-artifact@v4")
    assert "hazard_compiled.html" in up["artifact_files"]
    cm = next(s for s in d["steps"] if s.get("uses") == "actions/github-script@v7")
    assert cm["would_run"] and Path(cm["comment_body"]).read_text() == summary


def test_simulated_action_config_error(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("checks:\n  - file: examples/bell_correct.py\n    expct: fail\n")
    code, d = _simulate(tmp_path / "sim", "--input", f"config={bad}", "--event", "push")
    assert code == 3 and d["outputs"]["exit-code"] == "3"
    assert "Config error" in Path(d["step_summary"]).read_text()
    cm = next(s for s in d["steps"] if s.get("uses") == "actions/github-script@v7")
    assert not cm["would_run"]                                                     # push event: no comment
