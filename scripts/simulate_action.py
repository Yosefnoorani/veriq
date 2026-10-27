#!/usr/bin/env python3
"""Run action.yml's bash steps locally, the way a GitHub runner would (no docker / act needed).

It parses action.yml, substitutes ${{ inputs.* }} with defaults or --input overrides, sets GITHUB_OUTPUT,
GITHUB_STEP_SUMMARY, RUNNER_TEMP and GITHUB_ACTION_PATH to temp paths, and executes every `shell: bash`
step in order. `uses:` steps (setup-python, upload-artifact, github-script) are not executed: the upload
step's resolved path is checked instead, and the sticky-comment body is written to a file.
The install step is skipped by default (the current interpreter already has veriq); pass --install to run it.

  python scripts/simulate_action.py [--input fail-on=inconclusive] [--event pull_request] [--workdir DIR]
Prints a JSON summary; exit code = the action's final exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXPR = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def parse_outputs(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v  # last write wins, like GitHub
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", action="append", default=[], help="name=value")
    ap.add_argument("--event", default="pull_request")
    ap.add_argument("--workdir", default=str(ROOT))
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--tmp", default=None)
    a = ap.parse_args(argv)

    action = yaml.safe_load((ROOT / "action.yml").read_text())
    inputs = {k: str(v.get("default", "")) for k, v in action["inputs"].items()}
    for kv in a.input:
        k, v = kv.split("=", 1)
        if k not in inputs:
            ap.error(f"unknown input {k!r}")
        inputs[k] = v
    inputs["github-token"] = "SIMULATED"

    tmp = Path(a.tmp or tempfile.mkdtemp(prefix="veriq-action-"))
    tmp.mkdir(parents=True, exist_ok=True)
    gh_out, summary = tmp / "github_output", tmp / "step_summary.md"
    gh_out.write_text("")
    summary.write_text("")
    env = dict(os.environ, GITHUB_OUTPUT=str(gh_out), GITHUB_STEP_SUMMARY=str(summary), RUNNER_TEMP=str(tmp),
               GITHUB_ACTION_PATH=str(ROOT), GITHUB_EVENT_NAME=a.event)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    steps_out: dict[str, dict[str, str]] = {}

    def resolve(expr: str) -> str:
        expr = expr.strip()
        if expr.startswith("inputs."):
            return inputs[expr[len("inputs."):]]
        m = re.fullmatch(r"steps\.([\w-]+)\.outputs\.([\w-]+)", expr)
        if m:
            return steps_out.get(m.group(1), {}).get(m.group(2), "")
        if expr == "github.token":
            return "SIMULATED"
        raise ValueError(f"simulator cannot evaluate ${{{{ {expr} }}}}")

    def sub(s: str) -> str:
        return EXPR.sub(lambda m: resolve(m.group(1)), s)

    log: list[dict] = []
    final_code = None
    for step in action["runs"]["steps"]:
        name = step.get("name", step.get("uses", "?"))
        if "uses" in step:
            entry = {"step": name, "uses": step["uses"], "executed": False}
            if "upload-artifact" in step["uses"]:
                p = Path(sub(step["with"]["path"]))
                entry["artifact_path"] = str(p)
                entry["artifact_files"] = sorted(f.name for f in p.glob("*")) if p.is_dir() else []
            if "github-script" in step["uses"]:
                cond = step.get("if", "")
                wants = inputs["comment"] == "true" and a.event in ("pull_request", "pull_request_target")
                entry["would_run"] = wants and "inputs.comment == 'true'" in cond
                sp = sub(step.get("env", {}).get("SUMMARY_PATH", ""))
                if entry["would_run"] and sp and Path(sp).exists():
                    (tmp / "pr_comment.md").write_text(Path(sp).read_text())
                    entry["comment_body"] = str(tmp / "pr_comment.md")
            log.append(entry)
            continue
        if "Install" in name and not a.install:
            log.append({"step": name, "executed": False, "reason": "skipped (use --install)"})
            continue
        step_env = dict(env, **{k: sub(str(v)) for k, v in step.get("env", {}).items()})
        before = gh_out.read_text()
        r = subprocess.run(["bash", "-e", "-c", sub(step["run"])], cwd=a.workdir, env=step_env,
                           capture_output=True, text=True)
        new = gh_out.read_text()[len(before):]
        if "id" in step:
            steps_out[step["id"]] = {**steps_out.get(step["id"], {}),
                                     **{k: v for k, v in (l.split("=", 1) for l in new.splitlines() if "=" in l)}}
        log.append({"step": name, "executed": True, "returncode": r.returncode,
                    "stdout_tail": r.stdout[-800:], "stderr_tail": "\n".join(
                        l for l in r.stderr.splitlines() if "ZX" not in l)[-800:]})
        final_code = r.returncode
        if r.returncode != 0:
            break

    result = {"tmp": str(tmp), "outputs": parse_outputs(gh_out), "step_summary": str(summary),
              "final_exit_code": final_code, "steps": log}
    print(json.dumps(result, indent=2))
    return final_code or 0


if __name__ == "__main__":
    sys.exit(main())
