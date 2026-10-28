# `veriq preflight`: hardware gate before you submit

`veriq preflight` answers one question before a circuit reaches a device: **is the compiled circuit still the
circuit I wrote, does it fit the device, and is it worth running?** It runs fully offline. No cloud account,
API key or network access is used.

```bash
veriq preflight my_circuit.py -b fake_torino                      # IBM calibration snapshot (offline)
veriq preflight my_circuit.py -b fake_brisbane -r reference.py    # also prove it equals a reference
veriq preflight my_circuit.py -b ionq_style_25q --noisy-sim       # illustrative trapped-ion profile
veriq preflight my_circuit.py -b my_device.json --min-esp 0.3 --max-cx 200 --max-duration 2e-4 \
    -o compiled.qasm --json pf.json --certificate pf.cert.json
```

Exit codes: **0 = go**, **2 = warn**, **1 = no-go**, **3 = input error** (bad file, unknown backend, invalid
profile).

## What it does

1. **Load the backend** (see [Backends](#backends)) as a Qiskit `Target`: native gates, coupling, per-gate
   error and duration, readout error, T1/T2.
2. **Compile** with `qubits_initially_zero=False` for every optimisation level in `--levels` (default 1,3)
   and every seed in `--seeds` (default 4). A circuit without measurements is also compiled with
   `measure_all` appended, then the measurements are dropped again. Qiskit's VF2 layout scoring only sees
   the errors of operations that are in the circuit, so this copy gives a readout-aware layout.
3. **Rank the candidates (noise-aware layout choice)** by estimated success probability including idle
   dephasing, then by two-qubit gate count, then by duration. Candidates that land on bad qubits or
   couplers lose.
4. **Prove** the best-ranked candidate equivalent to the input. If that fails, try the next one, up to 4.
   The proof:
   - restricts the compiled circuit to its active physical qubits;
   - places the input on its initial layout and appends explicit SWAPs for the final routing permutation;
   - decides full unitary equivalence (any input state, up to global phase) with Veriq's engine (Clifford
     tableau, Operator, QCEC).

   The layout and permutation are part of the claim, so a wrong permutation is refuted. A candidate whose
   only difference is floating-point drift (process fidelity > 1 − 10⁻⁶, but outside the 10⁻⁸ proof
   tolerance) is reported as *undecided*, never as refuted, and is skipped in favour of a proven candidate.
5. **Check** that every instruction is native and on a coupled qubit pair (`Target.instruction_supported`).
6. **Estimate** quality (below), optionally **simulate** with noise, and give the **gate** verdict.

With `--reference`, the input is also proven against the reference (`--mode unitary|state`). A mismatch is
a no-go.

## Estimates (not measurements)

- **ESP** (expected success probability) = Π over compiled gates (1 − error) × Π over measured qubits
  (1 − readout error). Errors are the backend's average gate errors (EPG). A circuit without measurements
  is assumed to be read out on every logical qubit at its final physical position (`readout_assumed`).
- **Duration**: an ASAP schedule of the compiled circuit using the backend gate durations, including the
  final readout.
- **Idle dephasing**: `esp_with_idle` = ESP × Π_q exp(−idle_q / T2_q), where idle_q is the time qubit q
  waits during the schedule. This is used for ranking and reported. The gate thresholds use the plain ESP.
- **D/T1, D/T2** against the shortest T1/T2 among the active qubits.
- **Noisy simulation** (`--noisy-sim`, at most 12 active qubits): Aer with a depolarizing channel per gate
  (λ = EPG·d/(d−1)) and a symmetric readout error from the same data. It reports the TVD between the noisy
  and ideal output distributions over all logical qubits. There is no idle T1/T2 decay, crosstalk, leakage
  or coherent error. TVD is therefore **not independent evidence**, because it comes from the same
  calibration numbers.

ESP is a standard first-order figure of merit. It is usually optimistic for deep circuits and does not
predict an actual hardware run. Use it to compare compilations and to stop obviously hopeless jobs.

## Gate

| check | no-go (FAIL) | warn (INCONCLUSIVE) |
|---|---|---|
| Fits backend | more logical qubits than the device | |
| Input vs reference (with `-r`) | refuted | undecided |
| Compiled circuit proven equivalent | refuted | undecided (e.g. timeout, drift, non-unitary ops) |
| Native gates and coupling | any unsupported instruction | |
| Estimated success probability | ESP < `--min-esp` (0.05) | ESP < `--warn-esp` (0.5) |
| Two-qubit gate count | > `--max-cx` (off by default) | |
| Duration vs coherence | > `--max-duration` s (off) | duration > `--warn-t2-fraction` (0.5) × min T2 |
| Noisy simulation | TVD > `--max-tvd` (off; informational otherwise) | |

Any FAIL gives **no-go**. Otherwise, any INCONCLUSIVE gives **warn**. Otherwise the gate is **go**.

## Backends

`-b` accepts the following:

- **IBM fake backends** from `qiskit-ibm-runtime` (pinned 0.51.0, extra `pip install veriq[preflight]`):
  `fake_torino`, `FakeBrisbane`, `sherbrooke`, … Each one is a frozen calibration snapshot shipped inside
  the package. Veriq records the properties file, its `last_update_date` and the sha256 of the data. The
  snapshot is **not today's device**. In 0.51.0, `fake_torino` (133 qubits, cz) is dated 2025-02-26 and
  `fake_brisbane` (127 qubits, ecr) is dated 2025-02-26 as well.
- **Built-in profiles** (all **illustrative**, round numbers in the public order of magnitude of each
  device class, **not vendor data**):
  - `ionq_style_25q`: trapped ions, all-to-all, rz/rx/ry + rxx, 2q error 0.6 %, slow gates, long T2.
  - `quantinuum_style_20q`: trapped ions, all-to-all, rzz with 2q error 0.15 %.
  - `braket_superconducting_style_12q`: 3×4 grid, rx/rz + cz, short T1/T2, with one bad coupler (5,6) and
    one bad readout (q5) to show the noise-aware layout.
- **Your own profile** `device.json`:

```json
{
  "schema": "veriq.backend/1",
  "name": "my-device",
  "illustrative": false,
  "source": "vendor calibration export 2026-10-01",
  "calibration_date": "2026-10-01",
  "num_qubits": 8,
  "coupling": "all",
  "directed": false,
  "gates": {
    "rz":  {"error": 0.0,    "duration": 0.0},
    "sx":  {"error": 0.0003, "duration": 3.5e-8},
    "x":   {"error": 0.0003, "duration": 3.5e-8},
    "cz":  {"error": 0.006,  "duration": 6.8e-8, "overrides": {"2,3": {"error": 0.03}}}
  },
  "readout": {"error": [0.01, 0.01, 0.02, 0.01, 0.01, 0.01, 0.05, 0.01], "duration": 1.2e-6},
  "t1": 1.5e-4,
  "t2": [1.0e-4, 1.2e-4, 0.9e-4, 1.0e-4, 1.1e-4, 1.0e-4, 0.5e-4, 1.0e-4]
}
```

The fields are as follows:

- `coupling`: `"all"`, `"linear"`, `{"grid": [rows, cols]}`, or an explicit edge list `[[0,1],[1,2],…]`.
  `directed: true` keeps the edges one-way.
- `gates`: Qiskit standard gate names, 1- and 2-qubit only. Native trapped-ion gates (GPi/MS) are
  expressed via their standard equivalents, e.g. `rxx`/`rzz` + `rz`/`rx`/`ry`.
- `overrides`: per qubit pair (`"a,b"`) or per qubit (`"q"`) for 1q gates.
- `readout.error`, `t1`, `t2`: a scalar or a per-qubit list.
- Times are in seconds. Errors are average gate infidelities.
- The profile's sha256 is recorded in the result and the certificate. `illustrative` defaults to true.
  Set it to false only for real data, and say where it came from in `source`.

## Output

The text report shows the backend and its source and date, every check, the chosen candidate, the layout
(physical qubits, initial and final positions), the estimates and the range of ESP across candidates.
`--json` writes everything, `-o` writes the compiled circuit as OpenQASM 2, and `--certificate` writes a
`veriq.certificate/1` of kind `preflight`. The certificate embeds the input, the compacted compiled circuit
and the layout. `veriq cert verify --recheck` re-proves *compiled ≡ input* from the stored layout; it does
not re-run the estimates. See [certificates.md](certificates.md).

## In CI and MCP

`.veriq.yml` (see [ci.md](ci.md)):

```yaml
checks:
  - name: grover
    file: examples/grover.py
    preflight: fake_torino               # or a profile path, or:
  - name: qpe
    file: examples/qpe.py
    preflight: {backend: profiles/device.json, min-esp: 0.2, warn-esp: 0.5, max-cx: 120,
                max-duration: 2e-4, seeds: 4, levels: [1, 3], noisy-sim: false, max-tvd: 0.3}
```

The preflight runs after the entry's other checks and becomes one more check (`Hardware preflight`): go is
PASS, warn is INCONCLUSIVE, and no-go is FAIL. It is merged into the entry verdict, shown in the PR comment
notes, and summarised in the entry certificate (`preflight` block). On `--recheck`, a CI certificate keeps
the certified preflight status; the estimates are not re-run.

MCP: the `preflight_circuit` tool takes `code`/`path`, an optional reference, `backend` (a built-in name or an
inline `veriq.backend/1` object; file paths are refused), thresholds, `seeds`, `levels` and `noisy_sim`. It
returns the gate, checks, estimates, layout, proof and `compiled_qasm`. See [mcp.md](mcp.md).

## Limitations

- All quality numbers are **estimates** from calibration data. They do not include crosstalk, leakage,
  drift, coherent or non-Markovian errors, or queue-time recalibration.
- IBM snapshots are old frozen files. The built-in non-IBM profiles are illustrative, not vendor data.
- Layout search is Qiskit's (several seeds and levels plus the readout-aware variant), ranked by ESP. It is
  not an exhaustive noise-aware placement.
- The proof covers the unitary part. Mid-circuit measurement, reset and classical control give an
  undecided proof (warn).
- Gates with 3 or more qubits cannot be native in a profile. Pulse-level and dynamic-circuit timing is not
  modelled.
- The noisy simulation is capped at 12 active qubits.
