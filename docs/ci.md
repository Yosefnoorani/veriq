# Veriq in CI

There are two pieces: the `veriq ci` command, which reads `.veriq.yml`, and a composite GitHub Action
(`action.yml`) that wraps it for pull requests.

> Status, 27 Oct 2026: built and tested locally. The action's bash steps run under
> `scripts/simulate_action.py`, and `actionlint` passes on the workflows. It has **not run on github.com yet**.
> See "Verified only on GitHub" below.

## `.veriq.yml`

```yaml
version: 1                    # optional; only 1 is supported
changed-only: false           # true: on PRs, run only checks whose files changed
run-all-on: [src/**]          # changed paths/globs that force every check to run
report-dir: veriq-reports     # per-check HTML + JSON reports (relative to this file)
defaults:                     # applied to every check (any check key except name/file/function/reference*/watch)
  shots: 4096
  seed: 7
checks:
  - name: qft                 # default: the file's stem; must be unique
    file: circuits/qft.py     # .py (build()/circuit/qc), .qasm or .qasm3; required
    function: build_qft       # optional builder function in `file`
    reference: circuits/qft_reference.py
    reference-function: build # optional builder in `reference`
    mode: unitary             # unitary (default) | state (state preparation: compare from |0…0>)
    distribution: expect/qft.json   # optional: path, inline JSON string, or a YAML mapping
    allowed-gates: [h, cx, rz]      # or "h,cx,rz"
    coupling: linear          # "linear" or an explicit [[0,1],[1,2]] list
    no-black-boxes: true      # reject opaque gates / unitaries / isometries in the source
    backend: generic          # also compile for GenericBackendV2 ("generic" or "generic:N")
    shots: 4096
    seed: 7
    timeout: 30               # seconds for the formal check
    watch: [circuits/_lib.py, "circuits/common/*.py"]   # extra files that affect this check (globs ok)
    expect: pass              # pass (default) | fail | inconclusive
    preflight: fake_torino    # optional hardware gate (docs/preflight.md); or a mapping:
    # preflight: {backend: profiles/device.json, min-esp: 0.2, warn-esp: 0.5, max-cx: 120,
    #             max-duration: 2e-4, warn-t2-fraction: 0.5, seeds: 4, levels: [1, 3],
    #             noisy-sim: false, max-tvd: 0.3, shots: 4000, timeout: 30}
```

`preflight` runs `veriq preflight` on the candidate after the other checks and adds the result as one more check
(`Hardware preflight`): go = PASS, warn = INCONCLUSIVE, no-go = FAIL, merged into the entry verdict (so
`expect` applies to it too). The PR comment notes show the gate, the estimated ESP, the two-qubit count and the
duration, and the entry certificate gets a `preflight` block. A `.json` profile path is relative to the config
file and also counts as a watched file under `changed-only`. Preflight is offline: the IBM backends are
frozen calibration snapshots from `qiskit-ibm-runtime` (`pip install veriq[preflight]`).

Paths are relative to the config file. Errors are caught before anything runs, and `veriq ci` exits **3** with a
message that names the entry and key. The cases are: unknown keys (with a "did you mean" hint), wrong types,
missing files, duplicate names, an empty `checks`, a bad `expect` or `mode`, and invalid YAML.

```
$ veriq ci
veriq ci: config error: checks[2] (bell): unknown key 'refrence' (did you mean 'reference'?). Allowed: ...
```

### `expect`

`expect` is for circuits that are *supposed* to be wrong, such as regression fixtures for bugs Veriq must keep catching.
A check is "ok" when its verdict equals `expect`. A mismatch in either direction fails CI: a buggy fixture that
starts passing means a check got weaker.

## `veriq ci`

```
veriq ci [-c .veriq.yml] [--fail-on fail|inconclusive] [--changed-only | --all] [--base REF]
         [--changed-files FILE] [--report-dir DIR] [--json FILE] [--markdown FILE] [--github-output FILE] [-q]
```

| exit | meaning |
|---|---|
| 0 | every check gave its expected verdict (with `--fail-on fail`, an unexpected INCONCLUSIVE only warns) |
| 1 | an unexpected FAIL, or a check that should FAIL/be INCONCLUSIVE gave something else |
| 2 | an unexpected INCONCLUSIVE with `--fail-on inconclusive` |
| 3 | config or input error |

A candidate that crashes while building is a FAIL verdict (the Build check), not an input error.

* `--markdown`: the summary table (marker comment, headline, per-check row with verdict, expectation,
  CX count as written → after Veriq's compile, notes such as counterexample inputs and `zero_init_hazard`).
* `--json`: machine-readable results, with each check's full report embedded.
* `--github-output`: appends `exit-code`, `ran`, `unexpected`, `skipped` and `report-dir`.

### changed-only

With `changed-only: true` or `--changed-only`, Veriq diffs `BASE...HEAD`. BASE is `--base`, or `origin/$GITHUB_BASE_REF`
on a pull_request. A check runs if any changed path matches its `file`, `reference`, `distribution` file, or `watch`
patterns. Every check runs when the config itself changed, when a path matches `run-all-on`, or when git can't tell
(no base, shallow clone, unknown ref). The summary says which case applied. `--changed-files FILE` (one path per line)
replaces git, for testing or other CI systems. `--all` overrides the config.

On GitHub, the checkout needs `fetch-depth: 0`. Otherwise the base commit is missing and every check runs.

## The action

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: <owner>/veriq@v0
  with:
    config: .veriq.yml        # default
    python-version: "3.12"    # default
    fail-on: fail             # default; or inconclusive
    comment: "true"           # sticky PR comment on pull_request events
    qiskit-version: ""        # e.g. 1.4.3 to test against another Qiskit
    changed-only: ""          # "true"/"false" overrides the config
    base-ref: ""              # default origin/<PR base>
    report-dir: ""            # default: the config's report-dir
    artifact-name: veriq-reports
    github-token: ${{ github.token }}
    certificates: "true"      # write + upload <artifact-name>-certificates (see certificates.md)
    signing-key: ""           # e.g. ${{ secrets.VERIQ_SIGNING_KEY }}; empty = unsigned certificates
    signing-key-passphrase: ""
```

Steps:
1. setup-python.
2. `pip install $GITHUB_ACTION_PATH` (plus `qiskit==X` if requested).
3. `veriq ci`, which writes the summary to `$GITHUB_STEP_SUMMARY`.
4. upload the reports with `actions/upload-artifact@v4`.
5. create or update the PR comment with `actions/github-script@v7`. It finds the comment by `<!-- veriq-ci-comment -->`.
6. exit with Veriq's code.

Outputs are `exit-code`, `unexpected` and `summary-path`. Inputs reach the shell through `env:`, never by inline
`${{ }}` interpolation; a test enforces this.

Permissions: `contents: read`, `pull-requests: write`. On PRs from forks the token is read-only, so the comment step
fails softly (`continue-on-error`). The job summary and the artifact still have the results.

`qiskit-version` installs that Qiskit over the pinned one (Veriq pins `qiskit==2.6.1`, `qiskit-aer==0.18.2`).
pip may refuse or warn if aer/qcec don't support it. This is meant for checking how the compiler behaves
(see the transpile-hazard showcase: the hazard appears from 1.3.0 onwards).

Sample comment: [sample_pr_comment.md](sample_pr_comment.md).

## Testing it without GitHub

```
python -m pytest tests/test_ci.py                                  # config, ci command, markdown, changed-only, action shape
python scripts/simulate_action.py                                  # run action.yml's bash steps with temp GITHUB_* files
python scripts/simulate_action.py --install                        # ... including pip install from the action path
python scripts/simulate_action.py --input fail-on=inconclusive --event push
```

The simulator runs each `shell: bash` step with `bash -e`, the way the runner does. It substitutes `${{ inputs.* }}`
and `${{ steps.*.outputs.* }}`, and reports what the `uses:` steps would get: the artifact file list and the
comment body. It doesn't evaluate `if:` expressions in general, and it doesn't call the GitHub API.

## Verified only on GitHub

- That the composite action resolves `uses: ./` and `<owner>/veriq@v0`. The `v0` tag has to be created and pushed.
- `setup-python` and a clean `pip install` on the runner image. Locally this was tested on Python 3.13 only.
- Artifact upload, and the sticky comment's create-then-update cycle against the real API and token permissions.
- Fork-PR behaviour. `GITHUB_BASE_REF` diffing with `fetch-depth: 0`.
- How the summary renders in GitHub's Markdown (table escaping, `<sub>`).
