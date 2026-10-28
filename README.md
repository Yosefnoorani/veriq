# Veriq — a truth layer for AI-written quantum code

[![verified by veriq](https://img.shields.io/badge/verified_by-veriq-6f42c1)](docs/certificates.md)
[![signed certificates](https://img.shields.io/badge/certificates-Ed25519_signed-6f42c1)](docs/certificates.md)

LLMs now write a lot of quantum code. Some of it is wrong in ways that are hard to spot:
a swapped CNOT, an off-by-one rotation angle, an oracle that forgets to uncompute.
Running the circuit once and looking at a histogram often **does not** reveal the bug.

**Veriq** is a neutral, open verification layer. Give it a circuit (and optionally a
trusted reference or an expected result) and it returns **PASS / FAIL / INCONCLUSIVE**
for each check, with evidence, plus an overall verdict and a self-contained HTML/JSON report.

| # | Check | What it proves | Engine |
|---|-------|----------------|--------|
| 1 | **Transpile integrity** | The compiled circuit (generic `rz/sx/x/cx` basis + linear coupling, optionally a `GenericBackendV2` fake backend) still implements the source circuit. | MQT QCEC, fallback `qiskit.quantum_info.Operator` (≤10 qubits) |
| 2 | **Reference equivalence** | The candidate is formally equivalent (up to global phase) to a trusted reference. On failure, Veriq searches for a **concrete counterexample** input state and shows both outputs. | MQT QCEC + statevector search (≤12 qubits) |
| 3 | **Statistical test** | Shots on Qiskit Aer match an expected distribution (or the reference's ideal distribution, or an allowed support set). Chi-square goodness-of-fit + total variation distance, plus "impossible outcome" detection. | Qiskit Aer, SciPy |
| 4 | **Metrics** | Qubits, depth, size, gate counts, 2-qubit and 3+-qubit gate counts, before vs after transpilation. | Qiskit |

Overall verdict: **FAIL** if any check fails, **PASS** if every applicable check passes,
otherwise **INCONCLUSIVE**. Checks that do not apply (e.g. no `--reference`) are `SKIPPED`.
CLI exit codes: `0` PASS, `1` FAIL, `2` INCONCLUSIVE, `3` input error — so it drops straight into CI.

## Install

Python 3.10+ (developed on 3.13).

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'      # or: make install
```

Pinned stack: `qiskit 2.6.1`, `qiskit-aer 0.18.2`, `mqt.qcec 3.11.0`, `qiskit-qasm3-import`, `scipy`.

## Usage

```bash
veriq check <candidate.py | .qasm | .qasm3> \
    [--reference <trusted.py | .qasm>] \
    [--expect '<json>' | --expect expected.json] \
    [--backend generic | generic:<nqubits>] \
    [--shots 4096] [--seed 7] [--timeout 30] \
    --report out.html [--json out.json]
```

**Loading circuits**
- `.py`: the module must expose a `QuantumCircuit` named `circuit`, or a `build()` function returning one.
- `.qasm` / `.qasm3`: OpenQASM 2 or 3 (detected from the `OPENQASM` header).
- Final measurements are stripped for the formal checks and re-added (`measure_all`) for sampling.

**`--expect` formats** (inline JSON or a file; bitstrings in Qiskit order, qubit 0 rightmost)
```jsonc
{"000": 0.5, "111": 0.5}                                  // bare distribution
{"distribution": {"00": 0.5, "11": 0.5}, "shots": 8192, "tvd_threshold": 0.05}
{"support": ["000", "111"]}                               // property: only these outcomes may appear
```
Without `--expect` but with `--reference`, the reference's ideal distribution is used.

**Example**
```bash
veriq check examples/qft_buggy.py --reference examples/qft_reference.py --report reports/qft_buggy.html
```
```
Veriq  examples/qft_buggy.py  vs  examples/qft_reference.py
  ✔ PASS         Transpile integrity      Proved equivalent after transpilation on 1 target(s).
  ✘ FAIL         Reference equivalence    NOT equivalent. Counterexample: on input |0001> the outputs overlap only 0.8132.
  ✔ PASS         Statistical test (Aer)   Consistent with expectation: TVD=0.022, chi2 p=0.64.
  ✔ PASS         Metrics                  4 qubits, depth 8, 8 two-qubit gates; compiled: depth 33, 15 2q gates.
  => VERDICT: FAIL
```
Note how the histogram test alone would have *passed* this buggy QFT — that is the point of Veriq.

![Sample report](docs/sample_report_qft_buggy.png)

## Demo and tests

```bash
./scripts/demo.sh        # or: make demo   — runs every example, writes reports/*.html + *.json
.venv/bin/python -m pytest -q             # or: make test
```

| Example | Should be | What is wrong |
|---------|-----------|---------------|
| `bell_correct.py`, `bell.qasm` | PASS | — |
| `ghz_correct.py`, `ghz3.qasm3` | PASS | — |
| `ghz_buggy.py` | FAIL | last CNOT has control/target swapped |
| `qft_correct.py` vs `qft_reference.py` | PASS | — (hand-written vs library `QFTGate`) |
| `qft_buggy.py` vs `qft_reference.py` | FAIL | every controlled-phase angle halved (off-by-one exponent) |
| `grover_correct.py` (3q, marks `101`) | PASS | — |
| `grover_buggy.py` | FAIL | oracle forgets to uncompute an `X` |

`demo.sh` exits non-zero if any example gets the wrong verdict.

## Week 2: modes, gate-set constraints, LLM benchmark

New options for `veriq check`:
- `--function NAME` / `--reference-function NAME`: pick a builder inside a multi-function `.py` file.
- `--mode state`: compare the states prepared from |0...0> (fidelity, up to global phase) instead of
  full unitaries — the right check when the spec is a state (GHZ, W, Grover output).
- `--allowed-gates h,t,tdg,cx`: gate-set constraint; any other instruction is a **FAIL**.
- Candidate code that raises or returns no circuit is a **FAIL** with error type `does not build`
  (a missing file is still an input error, exit 3).

`benchmark/` holds 28 circuits written by ChatGPT, Claude, Gemini and Perplexity (verbatim in
`benchmark/llm/raw/`), independently verified references (`benchmark/references.py`), and the harness:

```bash
.venv/bin/python benchmark/run_llm.py   # -> benchmark/results/{results.json,results.md,reports/*.html}
```

## Hard round: 7 non-standard tasks, proof-only bugs

New options for `veriq check`:
- `--coupling linear|ring|0-1,1-2,...`: coupling-map constraint checked on the circuit **as written**
  (before any transpilation, so a router cannot "fix" it). Any 2-qubit gate off an edge, or any gate on
  3+ qubits, is a **FAIL**. A malformed edge or a qubit index out of range is an input error (exit 3).
- `--no-black-boxes`: **FAIL** on `UnitaryGate`, `initialize`, `StatePreparation`, `PermutationGate`,
  `QFTGate`, isometries and other library blocks, so the circuit must be built from elementary gates
  (`mcx`/`mcp` are allowed).
- Exit codes are unchanged: 0 PASS, 1 FAIL, 2 INCONCLUSIVE, 3 input error.
- **Transpile integrity now uses `qubits_initially_zero=False` in unitary mode.** Qiskit's default
  `transpile()` assumes all qubits start in |0> and may borrow idle qubits as clean ancillas when it
  synthesises an `mcx`. The output is then right from |0...0> but wrong as a unitary (e.g. `mcx([0,3,4],5)`
  on 6 qubits). Veriq proves the safe compile and reports the default-compile hazard as information
  (`zero_init_hazard` in the evidence). State mode keeps the default.

`benchmark/hard/` holds the 7-task prompt (`prompt.md`, reconstructed), the four assistants' answers
verbatim (`raw/*.py`, never edited), references proven against exhaustive truth tables
(`references.py`), and the harness:

```bash
.venv/bin/python benchmark/hard/run_hard.py              # ~2 min incl. mutation study
.venv/bin/python benchmark/hard/run_hard.py --no-mutants # ~10 s, verdicts and costs only
# -> benchmark/hard/results/{results.json,results.md,mutation.json,reports/*.html}
```

Findings (details in `benchmark/hard/results/results.md`):
- All 28 circuits are correct (28/28 PASS, proved). Gemini's C3X uses `rz` instead of `p` and differs by
  the global phase e^{-iπ/16}, which is allowed.
- The costs are very different: after transpiling to {cx, rz, sx, x}, cmul7 ranges from 70 to 1116 CX
  (15.9x), maj5 from 240 to 1312 (5.5x), and C3X on a linear chain from 24 to 150 (6.2x).
- In 5 of 28 circuits, Qiskit's default compile is not unitary-equivalent (the `qubits_initially_zero`
  hazard). Only a unitary proof sees this.
- Mutation study: 1036 injected bugs (deleted gate, negated angle, π written as 3.14, flipped CX,
  cp→crz, p→rz) were added to the 28 correct circuits. Of 966 truly wrong mutants, the usual Aer
  histogram from |0...0> catches only 327 (34%). 596 more need an exhaustive basis-input sweep. 43 are
  caught by the proof alone:
  - 39 phase errors in the C3X circuits leave every basis-input distribution unchanged, so no sampling
    test can catch them;
  - in 4 QPE circuits, π written as 3.14 moves the output distribution by a TVD of about 1e-6, far below
    shot noise.

## Showcase: the silent transpile footgun

`examples/transpile_hazard/` contains a 5-qubit `mcx([0,1,2], 3)` block. After a default
`transpile()` it passes Aer sampling (TVD 0), yet Veriq proves it NOT equivalent, with
counterexample |10100>. Reused via `to_gate()`, it gives the wrong output.

This is documented Qiskit behaviour (`qubits_initially_zero=True` since 1.3), not a Qiskit
bug. The fix is `qubits_initially_zero=False`. See that folder's README. Post drafts are in
`docs/posts/transpile_hazard_{en,he}.md`.

```
python examples/transpile_hazard/demo.py
```

## Use in CI (GitHub Action)

Veriq ships a composite action (`action.yml` at the repo root). List your circuits in `.veriq.yml`:

```yaml
version: 1
changed-only: true            # on PRs, run only checks whose files changed (needs fetch-depth: 0)
run-all-on: [src/**, requirements.txt]
checks:
  - name: qft
    file: circuits/qft.py
    reference: circuits/qft_reference.py
  - name: bell
    file: circuits/bell.py
    distribution: tests/expect/bell.json
  - name: c3x_linear
    file: circuits/c3x.py
    reference: circuits/c3x_reference.py
    allowed-gates: [cx, h, t, tdg, rz]
    coupling: linear
    no-black-boxes: true
  - name: known_bug           # a deliberately broken circuit; CI stays green only while Veriq catches it
    file: circuits/qft_buggy.py
    reference: circuits/qft_reference.py
    expect: fail
```

Then add `.github/workflows/veriq.yml`:

```yaml
name: veriq
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
  pull-requests: write        # for the sticky PR comment
jobs:
  veriq:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: <owner>/veriq@v0
        with:
          config: .veriq.yml
          fail-on: fail       # or `inconclusive` to also fail on INCONCLUSIVE
          comment: "true"
```

Each run writes a results table to the job summary, uploads the HTML reports as the `veriq-reports`
artifact, and creates or updates **one** PR comment ([sample](docs/sample_pr_comment.md)). The job fails on any
verdict that differs from `expect`. Locally, `veriq ci` runs the same thing. Full reference: [docs/ci.md](docs/ci.md).
This repo dogfoods it: [.veriq.yml](.veriq.yml) and [.github/workflows/](.github/workflows/).

## Signed verification certificates (attestation)

Every `check`/`verify`, `optimize` and `ci` result can be written as a **certificate**: a JSON file with
the SHA-256 of each input (source file + canonical OpenQASM), the verdict and an explicit `claim`
(`PROVEN_EQUIVALENT`, `NOT_EQUIVALENT`, `CHECKS_PASSED_NO_PROOF`, `CHECK_FAILED`, or `NONE` for INCONCLUSIVE),
the proof method and engine, every assumption (initial state, gate set, coupling, permutations, black boxes),
tool versions, metrics, timestamps and, for FAIL, the counterexample. It is signed with Ed25519.

```bash
veriq keygen -o veriq-signing.key                          # private key (mode 600, never commit) + .pub
veriq check cand.py -r ref.py --certificate cert.json --sign-key veriq-signing.key
veriq cert verify cert.json --key veriq-signing.pub --circuit cand.py --circuit ref.py --recheck
```

`cert verify` checks the signature against your pinned key, re-hashes the circuit files, enforces the
semantic rules (an INCONCLUSIVE result can never be certified as PASS) and, with `--recheck`, re-runs the
proof. In CI, pass `signing-key: ${{ secrets.VERIQ_SIGNING_KEY }}` to the action; the certificates are
uploaded as the `veriq-reports-certificates` artifact. The MCP `verify_circuit` tool returns an unsigned
certificate with `certificate=true`. A *verified by veriq* badge means: the certificates for this repo's
circuits are published, and you can verify them with the public key. Details, schema and key handling are
in [docs/certificates.md](docs/certificates.md).

## Use from an AI assistant (MCP server)

`veriq mcp` makes Veriq an [MCP](https://modelcontextprotocol.io) server, so Claude Desktop, Cursor or any MCP
client can **verify a circuit before showing it to you**. The tools are `verify_circuit`, `check_transpile`,
`compare_circuits`, `circuit_metrics`, `repair_hints`, `optimize_circuit` and `explain_verdict`. Each returns
structured JSON with a verdict, a counterexample and fix hints. There are also resources with conventions and
examples, and two prompts: `write-verified-circuit` and `verify-and-repair` (a bounded repair loop).

```bash
pip install -e '.[mcp]'
veriq mcp                       # stdio; or: veriq mcp --http --port 8765
```

```json
// .cursor/mcp.json  (Claude Desktop: same block in claude_desktop_config.json)
{ "mcpServers": { "veriq": { "command": "/abs/path/.venv/bin/veriq-mcp", "args": ["--root", "/abs/path/project"] } } }
```

**The server executes the code it is given. Run it locally, for yourself.** Every call builds circuits in a
sandboxed subprocess with timeouts, memory/CPU/file rlimits, no network (bubblewrap or a user network namespace),
a read-only filesystem except a temp dir, and a scrubbed environment. The checks then run in a second clean
process, so user code can't forge the verdict. `scripts/agent_loop_demo.py` shows the loop end to end with a
simulated model (FAIL → FAIL → PASS). Full reference: [docs/mcp.md](docs/mcp.md).

## Repair: what is wrong, where, and the fix

On a FAIL, `--repair-report` writes a machine-readable report: a counterexample (expected vs actual), the
**localized gate region** of the bug, exact single-gate fixes when one exists, hardware violations and metric
deltas. `veriq repair` runs a bounded verify → fix → re-verify loop with a pluggable fixer: the offline `demo`
fixer, or your own `module:function`, e.g. an LLM call. Veriq itself calls no external API.

```bash
veriq verify examples/ghz_buggy.py -r examples/ghz_correct.py --mode state --repair-report report.json
veriq repair examples/ghz_buggy.py -r examples/ghz_correct.py --mode state --out fixed.qasm
#   attempt 0: FAIL
#   attempt 1: PASS  after: flip gate #2 cx(2, 1) -> cx(1, 2)
python benchmark/repair/run_repair.py    # localization accuracy on the hard-round mutants
```

On the 958 single-gate mutants of the hard round, the flagged region contains the injected bug **88.4%** of the
time, and is a proven valid fix location (exact single-gate fix inside it) **98.5%** of the time. Details and
limitations: [docs/repair.md](docs/repair.md).

## Verified optimization: fewer CX, proven equal

`veriq optimize` compiles a circuit many ways (Qiskit levels 0-3, several seeds, an extra resynthesis round,
exact resynthesis for ≤ 6 qubits; approximation off, `qubits_initially_zero=False`). It proves the candidates
cheapest-first and returns the cheapest one with a formal **PROVEN_EQUIVALENT** proof. It never returns an
unproven candidate. It also rejects compilations that silently permute the output qubits, unless you pass
`--allow-permutation`.

```bash
veriq optimize my_circuit.py -o best.qasm
python benchmark/optimize/run_optimize.py   # the 28 hard-round circuits
```

On the 28 hard-round circuits, the result was proven for 28/28. Against Qiskit level 1, CX dropped
from 5480 to 3124 in total (ChatGPT −60%, Perplexity −58%, Claude −24%, Gemini −14%). See
[benchmark/optimize/results.md](benchmark/optimize/results.md) and [docs/optimize.md](docs/optimize.md).

## Hardware preflight: go / warn / no-go before you submit

`veriq preflight` compiles a circuit for a target device, **proves** the compiled circuit equals the input
(layout and routing permutation made explicit, `qubits_initially_zero=False`), checks native gates and coupling,
and estimates quality: ESP (product of gate and readout fidelities), duration vs T1/T2, two-qubit count. It picks
the best of several layouts/seeds (noise-aware), and optionally runs a noisy Aer simulation (TVD vs ideal, ≤ 12
qubits). Fully offline: IBM devices come from the frozen calibration snapshots in `qiskit-ibm-runtime`
(`fake_torino`, `fake_brisbane`, …; `pip install veriq[preflight]`), other devices from a small JSON profile
(native gates, coupling or all-to-all, per-gate errors, T1/T2, readout, durations).

```bash
veriq preflight my_circuit.py --backend fake_torino --reference ref.py --min-esp 0.2 --max-cx 200
veriq preflight my_circuit.py --backend my_device.json --noisy-sim --certificate pf.json
```

Exit 0 = go, 2 = warn, 1 = no-go, 3 = input error. It is also a `preflight:` key in `.veriq.yml`, an MCP tool
(`preflight_circuit`), and a certificate block. The three bundled profiles (`ionq_style_25q`,
`quantinuum_style_20q`, `braket_superconducting_style_12q`) are **illustrative, not vendor data**.

On the 28 hard-round circuits, every compiled circuit was proven equal to its input (112/112 across written and
optimized versions on both backends). On fake_torino the optimized versions cut two-qubit gates 8949 → 4900; for
the ChatGPT/Perplexity 7-bit multiplier that moves the gate from no-go (ESP 0.001) to warn (0.234). Optimization
does not always help: ESP got worse on 5/28 (torino) and 10/28 (brisbane), because fewer gates on an all-to-all
basis can route worse. **ESP is an estimate from months-old snapshots, not a hardware measurement.** See
[benchmark/preflight/results.md](benchmark/preflight/results.md) and [docs/preflight.md](docs/preflight.md).

## Large circuits (20–50+ qubits)

Above 12 qubits a brute-force truth table is impossible, so `veriq.scale.decide_equivalence` runs a tiered
engine (the CLI, the CI action and the MCP tools use it automatically):

1. **Partitioning:** if the joint interaction graph splits into independent blocks, each block is checked on its own.
2. **Exact Clifford check:** stabilizer tableaux are compared (equal up to global phase). For 100-200 qubits this takes seconds. On a mismatch, a stabilizer-input witness is attached.
3. **Operator** (≤10 qubits).
4. **mqt.qcec**, with configurable strategies (`zx`, `alternating`, `construction`, `simulation`). Each strategy runs in its own subprocess with a **hard** timeout, because QCEC's own timeout does not stop a large check.
5. **MPS falsification** (Aer matrix-product states): basis, `|+…+>` and random product inputs, with fidelity |⟨ψ|B†A|ψ⟩|². In state mode (`zero_input_equal`), the untruncated MPS overlap from |0…0⟩ is exact.

Every result has one of three statuses. **PROVEN** and **NOT** are decided. **PROBABLY** means only that the
simulated inputs (or QCEC's random simulations) found no difference. It is **falsification only** and veriq
reports it as `INCONCLUSIVE`, never as a proof.

```bash
python benchmark/scale/run.py          # GHZ, QFT, AQFT, oracle, Clifford+T, Clifford, Cuccaro, blocks; n=8..50
python benchmark/scale/report.py       # -> benchmark/scale/results.md, time_vs_qubits.png
```

Results: [benchmark/scale/results.md](benchmark/scale/results.md) and [the chart](benchmark/scale/time_vs_qubits.png).

## Veriq Bench v0.1 (public benchmark)

`benchmark/veriqbench/` packages the 7 hard tasks as a versioned, reproducible benchmark. Each task has a spec (prompt,
reference and constraints). The bug corpus is stored as data: 1036 single-gate mutants plus 28 originals, one JSON file
each, with fields for the task, the source assistant, the mutation class, the location, whether the mutant is
equivalent, and which detectors catch it. Field definitions are in
[SCHEMA.md](benchmark/veriqbench/SCHEMA.md), and the integrity hashes are in `MANIFEST.json`.

```bash
veriq bench run --model-outputs DIR            # score new model outputs: proof, CX/depth, constraints, optimized-CX gap
veriq bench corpus-eval --detector histogram   # score a detection method (built-in or file.py:fn) against the corpus
veriq bench leaderboard                        # -> benchmark/veriqbench/leaderboard/{leaderboard.md,leaderboard.html}
```

Results recomputed on the 966 wrong mutants (0/98 false positives for every detector):

| Detector | Recall |
|---|---|
| histogram | 33.9% |
| zero-state | 34.3% |
| all-basis | 96.0% |
| proof | 100% |

In the hard round all 28 submissions passed. Their CX cost, however, ranges from 1.5× to 2.1× the best proven circuit
(geomean). Details are in the [leaderboard](benchmark/veriqbench/leaderboard/leaderboard.md) and the paper draft
[docs/paper/veriq_bench.md](docs/paper/veriq_bench.md).

**Warning:** submissions run in-process without a sandbox, so only run code you trust.

## Multi-framework: OpenQASM 3, Cirq, TKET

`pip install 'veriq[qasm3,cirq,tket]'`, then verify across frameworks; the converted circuits are exact
(global phase included), qubit order is documented, and a missing extra gives a clear install hint:

```bash
veriq verify kernel.qasm kernel_cirq.py              # OpenQASM 3 candidate vs a Cirq reference
veriq verify ansatz_tket.json --reference ansatz.py   # TKET JSON vs Qiskit
```

Also in `.veriq.yml` (`framework:`, `reference-framework:`), the MCP tools (`framework` arguments; Cirq/TKET
code runs in the same sandbox) and certificates (each input records its `frontend` and framework version).
Evidence: 21 hard-round circuits translated with each framework's own converter, 63/63 proven equivalent,
87/87 deliberate mis-translations (reversed qubit order, dropped controlled phase, wrong angle units) caught;
see [docs/frameworks.md](docs/frameworks.md) and [benchmark/frameworks/results.md](benchmark/frameworks/results.md).

## Project layout

```
src/veriq/   loader.py  checks.py  runner.py  report.py  cli.py  models.py  ci.py
             mcp_server.py  tools.py  sandbox.py  _sandbox_worker.py   (MCP server)
             scale.py   (large-circuit engine)
             repair_report.py  repair.py   (repair report, localization, repair loop)
             optimize.py   (verified CX optimizer)
             preflight.py  profiles/*.json   (hardware preflight, illustrative device profiles)
             bench.py   (Veriq Bench runner, corpus-eval, leaderboard)
             frontends/   (OpenQASM 2/3, Cirq, TKET -> Qiskit, exact)
examples/    correct and buggy circuits + expect/*.json
tests/       pytest suite (unit + end-to-end through the CLI)
scripts/     demo.sh  simulate_action.py  agent_loop_demo.py
action.yml   composite GitHub Action;  .veriq.yml  this repo's own CI config
```

## Limitations

- Formal checks cover the **unitary part** only; mid-circuit measurement, reset and classical control flow give `INCONCLUSIVE`.
- The exhaustive basis-state counterexample search goes up to 12 qubits, and the Operator check to 10. Above that, equivalence is *proven* only by the Clifford tableau, by QCEC (ZX, alternating or construction) or, for states, by exact MPS overlap. Everything else is MPS / random-simulation falsification (`PROBABLY`), which is reported as INCONCLUSIVE. Some bugs are invisible to product-state inputs, for example swapping the marked string of a 50-qubit phase oracle. These stay INCONCLUSIVE: they are not reported as PASS.
- MPS falsification is exact for low-entanglement circuits but slows down sharply as entanglement grows. Highly entangling 40-50 qubit circuits may hit the time cap.
- For more than 20 qubits the statistical test is a two-sample chi² on sampled outcomes. When the outputs are spread out (distinct outcomes > shots/10) it returns INCONCLUSIVE.
- The statistical test uses a noiseless simulator; noise-aware thresholds come later.
- Hardware preflight uses frozen IBM calibration snapshots (from `qiskit-ibm-runtime`) and illustrative JSON profiles; its ESP / duration / TVD numbers are estimates under a simple noise model (no crosstalk, leakage or drift), not hardware measurements. No live device or cloud account is used.
- Front-ends: Qiskit, OpenQASM 2/3, Cirq and TKET (exact conversion to Qiskit). No classical control or symbolic parameters in Cirq/TKET input; Cirq circuits drop untouched qubits unless `cirq.I` keeps them. Other frameworks (PennyLane, Braket, Quil) are not supported yet.
- Certificates: the canonical circuit hash depends on Qiskit's QASM exporter version (the source-file hash is the stable anchor); a signature checked only against the embedded key proves integrity, not identity; there is no sigstore or transparency log yet.

## Roadmap

- **Week 1 (this release):** CLI, four checks, HTML/JSON report, examples, tests.
- **Week 2 — benchmark:** collect ~20 circuits written by different LLMs (ChatGPT, Claude, Gemini, …) for standard tasks, run Veriq on all of them, and publish the bug-catch rate — the first evidence that the tool is needed.
- **Week 3 — QML claim audit:** check "quantum advantage" claims of quantum-ML notebooks against strong classical baselines on the same data, with fair hyper-parameter budgets and statistical significance.
- **MCP server:** ✅ `veriq mcp` (verify / check_transpile / compare / metrics / repair_hints / optimize / explain; sandboxed).
- **Repair + verified optimization:** ✅ repair reports with exact localization, `veriq repair` loop with pluggable fixers, `veriq optimize` (cheapest proven compilation).
- **Large circuits:** ✅ Clifford tableau, QCEC strategies with hard timeouts, MPS falsification, partitioning, and a scaling benchmark up to 50 qubits (200 for Clifford). Next: decision-diagram (DD) simulation of counterexamples, and noise-aware statistics.
- **Veriq Bench v0.1:** ✅ tasks, mutant corpus, `veriq bench run|corpus-eval|leaderboard`, leaderboard, paper draft. Next: a sandboxed runner, pinned model versions per submission, more tasks and rounds, and real-world (non-synthetic) bugs.
- **Week 4 — CI integration:** ✅ GitHub Action + `veriq ci` (see "Use in CI"; not yet run on github.com). Still to do: a `pytest` plugin (`assert_equivalent`, `assert_distribution`) for quantum test suites.
- **Hardware preflight:** ✅ `veriq preflight` (proven compile, native/coupling checks, ESP/duration/TVD estimates, noise-aware layout, go/warn/no-go; CI key, MCP tool, certificate). Next: live calibration fetch (opt-in), backend-aware optimization, idle-error-aware layout.
- **Multi-framework frontends:** ✅ OpenQASM 3, Cirq, TKET (CLI, CI, MCP, sandbox, certificates). Next: PennyLane, Braket, Quil.
- **Signed certificates:** ✅ `veriq.certificate/1`, Ed25519 `keygen`/`certify`/`cert verify --recheck`, CI artifacts, MCP. Next: sigstore keyless signing + transparency log, in-toto/SLSA attestation format.

## License

Apache-2.0
