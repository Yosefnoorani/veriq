# Veriq week 2: 28 LLM-written circuits (4 assistants x 7 tasks)

Generated 2026-10-27T20:14:01+02:00. Prompts sent 2026-10-27 (free plans). Total 27/28 PASS in 4.31 s.

Note: Gemini Pro returned an error twice (no code) and answered on the third try.

## Verdicts

| assistant | ghz5 | w3 | qft4 | iqft3 | grover3 | toffoli | adder2 | score |
|---|---|---|---|---|---|---|---|---|
| chatgpt | PASS | PASS | PASS | PASS | PASS | PASS | FAIL | 6/7 |
| claude | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |
| gemini | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |
| perplexity | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |

Modes: state = prepared state from |0...0> up to global phase (ghz5, w3, grover3); unitary = full unitary up to global phase (qft4, iqft3, toffoli, adder2). toffoli also enforces the gate set {h,t,tdg,s,sdg,cx}.

## Failures

- **chatgpt / adder2** (does not build): build_adder2 calls qc.ccx(1, 0, 2, 4) and qc.ccx(3, 0, 2, 4) with four qubits, but Qiskit's ccx takes exactly two controls and a target, so the 4th argument is read as ctrl_state=4 and the call raises CircuitError('invalid control state specification'); no circuit is ever produced. If those two calls are read as 3-control X gates (mcx), the adder logic is correct, so the bug is purely the API misuse. Histogram-only test: n/a (no circuit to run).

## Quality of passing circuits (as written / after transpiling to rz,sx,x,cx + linear coupling, opt 3)

| task | assistant | size | depth | 2q gates | 3q+ gates | gates | compiled cx | compiled depth |
|---|---|---|---|---|---|---|---|---|
| ghz5 | chatgpt | 5 | 5 | 4 | 0 | cx:4, h:1 | 10 | 13 |
| ghz5 | claude | 5 | 5 | 4 | 0 | cx:4, h:1 | 4 | 7 |
| ghz5 | gemini | 5 | 5 | 4 | 0 | cx:4, h:1 | 4 | 7 |
| ghz5 | perplexity | 5 | 5 | 4 | 0 | cx:4, h:1 | 10 | 13 |
| w3 | chatgpt | 6 | 6 | 2 | 1 | ccx:1, cry:1, cx:1, ry:1, x:2 | 13 | 30 |
| w3 | claude | 26 | 17 | 8 | 0 | cx:8, h:2, ry:3, t:4, tdg:3, x:6 | 12 | 27 |
| w3 | gemini | 7 | 7 | 3 | 0 | ch:1, cx:2, ry:1, x:3 | 6 | 16 |
| w3 | perplexity | 9 | 7 | 5 | 0 | cx:5, ry:3, x:1 | 7 | 16 |
| qft4 | chatgpt | 12 | 8 | 8 | 0 | cp:6, h:4, swap:2 | 17 | 35 |
| qft4 | claude | 36 | 22 | 14 | 0 | cx:12, h:4, p:18, swap:2 | 15 | 32 |
| qft4 | gemini | 12 | 8 | 8 | 0 | cp:6, h:4, swap:2 | 15 | 33 |
| qft4 | perplexity | 12 | 8 | 8 | 0 | cp:6, h:4, swap:2 | 15 | 33 |
| iqft3 | chatgpt | 7 | 6 | 4 | 0 | cp:3, h:3, swap:1 | 7 | 17 |
| iqft3 | claude | 19 | 16 | 7 | 0 | cx:6, h:3, p:9, swap:1 | 9 | 18 |
| iqft3 | gemini | 7 | 6 | 4 | 0 | cp:3, h:3, swap:1 | 9 | 19 |
| iqft3 | perplexity | 7 | 6 | 4 | 0 | cp:3, h:3, swap:1 | 9 | 19 |
| grover3 | chatgpt | 43 | 21 | 0 | 4 | ccx:4, h:23, x:16 | 37 | 94 |
| grover3 | claude | 43 | 21 | 0 | 4 | ccx:4, h:23, x:16 | 37 | 94 |
| grover3 | gemini | 43 | 21 | 0 | 4 | ccx:4, h:23, x:16 | 37 | 94 |
| grover3 | perplexity | 43 | 21 | 0 | 4 | ccx:4, h:23, x:16 | 37 | 94 |
| toffoli | chatgpt | 19 | 16 | 10 | 0 | cx:10, h:2, t:4, tdg:3 | 9 | 23 |
| toffoli | claude | 15 | 11 | 6 | 0 | cx:6, h:2, t:4, tdg:3 | 7 | 19 |
| toffoli | gemini | 15 | 11 | 6 | 0 | cx:6, h:2, t:4, tdg:3 | 7 | 19 |
| toffoli | perplexity | 15 | 11 | 6 | 0 | cx:6, h:2, t:4, tdg:3 | 7 | 19 |
| adder2 | claude | 108 | 90 | 72 | 2 | ccx:2, cx:72, h:4, p:30 | 121 | 162 |
| adder2 | gemini | 9 | 7 | 2 | 5 | ccx:5, cx:2, x:2 | 45 | 96 |
| adder2 | perplexity | 8 | 8 | 2 | 6 | ccx:6, cx:2 | 58 | 109 |

## Adder under a strict {x, cx, ccx} reading of the spec (informational, not scored)

- chatgpt: n/a (does not build)
- claude: FAIL (uses {'h': 4, 'p': 30})
- gemini: PASS
- perplexity: PASS

## Reference verification

- ghz5: statevector == (|00000>+|11111>)/sqrt2
- w3: statevector == (|001>+|010>+|100>)/sqrt3
- qft4: unitary == explicit DFT matrix e^{2pi i xk/16}/4 (exact) == QFTGate(4)
- iqft3: unitary == DFT(8)^dagger (exact) == QFTGate(3).inverse()
- grover3: statevector == numpy (DO)^2 H|000>, P(|101>) = 0.945312
- toffoli: unitary == CCXGate (exact, incl. global phase); gates within {h,t,tdg,s,sdg,cx}
- adder2: unitary == 32x32 permutation from exhaustive truth table (a, (a+b) mod 4, c XOR carry)

Per-circuit HTML reports: `results/reports/<assistant>_<task>.html`.
