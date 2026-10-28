# Preflight evidence: 28 hard-round circuits on offline IBM fake backends

Generated 2026-10-28T18:16:48+02:00 by `benchmark/preflight/run_preflight.py` in 168.6 s.

> **ESP is an estimate, not a hardware measurement.** ESP = product of (1 − gate error) over all compiled gates × (1 − readout error) of each measured qubit (all logical qubits are assumed measured when the circuit has no measurements), taken from frozen calibration snapshots shipped with qiskit-ibm-runtime. TVD comes from a noisy Aer simulation with a depolarizing + readout model built from the same snapshot (no idle decoherence, crosstalk, leakage or drift). Use the numbers to compare compilations, not to predict a real run.

## Backends

- **fake_torino** (133 qubits): qiskit-ibm-runtime 0.51.0 fake_provider snapshot (props_torino.json), calibration date 2025-02-26T15:26:08-05:00, data sha256 `116c5692ad566921…`
- **fake_brisbane** (127 qubits): qiskit-ibm-runtime 0.51.0 fake_provider snapshot (props_brisbane.json), calibration date 2025-02-26T14:33:06-05:00, data sha256 `bc8b29433a8e1935…`

## Summary

**fake_torino**: compiled-circuit proofs PROVEN 56/56; gate as written {'warn': 4, 'no-go': 3, 'go': 21}, optimized {'warn': 6, 'no-go': 1, 'go': 21}; on 28 circuits with an optimized version, ESP improved on 12, unchanged on 11, worse on 5; median ESP 0.739 → 0.738; total two-qubit gates 8949 → 4900.

  Non-go reasons (as written + optimized, a circuit can have several): Estimated success probability ×14, Duration vs coherence ×6.

**fake_brisbane**: compiled-circuit proofs PROVEN 56/56; gate as written {'no-go': 7, 'warn': 8, 'go': 13}, optimized {'no-go': 4, 'warn': 11, 'go': 13}; on 28 circuits with an optimized version, ESP improved on 8, unchanged on 10, worse on 10; median ESP 0.693 → 0.692; total two-qubit gates 10382 → 5435.

  Non-go reasons (as written + optimized, a circuit can have several): Duration vs coherence ×30, Estimated success probability ×18.

## Per circuit

Gate: go / warn / no-go (no-go includes circuits that are NOT equivalent to the trusted reference). Proof = compiled vs input, layout-aware.

| Assistant | Task | vs ref | fake_torino gate | ESP written → opt | 2q written → opt | µs written → opt | TVD written → opt | proof | fake_brisbane gate | ESP written → opt | 2q written → opt | µs written → opt | TVD written → opt | proof |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chatgpt | maj5 | PASS | warn → warn | 0.137 → 0.137 | 450 → 450 | 49.6 → 49.6 | 0.826 → 0.826 | proven/proven | no-go → no-go | 0.035 → 0.034 | 450 → 450 | 270.8 → 271.0 | 0.936 → 0.936 | proven/proven |
| claude | maj5 | PASS | no-go → no-go | 0.000 → 0.003 | 2266 → 1520 | 233.8 → 177.5 | 0.985 → 0.970 | proven/proven | no-go → no-go | 0.000 → 0.000 | 2272 → 2118 | 1397.3 → 1484.5 | 0.986 → 0.976 | proven/proven |
| gemini | maj5 | PASS | warn → warn | 0.135 → 0.135 | 451 → 451 | 55.3 → 55.3 | 0.830 → 0.830 | proven/proven | no-go → no-go | 0.035 → 0.035 | 453 → 453 | 306.3 → 306.3 | 0.937 → 0.937 | proven/proven |
| perplexity | maj5 | PASS | warn → warn | 0.135 → 0.135 | 451 → 451 | 55.3 → 55.3 | 0.830 → 0.830 | proven/proven | no-go → no-go | 0.035 → 0.035 | 453 → 453 | 306.3 → 306.3 | 0.937 → 0.937 | proven/proven |
| chatgpt | cmul7 | PASS | no-go → warn | 0.001 → 0.234 | 1865 → 384 | 221.8 → 44.4 | 0.963 → 0.782 | proven/proven | no-go → warn | 0.000 → 0.089 | 2595 → 374 | 1518.5 → 277.1 | 0.972 → 0.894 | proven/proven |
| claude | cmul7 | PASS | warn → warn | 0.105 → 0.228 | 556 → 384 | 68.3 → 44.4 | 0.860 → 0.786 | proven/proven | no-go → warn | 0.023 → 0.089 | 556 → 374 | 376.0 → 277.1 | 0.945 → 0.895 | proven/proven |
| gemini | cmul7 | PASS | go → go | 0.512 → 0.525 | 122 → 102 | 15.6 → 11.8 | 0.483 → 0.475 | proven/proven | warn → warn | 0.411 → 0.462 | 122 → 102 | 80.3 → 69.5 | 0.585 → 0.527 | proven/proven |
| perplexity | cmul7 | PASS | no-go → warn | 0.001 → 0.234 | 1865 → 384 | 221.8 → 44.4 | 0.963 → 0.782 | proven/proven | no-go → warn | 0.000 → 0.089 | 2595 → 374 | 1518.5 → 277.1 | 0.972 → 0.894 | proven/proven |
| chatgpt | qpe_t | PASS | go → go | 0.896 → 0.904 | 16 → 13 | 3.6 → 3.3 | 0.102 → 0.095 | proven/proven | go → go | 0.858 → 0.853 | 16 → 17 | 13.5 → 14.1 | 0.141 → 0.144 | proven/proven |
| claude | qpe_t | PASS | go → go | 0.899 → 0.908 | 15 → 12 | 3.5 → 3.1 | 0.100 → 0.089 | proven/proven | go → go | 0.873 → 0.843 | 13 → 19 | 11.4 → 12.1 | 0.123 → 0.151 | proven/proven |
| gemini | qpe_t | PASS | go → go | 0.899 → 0.908 | 15 → 12 | 3.5 → 3.1 | 0.100 → 0.089 | proven/proven | go → go | 0.873 → 0.843 | 13 → 19 | 11.4 → 12.1 | 0.123 → 0.151 | proven/proven |
| perplexity | qpe_t | PASS | go → go | 0.899 → 0.908 | 15 → 12 | 3.5 → 3.1 | 0.100 → 0.089 | proven/proven | go → go | 0.874 → 0.843 | 13 → 19 | 11.3 → 12.1 | 0.125 → 0.151 | proven/proven |
| chatgpt | c3x_linear | PASS | go → go | 0.549 → 0.644 | 150 → 85 | 16.9 → 11.1 | 0.445 → 0.372 | proven/proven | warn → warn | 0.430 → 0.614 | 150 → 74 | 107.8 → 56.5 | 0.543 → 0.402 | proven/proven |
| claude | c3x_linear | PASS | go → go | 0.871 → 0.871 | 24 → 24 | 3.6 → 3.6 | 0.130 → 0.130 | proven/proven | go → go | 0.824 → 0.824 | 24 → 24 | 15.2 → 15.2 | 0.174 → 0.174 | proven/proven |
| gemini | c3x_linear | PASS | go → go | 0.549 → 0.644 | 150 → 85 | 16.9 → 11.0 | 0.445 → 0.358 | proven/proven | warn → warn | 0.430 → 0.613 | 150 → 74 | 107.8 → 56.6 | 0.543 → 0.403 | proven/proven |
| perplexity | c3x_linear | PASS | go → go | 0.655 → 0.644 | 92 → 85 | 10.1 → 11.1 | 0.332 → 0.373 | proven/proven | warn → warn | 0.548 → 0.613 | 92 → 74 | 59.4 → 56.6 | 0.437 → 0.403 | proven/proven |
| chatgpt | reverse6_nn | PASS | go → go | 0.756 → 0.756 | 45 → 45 | 4.5 → 4.5 | 0.237 → 0.237 | proven/proven | go → go | 0.715 → 0.715 | 45 → 45 | 21.2 → 21.2 | 0.269 → 0.269 | proven/proven |
| claude | reverse6_nn | PASS | go → go | 0.754 → 0.754 | 45 → 45 | 3.6 → 3.6 | 0.238 → 0.238 | proven/proven | go → go | 0.709 → 0.709 | 45 → 45 | 14.6 → 14.6 | 0.275 → 0.275 | proven/proven |
| gemini | reverse6_nn | PASS | go → go | 0.756 → 0.756 | 45 → 45 | 4.5 → 4.5 | 0.237 → 0.237 | proven/proven | go → go | 0.715 → 0.715 | 45 → 45 | 21.2 → 21.2 | 0.269 → 0.269 | proven/proven |
| perplexity | reverse6_nn | PASS | go → go | 0.756 → 0.756 | 45 → 45 | 4.5 → 4.5 | 0.237 → 0.237 | proven/proven | go → go | 0.715 → 0.715 | 45 → 45 | 21.2 → 21.2 | 0.269 → 0.269 | proven/proven |
| chatgpt | bv22 | PASS | go → go | 0.940 → 0.940 | 3 → 3 | 1.9 → 1.9 | 0.063 → 0.064 | proven/proven | go → go | 0.921 → 0.921 | 3 → 3 | 3.5 → 3.5 | 0.078 → 0.079 | proven/proven |
| claude | bv22 | PASS | go → go | 0.940 → 0.940 | 3 → 3 | 1.9 → 1.9 | 0.063 → 0.064 | proven/proven | go → go | 0.921 → 0.921 | 3 → 3 | 3.5 → 3.5 | 0.078 → 0.079 | proven/proven |
| gemini | bv22 | PASS | go → go | 0.940 → 0.940 | 3 → 3 | 1.9 → 1.9 | 0.063 → 0.064 | proven/proven | go → go | 0.921 → 0.921 | 3 → 3 | 3.5 → 3.5 | 0.078 → 0.079 | proven/proven |
| perplexity | bv22 | PASS | go → go | 0.940 → 0.940 | 3 → 3 | 1.9 → 1.9 | 0.063 → 0.064 | proven/proven | go → go | 0.921 → 0.921 | 3 → 3 | 3.5 → 3.5 | 0.078 → 0.079 | proven/proven |
| chatgpt | add3 | PASS | go → go | 0.739 → 0.738 | 49 → 49 | 6.6 → 6.6 | 0.249 → 0.250 | proven/proven | warn → warn | 0.693 → 0.692 | 38 → 38 | 28.2 → 28.5 | 0.288 → 0.290 | proven/proven |
| claude | add3 | PASS | go → go | 0.677 → 0.677 | 85 → 85 | 9.8 → 9.9 | 0.310 → 0.311 | proven/proven | warn → warn | 0.522 → 0.533 | 74 → 76 | 49.8 → 53.7 | 0.464 → 0.454 | proven/proven |
| gemini | add3 | PASS | go → go | 0.574 → 0.574 | 71 → 71 | 8.9 → 8.9 | 0.407 → 0.407 | proven/proven | warn → warn | 0.544 → 0.526 | 73 → 73 | 50.3 → 50.9 | 0.447 → 0.459 | proven/proven |
| perplexity | add3 | PASS | go → go | 0.739 → 0.738 | 49 → 49 | 6.6 → 6.6 | 0.249 → 0.250 | proven/proven | warn → warn | 0.693 → 0.692 | 38 → 38 | 28.2 → 28.5 | 0.288 → 0.290 | proven/proven |

## Limitations

- Calibration snapshots are frozen files inside qiskit-ibm-runtime, months old; real devices drift daily.
- ESP ignores idle decoherence (reported separately as `esp_with_idle` = ESP × Π exp(−idle/T2)), crosstalk, leakage, non-Markovian and coherent errors; it is usually optimistic for deep circuits.
- 'Optimized' means fewer gates on the generic all-to-all basis; after routing to a backend that can translate into slightly *lower* ESP (more SWAPs or a worse layout), which is why some rows get worse.
- The noisy simulation uses the same simplified model, so TVD and ESP are not independent evidence.
- The 'optimized' circuit is optimized for an all-to-all device with the generic basis; the backend compile then routes it. A backend-aware optimizer could do better.
- Proofs are full unitary equivalence (qubits_initially_zero=False) on the active physical qubits, with the layout and final routing permutation made explicit.
