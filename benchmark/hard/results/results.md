# Veriq hard round: 28 LLM-written circuits (4 assistants x 7 non-standard tasks)

Generated 2026-10-27T20:20:15+02:00. Prompt sent 2026-10-27. Total 28/28 PASS.

## Verdicts

| assistant | maj5 | cmul7 | qpe_t | c3x_linear | reverse6_nn | bv22 | add3 | score |
|---|---|---|---|---|---|---|---|---|
| chatgpt | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |
| claude | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |
| gemini | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |
| perplexity | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |

Checks per task: proof (QCEC, matrix fallback) or exact state fidelity (qpe_t, bv22), counterexample search, Aer statistical test, no-black-boxes; c3x_linear and reverse6_nn also enforce the gate set and a linear coupling map on the circuit as written; add3 enforces {x,cx,ccx,mcx}.

## Failures

None.

## Cost (CX count) — as written / transpiled to {cx,rz,sx,x} opt 1 all-to-all / on a linear chain

| task | chatgpt | claude | gemini | perplexity | spread |
|---|---|---|---|---|---|
| maj5 | 0 / 240 | 0 / 1312 | 0 / 240 | 0 / 240 | 5.5x |
| cmul7 | 0 / 1116 | 22 / 344 | 10 / 70 | 0 / 1116 | 15.9x |
| qpe_t | 3 / 15 | 0 / 15 | 0 / 15 | 3 / 15 | 1.0x |
| c3x_linear | 202 / 150 / lin 150 | 24 / 24 / lin 24 | 202 / 150 / lin 150 | 126 / 94 / lin 94 | 6.2x |
| reverse6_nn | 45 / 45 / lin 45 | 45 / 45 / lin 45 | 45 / 45 / lin 45 | 45 / 45 / lin 45 | 1.0x |
| bv22 | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 1.0x |
| add3 | 3 / 25 | 3 / 41 | 3 / 41 | 3 / 25 | 1.6x |

Spread = max/min of the transpiled CX count (linear chain for c3x_linear and reverse6_nn).

## Diagnostics

- chatgpt qpe_t: inverse-QFT block alone equals QFTGate(3).inverse() as a unitary: True
- claude qpe_t: inverse-QFT block alone equals QFTGate(3).inverse() as a unitary: True
- gemini qpe_t: inverse-QFT block alone equals QFTGate(3).inverse() as a unitary: True
- perplexity qpe_t: inverse-QFT block alone equals QFTGate(3).inverse() as a unitary: True
- chatgpt c3x_linear: global phase vs. exact C3X = 0.0 rad (gates: {'cx': 202, 'h': 2, 'p': 15})
- claude c3x_linear: global phase vs. exact C3X = 0.0 rad (gates: {'cx': 24, 'h': 2, 'p': 15})
- gemini c3x_linear: global phase vs. exact C3X = -0.19635 rad (gates: {'cx': 202, 'h': 2, 'rz': 15})
- perplexity c3x_linear: global phase vs. exact C3X = 0.0 rad (gates: {'cx': 126, 'h': 2, 'p': 15})

### Toolchain finding: `qubits_initially_zero` hazard

Qiskit's default `transpile()` assumes every qubit starts in |0> and lets HighLevelSynthesis borrow still-untouched qubits as *clean* ancillas when it decomposes an `mcx`. The compiled circuit is then correct from |0...0> but NOT equal as a unitary, so `transpile(oracle).to_gate()` reused inside a larger algorithm would be silently wrong. A histogram from |0...0> can never see this; the unitary proof does. Veriq now compiles unitary-mode tasks with `qubits_initially_zero=False` and flags the hazard.

Circuits where the default compile is not unitary-equivalent (5/28): chatgpt/add3, chatgpt/maj5, gemini/maj5, perplexity/add3, perplexity/maj5. The LLM circuits themselves are correct.

## Mutation study: which injected bugs does sampling miss?

1036 mutants (seed 2026, up to 30 per operator per circuit).

| operator | caught_by_histogram | missed_by_histogram_caught_by_truth_table | proof_only_sampling_too_weak | proof_only_invisible_to_sampling | equivalent_mutant | undecided |
|---|---|---|---|---|---|---|
| delete_gate | 222 | 341 | 0 | 11 | 5 | 0 |
| negate_angle | 48 | 0 | 0 | 28 | 8 | 0 |
| pi_as_3.14 | 0 | 4 | 4 | 0 | 0 | 0 |
| flip_cx | 45 | 251 | 0 | 0 | 0 | 0 |
| cp_to_crz | 12 | 0 | 0 | 0 | 12 | 0 |
| p_to_rz | 0 | 0 | 0 | 0 | 45 | 0 |
| **total** | **327** | **596** | **4** | **39** | **70** | **0** |

| task | caught_by_histogram | missed_by_histogram_caught_by_truth_table | proof_only_sampling_too_weak | proof_only_invisible_to_sampling | equivalent_mutant | undecided |
|---|---|---|---|---|---|---|
| maj5 | 21 | 54 | 0 | 0 | 0 | 0 |
| cmul7 | 70 | 72 | 0 | 0 | 0 | 0 |
| qpe_t | 89 | 0 | 4 | 0 | 25 | 0 |
| c3x_linear | 67 | 192 | 0 | 39 | 45 | 0 |
| reverse6_nn | 0 | 240 | 0 | 0 | 0 | 0 |
| bv22 | 80 | 0 | 0 | 0 | 0 | 0 |
| add3 | 0 | 38 | 0 | 0 | 0 | 0 |

**Headline:** of 966 genuinely wrong mutants, the standard Aer histogram from |0...0> catches only 327 (34%). 596 more need an exhaustive basis-input sweep, and 43 (4.5%) are caught by the formal proof alone.

Classes: *caught_by_histogram* = the usual Aer test from |0...0> FAILs; *missed_by_histogram_caught_by_truth_table* = only an exhaustive basis-input sweep sees it; *proof_only_sampling_too_weak* = the |0...0> distribution differs but below the statistical threshold (4096 shots, TVD 0.05); *proof_only_invisible_to_sampling* = every basis input gives exactly the reference distribution, so no such sampling test can ever detect it.

### Examples of proof-only bugs (43 total)

- chatgpt/qpe_t: pi written as 3.14 in all 6 angles — proof FAIL, Aer histogram PASS, exact TVD from |0..0> 1e-06
- chatgpt/c3x_linear: delete #6 p(2,) — proof FAIL, Aer histogram PASS, exact TVD from |0..0> 0.0, worst TVD over all basis inputs 0.0
- chatgpt/c3x_linear: negate #1 p(0.3927)(0,) — proof FAIL, Aer histogram PASS, exact TVD from |0..0> 0.0, worst TVD over all basis inputs 0.0

## Reference verification

- maj5: unitary == 64x64 permutation from the exhaustive truth table (exact, incl. phase)
- cmul7: unitary == 32x32 permutation from the exhaustive truth table (exact, incl. phase)
- c3x_linear: unitary == 16x16 permutation from the exhaustive truth table (exact, incl. phase)
- reverse6_nn: unitary == 64x64 permutation from the exhaustive truth table (exact, incl. phase)
- add3: unitary == 64x64 permutation from the exhaustive truth table (exact, incl. phase)
- qpe_t: statevector == |9> (basis index 9, up to global phase)
- bv22: statevector == |22> (basis index 22, up to global phase)

Per-circuit HTML reports: `results/reports/<assistant>_<task>.html`. All mutants: `results/mutation.json`.
