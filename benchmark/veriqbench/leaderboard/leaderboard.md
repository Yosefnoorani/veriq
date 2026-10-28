# Veriq Bench v0.1 leaderboard

Generated 2026-10-28T17:28:53+02:00 by `veriq bench leaderboard` from a `veriq bench run` of `hard-round-2026-10-27` (7 tasks). Versions: veriq 0.1.0, python 3.13.5, qiskit 2.6.1, mqt.qcec 3.11.0, qiskit_aer 0.18.2.

## Overall

| rank | model | pass (correct + compliant) | correct (proof) | compliant | CX total (passing tasks) | best proven CX (same tasks) | CX / best (geo-mean) |
|---|---|---|---|---|---|---|---|
| 1 | gemini | 7/7 | 7/7 | 7/7 | 564 | 405 | 1.53x |
| 2 | claude | 7/7 | 7/7 | 7/7 | 1784 | 405 | 1.89x |
| 3 | perplexity | 7/7 | 7/7 | 7/7 | 1538 | 405 | 1.99x |
| 4 | chatgpt | 7/7 | 7/7 | 7/7 | 1594 | 405 | 2.12x |

Ranked by tasks passed, then CX geo-mean ratio to the best proven-optimized circuit (lower is better).

## Correctness per task

| model | maj5 | cmul7 | qpe_t | c3x_linear | reverse6_nn | bv22 | add3 |
|---|---|---|---|---|---|---|---|
| gemini | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| claude | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| perplexity | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| chatgpt | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

PASS = proven correct (unitary or exact state) AND every task constraint satisfied.

## CX cost and gap to the best proven-optimized circuit

| model | maj5 | cmul7 | qpe_t | c3x_linear | reverse6_nn | bv22 | add3 |
|---|---|---|---|---|---|---|---|
| gemini | 240 (+1) | 70 (+10) | 15 (+6) | 150 (+126) | 45 (+0) | 3 (+0) | 41 (+16) |
| claude | 1312 (+1073) | 344 (+284) | 15 (+6) | 24 (+0) | 45 (+0) | 3 (+0) | 41 (+16) |
| perplexity | 240 (+1) | 1116 (+1056) | 15 (+6) | 94 (+70) | 45 (+0) | 3 (+0) | 25 (+0) |
| chatgpt | 240 (+1) | 1116 (+1056) | 15 (+6) | 150 (+126) | 45 (+0) | 3 (+0) | 25 (+0) |
| **best proven** | 239 | 60 | 9 | 24 | 45 | 3 | 25 |

Cost = CX after Qiskit opt-level 1 (basis cx/rz/sx/x, seed 2026, linear chain where required). (+gap) = CX above the best circuit PROVEN equivalent to a correct submission (`veriq optimize`); the best is an upper bound on the optimum, not the optimum.

## Proven-optimized CX of each submission

| model | maj5 | cmul7 | qpe_t | c3x_linear | reverse6_nn | bv22 | add3 | total |
|---|---|---|---|---|---|---|---|---|
| gemini | 240 | 60 | 9 | 85 | 45 | 3 | 41 | 483 |
| claude | 996 | 236 | 9 | 24 | 45 | 3 | 41 | 1354 |
| perplexity | 240 | 236 | 9 | 85 | 45 | 3 | 25 | 643 |
| chatgpt | 239 | 236 | 11 | 85 | 45 | 3 | 25 | 644 |

Cheapest compilation of that submission that the optimizer PROVED equivalent to it.

## Bug detection on the corpus

| detector | what it does | recall (wrong mutants) | false positives | undecided | missed_by_histogram_caught_by_truth_table | caught_by_histogram | proof_only_sampling_too_weak | proof_only_invisible_to_sampling |
|---|---|---|---|---|---|---|---|---|
| histogram | Aer sampling from \|0...0> (4096 shots, two-sample test vs the reference) | 327/966 = 33.9% | 0/98 | 0 | 0/596 | 327/327 | 0/4 | 0/39 |
| zero-state | exact output distribution from \|0...0> (infinite shots) | 331/966 = 34.3% | 0/98 | 0 | 0/596 | 327/327 | 4/4 | 0/39 |
| all-basis | exact output distribution from EVERY computational-basis input (truth table) | 927/966 = 96.0% | 0/98 | 0 | 596/596 | 327/327 | 4/4 | 0/39 |
| proof | formal equivalence proof (QCEC / operator; exact state equality in state mode) | 966/966 = 100.0% | 0/98 | 0 | 596/596 | 327/327 | 4/4 | 39/39 |
| veriq | the full `veriq check` suite against the reference (semantic checks, no constraints) | 966/966 = 100.0% | 0/98 | 0 | 596/596 | 327/327 | 4/4 | 39/39 |

Recall on genuinely wrong mutants; false positives on equivalent mutants + the correct originals. Columns per study class (assigned in the hard round) show detected/total.

## Provenance

- Round `hard-round-2026-10-27`; prompt date 2026-10-27; same prompt pasted once into a new chat of each web assistant; first answer kept verbatim; no retries, no edits.
- chatgpt: ChatGPT (free, Think) via public web chat; model version: unknown (not shown/recorded by the web UI at the time); date 2026-10-27; attempts 1
- claude: Claude (free, default model) via public web chat; model version: unknown (not shown/recorded by the web UI at the time); date 2026-10-27; attempts 1
- gemini: Gemini (Pro) via public web chat; model version: unknown (not shown/recorded by the web UI at the time); date 2026-10-27; attempts 1
- perplexity: Perplexity (free, default) via public web chat; model version: unknown (not shown/recorded by the web UI at the time); date 2026-10-27; attempts 1
