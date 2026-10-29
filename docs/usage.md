# Usage: checks, options and examples

<sub>Moved from the README. See also the [README](../README.md).</sub>

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

## Install (from source)

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

![Sample report](sample_report_qft_buggy.png)

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

## More options

New options for `veriq check`:
- `--function NAME` / `--reference-function NAME`: pick a builder inside a multi-function `.py` file.
- `--mode state`: compare the states prepared from |0...0> (fidelity, up to global phase) instead of
  full unitaries — the right check when the spec is a state (GHZ, W, Grover output).
- `--allowed-gates h,t,tdg,cx`: gate-set constraint; any other instruction is a **FAIL**.
- Candidate code that raises or returns no circuit is a **FAIL** with error type `does not build`
  (a missing file is still an input error, exit 3).

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
