"""`veriq ci`: run every entry of a `.veriq.yml` config and produce JSON + Markdown summaries.

Config format (all paths are relative to the config file's directory):

    version: 1                 # optional, only 1 is supported
    changed-only: false        # only run entries whose files changed vs the PR base
    report-dir: veriq-reports  # HTML/JSON reports, one per entry
    defaults:                  # optional, applied to every entry
      shots: 4096
    checks:
      - name: qft_buggy                  # optional, defaults to the file stem
        file: examples/qft_buggy.py      # required
        function: build                  # builder in a multi-function .py
        reference: examples/qft_reference.py
        reference-function: build
        mode: unitary                    # unitary | state
        distribution: examples/expect/bell.json   # expected distribution (inline JSON or path)
        allowed-gates: [h, cx]           # list or "h,cx"
        coupling: linear                 # linear | ring | "0-1,1-2"
        no-black-boxes: true
        backend: generic
        shots: 4096
        seed: 7
        timeout: 30
        expect: fail                     # expected verdict: pass (default) | fail | inconclusive
        watch: [examples/_grover.py]     # extra files that trigger this entry under changed-only
        preflight: fake_torino           # hardware gate (veriq preflight); or a mapping:
        # preflight: {backend: fake_torino, min-esp: 0.2, warn-esp: 0.5, max-cx: 60, max-duration: 2e-4,
        #             seeds: 4, levels: [1, 3], noisy-sim: false, max-tvd: 0.3}
        # go -> PASS, warn -> INCONCLUSIVE, no-go -> FAIL, merged into the entry's verdict

Exit code: 0 every entry matched its expectation, 1 an entry FAILed unexpectedly (or an `expect: fail`
entry did not fail), 2 an entry was INCONCLUSIVE unexpectedly and `--fail-on inconclusive`,
3 config/input error.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .loader import LoadError
from .models import CheckResult, Report, Status, overall_verdict
from .report import render_html, render_json
from .runner import run_checks

MARKER = "<!-- veriq-ci-comment -->"
VERDICTS = {"pass": Status.PASS, "fail": Status.FAIL, "inconclusive": Status.INCONCLUSIVE}
ENTRY_KEYS = {
    "name", "file", "function", "reference", "reference-function", "mode", "distribution",
    "allowed-gates", "coupling", "no-black-boxes", "backend", "shots", "seed", "timeout", "expect", "watch",
    "preflight",
}
PREFLIGHT_KEYS = {"backend", "min-esp", "warn-esp", "max-cx", "max-duration", "warn-t2-fraction", "seeds", "levels",
                  "noisy-sim", "max-tvd", "shots", "timeout"}
DEFAULT_KEYS = ENTRY_KEYS - {"name", "file", "function", "reference", "reference-function", "watch"}
TOP_KEYS = {"version", "changed-only", "report-dir", "run-all-on", "defaults", "checks"}
ICON = {"PASS": "✅", "FAIL": "❌", "INCONCLUSIVE": "⚠️", "SKIPPED": "⏭️"}


class ConfigError(ValueError):
    """Invalid .veriq.yml. Raised with a message naming the entry and key."""


@dataclass
class Entry:
    name: str
    file: str
    expect: Status = Status.PASS
    function: str | None = None
    reference: str | None = None
    reference_function: str | None = None
    mode: str = "unitary"
    distribution: str | dict | None = None
    allowed_gates: list[str] | None = None
    coupling: str | None = None
    no_black_boxes: bool = False
    backend: str | None = None
    shots: int = 4096
    seed: int = 7
    timeout: float = 30.0
    watch: list[str] = field(default_factory=list)
    preflight: dict[str, Any] | None = None

    def paths(self) -> list[str]:
        out = [self.file] + ([self.reference] if self.reference else []) + list(self.watch)
        b = (self.preflight or {}).get("backend")
        if isinstance(b, str) and b.endswith(".json"):
            out.append(b)
        if isinstance(self.distribution, str) and not self.distribution.lstrip().startswith("{"):
            out.append(self.distribution)
        return [os.path.normpath(p) for p in out]


@dataclass
class Config:
    path: str
    root: str
    entries: list[Entry]
    changed_only: bool = False
    report_dir: str = "veriq-reports"
    run_all_on: list[str] = field(default_factory=list)


def _matches(path: str, patterns: list[str]) -> bool:
    """Exact path or fnmatch glob ('examples/*.py', 'src/**'). '**' matches across directories."""
    import fnmatch

    path = os.path.normpath(path)
    for pat in patterns:
        pat = os.path.normpath(pat)
        if path == pat or fnmatch.fnmatchcase(path, pat) or fnmatch.fnmatchcase(path, pat.replace("**", "*")):
            return True
    return False


def _suggest(key: str, allowed: set[str]) -> str:
    import difflib

    m = difflib.get_close_matches(key, sorted(allowed), n=1)
    return f" (did you mean '{m[0]}'?)" if m else ""


def _check_keys(d: dict, allowed: set[str], where: str) -> None:
    for k in d:
        if k not in allowed:
            raise ConfigError(f"{where}: unknown key '{k}'{_suggest(str(k), allowed)}. "
                              f"Allowed: {', '.join(sorted(allowed))}")


def _typed(where: str, key: str, value: Any, typ: type | tuple) -> Any:
    if isinstance(value, bool) and typ in (int, float, (int, float)):
        raise ConfigError(f"{where}: '{key}' must be a number, got {value!r}")
    if not isinstance(value, typ):
        names = typ.__name__ if isinstance(typ, type) else " or ".join(t.__name__ for t in typ)
        raise ConfigError(f"{where}: '{key}' must be {names}, got {type(value).__name__} {value!r}")
    return value


def _parse_entry(raw: Any, i: int, defaults: dict, root: Path, check_files: bool) -> Entry:
    where = f"checks[{i}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: each check must be a mapping with at least 'file', got {raw!r}")
    _check_keys(raw, ENTRY_KEYS, where)
    d = {**defaults, **raw}
    if "file" not in d or not d["file"]:
        raise ConfigError(f"{where}: missing required key 'file'")
    file = _typed(where, "file", d["file"], str)
    name = str(d.get("name") or Path(file).stem)
    where = f"checks[{i}] ({name})"
    exp = str(d.get("expect", "pass")).lower()
    if exp not in VERDICTS:
        raise ConfigError(f"{where}: 'expect' must be one of pass, fail, inconclusive, got {d['expect']!r}")
    mode = d.get("mode", "unitary")
    if mode not in ("unitary", "state"):
        raise ConfigError(f"{where}: 'mode' must be 'unitary' or 'state', got {mode!r}")
    gates = d.get("allowed-gates")
    if gates is not None:
        if isinstance(gates, str):
            gates = [g.strip() for g in gates.split(",") if g.strip()]
        elif not (isinstance(gates, list) and all(isinstance(g, str) for g in gates)):
            raise ConfigError(f"{where}: 'allowed-gates' must be a list of gate names or 'h,cx,...'")
        if not gates:
            raise ConfigError(f"{where}: 'allowed-gates' is empty")
    watch = d.get("watch") or []
    if isinstance(watch, str):
        watch = [watch]
    if not (isinstance(watch, list) and all(isinstance(w, str) for w in watch)):
        raise ConfigError(f"{where}: 'watch' must be a list of paths")
    dist = d.get("distribution")
    if dist is not None and not isinstance(dist, (str, dict)):
        raise ConfigError(f"{where}: 'distribution' must be a JSON path, inline JSON or a mapping")
    if isinstance(dist, dict):
        dist = {str(k): v for k, v in dist.items()}
    for key in ("function", "reference", "reference-function", "coupling", "backend"):
        if d.get(key) is not None:
            if key == "coupling" and isinstance(d[key], list):
                continue
            _typed(where, key, d[key], str)
    e = Entry(
        name=name, file=file, expect=VERDICTS[exp], function=d.get("function"),
        reference=d.get("reference"), reference_function=d.get("reference-function"), mode=mode,
        distribution=dist, allowed_gates=gates, coupling=d.get("coupling"),
        no_black_boxes=bool(_typed(where, "no-black-boxes", d.get("no-black-boxes", False), bool)),
        backend=d.get("backend"),
        shots=int(_typed(where, "shots", d.get("shots", 4096), int)),
        seed=int(_typed(where, "seed", d.get("seed", 7), int)),
        timeout=float(_typed(where, "timeout", d.get("timeout", 30.0), (int, float))), watch=watch,
    )
    if e.shots <= 0:
        raise ConfigError(f"{where}: 'shots' must be positive")
    e.preflight = _parse_preflight(d.get("preflight"), where)
    if check_files:
        for key, p in (("file", e.file), ("reference", e.reference),
                       ("distribution", e.distribution if isinstance(e.distribution, str)
                        and not e.distribution.lstrip().startswith("{") else None)):
            if p and not (root / p).is_file():
                raise ConfigError(f"{where}: {key} '{p}' not found (paths are relative to {root})")
    return e


def _parse_preflight(raw: Any, where: str) -> dict[str, Any] | None:
    if raw is None or raw is False:
        return None
    if isinstance(raw, str):
        raw = {"backend": raw}
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: 'preflight' must be a backend name / profile path or a mapping")
    _check_keys(raw, PREFLIGHT_KEYS, f"{where}: preflight")
    if not isinstance(raw.get("backend"), str) or not raw["backend"]:
        raise ConfigError(f"{where}: preflight needs 'backend' (e.g. fake_torino or profiles/device.json)")
    out: dict[str, Any] = {"backend": raw["backend"]}
    for k, typ in (("min-esp", (int, float)), ("warn-esp", (int, float)), ("max-duration", (int, float)),
                   ("warn-t2-fraction", (int, float)), ("max-tvd", (int, float)), ("timeout", (int, float)),
                   ("max-cx", int), ("seeds", int), ("shots", int)):
        if raw.get(k) is not None:
            out[k] = _typed(where, f"preflight.{k}", raw[k], typ)
    if raw.get("noisy-sim") is not None:
        out["noisy-sim"] = bool(_typed(where, "preflight.noisy-sim", raw["noisy-sim"], bool))
    lv = raw.get("levels")
    if lv is not None:
        if isinstance(lv, int) and not isinstance(lv, bool):
            lv = [lv]
        if not (isinstance(lv, list) and lv and all(isinstance(x, int) and 0 <= x <= 3 for x in lv)):
            raise ConfigError(f"{where}: preflight.levels must be a list of optimisation levels 0-3")
        out["levels"] = lv
    return out


def run_preflight(e: Entry, root: str, qc) -> tuple[CheckResult, dict[str, Any]]:
    from .preflight import PreflightError, preflight, to_json

    pf = e.preflight or {}
    b = pf["backend"]
    if b.endswith(".json"):
        b = _abs(root, b)
    try:
        res = preflight(qc, b, seeds=pf.get("seeds", 4), levels=tuple(pf.get("levels", (1, 3))),
                        min_esp=pf.get("min-esp"), warn_esp=pf.get("warn-esp"), max_cx=pf.get("max-cx"),
                        max_duration=pf.get("max-duration"), warn_t2_fraction=pf.get("warn-t2-fraction"),
                        noisy_sim=pf.get("noisy-sim", False), max_tvd=pf.get("max-tvd"),
                        shots=pf.get("shots", 4000), timeout=pf.get("timeout", e.timeout), keep_circuits=False)
    except PreflightError as exc:
        raise ValueError(f"preflight: {exc}") from None
    est = res.get("estimate") or {}
    bad = [f"{c['name']}: {c['status']}" for c in res["checks"] if c["status"] not in ("PASS", "SKIPPED")]
    summ = (f"{res['gate'].upper()} on {res['backend']['name']}: ESP {est.get('esp', 0):.3g} (estimate), "
            f"{est.get('two_qubit_gates')} 2q gates, {est.get('duration_s', 0) * 1e6:.3g} us"
            if est else f"{res['gate'].upper()} on {res['backend']['name']}")
    if bad:
        summ += "; " + "; ".join(bad)
    st = {"PASS": Status.PASS, "FAIL": Status.FAIL}.get(res["verdict"], Status.INCONCLUSIVE)
    j = to_json(res)
    return CheckResult("Hardware preflight", st, summ, {"preflight": j}, res["seconds"]), j


def parse_config(data: Any, path: str = ".veriq.yml", root: str | Path = ".", check_files: bool = True) -> Config:
    if data is None:
        raise ConfigError(f"{path}: config is empty")
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping with a 'checks' list")
    _check_keys(data, TOP_KEYS, path)
    if data.get("version", 1) != 1:
        raise ConfigError(f"{path}: unsupported version {data['version']!r} (only 1)")
    checks_raw = data.get("checks")
    if not isinstance(checks_raw, list) or not checks_raw:
        raise ConfigError(f"{path}: 'checks' must be a non-empty list")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"{path}: 'defaults' must be a mapping")
    _check_keys(defaults, DEFAULT_KEYS, f"{path}: defaults")
    root = Path(root)
    entries = [_parse_entry(raw, i, defaults, root, check_files) for i, raw in enumerate(checks_raw)]
    names = [e.name for e in entries]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ConfigError(f"{path}: duplicate check names {dup}; set a unique 'name' on each")
    co = data.get("changed-only", False)
    if not isinstance(co, bool):
        raise ConfigError(f"{path}: 'changed-only' must be true or false")
    rd = data.get("report-dir", "veriq-reports")
    if not isinstance(rd, str):
        raise ConfigError(f"{path}: 'report-dir' must be a path")
    rao = data.get("run-all-on") or []
    if isinstance(rao, str):
        rao = [rao]
    if not (isinstance(rao, list) and all(isinstance(x, str) for x in rao)):
        raise ConfigError(f"{path}: 'run-all-on' must be a list of paths or globs")
    return Config(path=str(path), root=str(root), entries=entries, changed_only=co, report_dir=rd,
                  run_all_on=rao)


def load_config(path: str | Path) -> Config:
    import yaml

    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config file '{p}' not found")
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{p}: invalid YAML: {exc}") from exc
    return parse_config(data, str(p), p.parent)


# --------------------------------------------------------------------------- changed-only


def changed_files(base: str, root: str | Path = ".") -> list[str] | None:
    """Files changed between `base` and HEAD (merge-base diff). None if git cannot tell."""
    try:
        out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return [os.path.normpath(line) for line in out.stdout.splitlines() if line.strip()]


def select_entries(cfg: Config, changed: list[str] | None) -> tuple[list[Entry], list[Entry], str]:
    """Return (run, skipped, why). Runs everything when changed is None, the config changed, or a run-all-on match."""
    if changed is None:
        return cfg.entries, [], "could not determine changed files; running all checks"
    ch = {os.path.normpath(c) for c in changed}
    cfg_rel = os.path.normpath(os.path.relpath(cfg.path, cfg.root))
    if cfg_rel in ch:
        return cfg.entries, [], f"{cfg_rel} changed; running all checks"
    hit = sorted(c for c in ch if _matches(c, cfg.run_all_on))
    if hit:
        return cfg.entries, [], f"{hit[0]} matches run-all-on; running all checks"
    run = [e for e in cfg.entries if any(_matches(c, e.paths()) for c in ch)]
    skipped = [e for e in cfg.entries if e not in run]
    return run, skipped, f"{len(ch)} changed file(s); {len(run)} of {len(cfg.entries)} checks affected"


# --------------------------------------------------------------------------- run + summarise


@dataclass
class Outcome:
    entry: Entry
    report: Report | None
    verdict: str
    ok: bool
    error: str | None = None
    started: str | None = None  # UTC ISO timestamp (for certificates)

    def notes(self) -> list[str]:
        out: list[str] = []
        if self.error:
            return [f"error: {self.error}"]
        r = self.report
        for c in (r.checks if r else []):
            if c.name == "Transpile integrity" and c.evidence.get("zero_init_hazard"):
                out.append("zero_init_hazard")
            if c.status == Status.FAIL:
                cex = (c.evidence or {}).get("counterexample")
                out.append(f"{c.name}: counterexample {cex['input_state']}" if cex else
                           (f"preflight {c.summary}" if c.name == "Hardware preflight" else f"{c.name} failed"))
            elif c.status == Status.INCONCLUSIVE and c.name == "Hardware preflight":
                out.append(f"preflight {c.summary}")
            elif c.status == Status.INCONCLUSIVE:
                out.append(f"{c.name} inconclusive")
            elif c.name == "Hardware preflight" and c.status == Status.PASS:
                out.append(f"preflight {c.summary}")
        if not self.ok:
            out.append(f"expected {self.entry.expect.value}")
        return out

    def cx(self) -> tuple[int | None, int | None]:
        if not self.report or not self.report.metrics:
            return None, None
        m = self.report.metrics
        src = m.get("source", {}).get("gate_counts", {}).get("cx", 0)
        comp = next(iter(m.get("compiled", {}).values()), None)
        return src, (comp or {}).get("gate_counts", {}).get("cx", 0) if comp else None


def _abs(root: str, p: str | None) -> str | None:
    if p is None:
        return None
    return p if os.path.isabs(p) else str(Path(root) / p)


def run_entry(e: Entry, root: str) -> Outcome:
    from .certificate import utc_now

    started = utc_now()
    dist = e.distribution
    if isinstance(dist, str) and not dist.lstrip().startswith("{"):
        dist = _abs(root, dist)
    try:
        rep = run_checks(_abs(root, e.file), reference=_abs(root, e.reference), expect=dist, backend=e.backend,
                         shots=e.shots, seed=e.seed, timeout=e.timeout, mode=e.mode,
                         allowed_gates=e.allowed_gates, function=e.function,
                         reference_function=e.reference_function, coupling=e.coupling,
                         no_black_boxes=e.no_black_boxes)
    except (LoadError, ValueError, OSError) as exc:
        return Outcome(e, None, "ERROR", False, str(exc))
    if e.preflight:
        qc = (rep.circuits or {}).get("candidate")
        if qc is None:
            pc = CheckResult("Hardware preflight", Status.SKIPPED, "candidate did not build: no preflight")
        else:
            try:
                pc, _ = run_preflight(e, root, qc)
            except (ValueError, OSError) as exc:
                return Outcome(e, None, "ERROR", False, str(exc))
        rep.checks.append(pc)
        rep.verdict = overall_verdict(rep.checks)
    rep.target = e.file + (f"::{e.function}" if e.function else "")
    rep.reference = e.reference
    return Outcome(e, rep, rep.verdict.value, rep.verdict == e.expect, started=started)


def entry_certificate(o: Outcome, root: str) -> dict:
    """Certificate for one CI entry (paths recorded relative to the repo root, as in the config)."""
    from .certificate import certificate_from_report

    e = o.entry
    dist = e.distribution
    expect = dist if isinstance(dist, dict) else None
    if isinstance(dist, str):
        try:
            from .runner import parse_expect

            expect = parse_expect(dist if dist.lstrip().startswith("{") else _abs(root, dist))
        except Exception:  # noqa: BLE001
            expect = None
    opts = {"mode": e.mode, "allowed_gates": e.allowed_gates, "coupling": e.coupling,
            "no_black_boxes": e.no_black_boxes, "backend": e.backend, "shots": e.shots, "seed": e.seed,
            "timeout": e.timeout, "expect": expect}
    cert = certificate_from_report(o.report, kind="ci", candidate_path=_abs(root, e.file),
                                   reference_path=_abs(root, e.reference), function=e.function,
                                   reference_function=e.reference_function, options=opts,
                                   started=o.started)
    pcheck = next((c for c in (o.report.checks if o.report else []) if c.name == "Hardware preflight"), None)
    if pcheck is not None and pcheck.evidence.get("preflight"):
        pj = pcheck.evidence["preflight"]
        est = pj.get("estimate") or {}
        cert["preflight"] = {"gate": pj.get("gate"), "backend": pj.get("backend"), "chosen": pj.get("chosen"),
                             "esp": est.get("esp"), "two_qubit_gates": est.get("two_qubit_gates"),
                             "duration_s": est.get("duration_s"), "proof": pj.get("proof"),
                             "thresholds": pj.get("thresholds"),
                             "note": "ESP / duration are estimates from a calibration snapshot"}
    for rec in cert["inputs"]:  # portable paths: relative to the config root
        rel = {"candidate": e.file, "reference": e.reference}.get(rec["role"])
        if rel:
            rec["path"] = rel
    cert["ci"] = {"entry": e.name, "expect": e.expect.value, "as_expected": o.ok,
                  **{k: os.environ[v] for k, v in (("repository", "GITHUB_REPOSITORY"), ("sha", "GITHUB_SHA"),
                                                    ("ref", "GITHUB_REF"), ("run_id", "GITHUB_RUN_ID"),
                                                    ("workflow", "GITHUB_WORKFLOW")) if os.environ.get(v)}}
    return cert


def exit_code(outcomes: list[Outcome], fail_on: str = "fail") -> int:
    if any(o.error for o in outcomes):
        return 3
    code = 0
    for o in outcomes:
        if o.ok:
            continue
        if o.verdict == "INCONCLUSIVE":
            if fail_on == "inconclusive":
                code = max(code, 2)
        else:  # unexpected FAIL, or an expect:fail/inconclusive entry that came out differently
            code = 1
            break
    return code


def _fmt_cx(src: int | None, comp: int | None) -> str:
    if src is None:
        return "–"
    return f"{src} → {comp}" if comp is not None else str(src)


def render_markdown(outcomes: list[Outcome], skipped: list[Entry] | None = None, why: str = "",
                    fail_on: str = "fail", artifact_hint: str | None = None, versions: dict | None = None) -> str:
    skipped = skipped or []
    code = exit_code(outcomes, fail_on)
    bad = [o for o in outcomes if not o.ok]
    warn = [o for o in bad if o.verdict == "INCONCLUSIVE" and fail_on != "inconclusive"]
    if not outcomes:
        head = "⏭️ **Veriq: no checks affected by this change.**"
    elif code == 0 and not warn:
        head = f"✅ **Veriq: all {len(outcomes)} checks gave the expected verdict.**"
    elif code == 0:
        head = f"⚠️ **Veriq: {len(warn)} of {len(outcomes)} checks inconclusive (not failing the build).**"
    elif code == 3:
        head = "🛑 **Veriq: input error, see notes.**"
    else:
        head = f"❌ **Veriq: {len(bad)} of {len(outcomes)} checks did not give the expected verdict.**"
    lines = [MARKER, "## Veriq", "", head, ""]
    if outcomes:
        lines += ["| Check | Verdict | Expected | CX as written → compiled¹ | Notes |", "|---|---|---|---|---|"]
        for o in outcomes:
            mark = "" if o.ok else " ⟵"
            v = f"{ICON.get(o.verdict, '🛑')} {o.verdict}{mark}"
            exp = o.entry.expect.value + (" ✓" if o.ok else "")
            notes = "; ".join(o.notes()).replace("|", "\\|") or "–"
            lines.append(f"| `{o.entry.name}` | {v} | {exp} | {_fmt_cx(*o.cx())} | {notes} |")
        lines.append("")
    if any("zero_init_hazard" in o.notes() for o in outcomes):
        lines += ["> **zero_init_hazard**: Qiskit's default `transpile()` (`qubits_initially_zero=True`) would "
                  "borrow idle qubits as clean ancillas here, so the default-compiled block is only valid from "
                  "|0…0>. Veriq verified with `qubits_initially_zero=False`.", ""]
    target = next((next(iter(o.report.metrics.get("compiled", {})), None) for o in outcomes
                   if o.report and o.report.metrics.get("compiled")), None)
    if target:
        import re

        target = re.sub(r" \(\d+q\)", "", target).replace(", qubits_initially_zero=False", "")
        lines.append(f"<sub>¹ compiled = Veriq's transpile target: {target}; unitary-mode checks use "
                     "`qubits_initially_zero=False`.</sub>")
    if why:
        lines.append(f"<sub>changed-only: {why}.</sub>")
    if skipped:
        lines.append(f"<sub>Not affected, skipped: {', '.join(f'`{e.name}`' for e in skipped)}.</sub>")
    if artifact_hint:
        lines.append(f"<sub>Full HTML reports: workflow artifact `{artifact_hint}`.</sub>")
    if versions:
        lines.append("<sub>" + " · ".join(f"{k} {v}" for k, v in versions.items()) + "</sub>")
    out = "\n".join(lines).rstrip() + "\n"
    return out.replace("</sub>\n<sub>", "</sub><br>\n<sub>")


def summary_json(outcomes: list[Outcome], skipped: list[Entry], fail_on: str, why: str) -> dict[str, Any]:
    return {
        "exit_code": exit_code(outcomes, fail_on),
        "fail_on": fail_on,
        "changed_only": why or None,
        "results": [
            {"name": o.entry.name, "file": o.entry.file, "verdict": o.verdict, "expected": o.entry.expect.value,
             "ok": o.ok, "cx_source": o.cx()[0], "cx_compiled": o.cx()[1], "notes": o.notes(),
             "report": o.report.to_dict() if o.report else None, "error": o.error}
            for o in outcomes
        ],
        "skipped": [e.name for e in skipped],
    }


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def main(args: Any) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"veriq ci: config error: {exc}", file=sys.stderr)
        if args.markdown:
            Path(args.markdown).write_text(f"{MARKER}\n## Veriq\n\n🛑 **Config error** in `{args.config}`:\n\n"
                                           f"```\n{exc}\n```\n")
        if args.json_out:
            Path(args.json_out).write_text(json.dumps({"exit_code": 3, "config_error": str(exc)}, indent=2))
        if args.github_output:
            with open(args.github_output, "a") as fh:
                fh.write("exit-code=3\nran=0\nunexpected=0\nskipped=0\n")
        return 3
    fail_on = args.fail_on
    changed_only = cfg.changed_only if args.changed_only is None else args.changed_only
    why = ""
    run, skipped = cfg.entries, []
    if changed_only:
        if args.changed_files is not None:
            changed = [l.strip() for l in Path(args.changed_files).read_text().splitlines() if l.strip()]
        else:
            base = args.base or (f"origin/{os.environ['GITHUB_BASE_REF']}" if os.environ.get("GITHUB_BASE_REF")
                                 else None)
            changed = changed_files(base, cfg.root) if base else None
            if base is None:
                why = "no PR base (not a pull_request run); running all checks"
        run, skipped, why2 = select_entries(cfg, changed)
        why = why or why2
    report_dir = Path(args.report_dir or Path(cfg.root) / cfg.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    outcomes: list[Outcome] = []
    cert_dir = None
    want_certs = getattr(args, "certificates", None)
    if want_certs is None and os.environ.get("VERIQ_CERTIFICATES", "").lower() in ("1", "true", "yes"):
        want_certs = ""
    if want_certs is not None:
        cert_dir = Path(want_certs) if want_certs else report_dir / "certificates"
        cert_dir.mkdir(parents=True, exist_ok=True)
    cert_errors = 0
    for e in run:
        o = run_entry(e, cfg.root)
        outcomes.append(o)
        if o.report:
            (report_dir / f"{_safe(e.name)}.html").write_text(render_html(o.report))
            (report_dir / f"{_safe(e.name)}.json").write_text(render_json(o.report))
            if cert_dir is not None:
                from .certificate import CertificateError, write_certificate

                try:
                    write_certificate(entry_certificate(o, cfg.root), cert_dir / f"{_safe(e.name)}.cert.json",
                                      getattr(args, "sign_key", None), sign_env=True)
                except (CertificateError, OSError) as exc:
                    cert_errors += 1
                    print(f"veriq ci: certificate for {e.name}: {exc}", file=sys.stderr)
        if not args.quiet:
            flag = "ok" if o.ok else f"UNEXPECTED (expected {e.expect.value})"
            print(f"  {ICON.get(o.verdict, '🛑')} {o.verdict:<12} {e.name:<24} {flag}"
                  + (f"  {o.error}" if o.error else ""))
    versions = next((o.report.versions for o in outcomes if o.report), None)
    md = render_markdown(outcomes, skipped, why, fail_on, args.artifact_hint, versions)
    data = summary_json(outcomes, skipped, fail_on, why)
    if cert_dir is not None:
        data["certificates"] = {"dir": str(cert_dir), "errors": cert_errors,
                                "signed": bool(getattr(args, "sign_key", None) or os.environ.get("VERIQ_SIGNING_KEY"))}
        if cert_errors and data["exit_code"] == 0:
            data["exit_code"] = 3
    code = data["exit_code"]
    if args.markdown:
        Path(args.markdown).write_text(md)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(data, indent=2, default=str))
    if args.github_output:
        with open(args.github_output, "a") as fh:
            fh.write(f"exit-code={code}\n")
            fh.write(f"ran={len(outcomes)}\n")
            fh.write(f"unexpected={sum(1 for o in outcomes if not o.ok)}\n")
            fh.write(f"skipped={len(skipped)}\n")
            fh.write(f"report-dir={report_dir.resolve()}\n")
            if cert_dir is not None:
                fh.write(f"certificate-dir={cert_dir.resolve()}\n")
    if not args.quiet:
        print(f"veriq ci: {len(outcomes)} run, {len(skipped)} skipped, "
              f"{sum(1 for o in outcomes if not o.ok)} unexpected -> exit {code}")
    return code
