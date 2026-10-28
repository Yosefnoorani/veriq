# Verified CX optimization of the hard-round circuits

Generated 2026-10-28T16:53:55+02:00 by `benchmark/optimize/run_optimize.py` (budget 120s per circuit, 4 seeds; total 37.2s).

* **before** = the hard-round cost metric: Qiskit `optimization_level=1`, seed 2026, `qubits_initially_zero=False`, basis cx/rz/sx/x, linear coupling for c3x_linear and reverse6_nn.
* **after** = cheapest candidate (CX, then depth) that `decide_equivalence` PROVED equivalent to the assistant's own circuit. Unproven candidates are never used.
* The optimizer preserves what the circuit does; a circuit that FAILed the hard round is still wrong after optimization.

Proven result for **28/28** circuits; CX before 5480 -> after 3124 on those.

| assistant | task | mode | hard verdict | CX before (opt1) | CX after | saved | depth after | proof | winning config |
|---|---|---|---|---:|---:|---:|---:|---|---|
| chatgpt | maj5 | unitary | PASS | 240 | 239 | 1 | 512 | operator | opt2 seed 2026 |
| chatgpt | cmul7 | unitary | PASS | 1116 | 236 | 880 | 723 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| chatgpt | qpe_t | state | PASS | 15 | 11 | 4 | 57 | mps-exact-overlap | opt1 seed 2026 +state-resynthesis |
| chatgpt | c3x_linear | unitary | PASS | 150 | 85 | 65 | 233 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| chatgpt | reverse6_nn | unitary | PASS | 45 | 45 | 0 | 27 | operator | opt0 seed 2026 |
| chatgpt | bv22 | state | PASS | 3 | 3 | 0 | 9 | partition+clifford-tableau | opt2 seed 2026 |
| chatgpt | add3 | unitary | PASS | 25 | 25 | 0 | 48 | operator | opt2 seed 2026 |
| claude | maj5 | unitary | PASS | 1312 | 996 | 316 | 2996 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| claude | cmul7 | unitary | PASS | 344 | 236 | 108 | 723 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| claude | qpe_t | state | PASS | 15 | 9 | 6 | 50 | mps-exact-overlap | opt3 seed 2026 +state-resynthesis |
| claude | c3x_linear | unitary | PASS | 24 | 24 | 0 | 25 | operator | opt1 seed 2026 |
| claude | reverse6_nn | unitary | PASS | 45 | 45 | 0 | 18 | operator | opt0 seed 2026 |
| claude | bv22 | state | PASS | 3 | 3 | 0 | 9 | partition+clifford-tableau | opt2 seed 2026 |
| claude | add3 | unitary | PASS | 41 | 41 | 0 | 73 | operator | opt2 seed 2026 |
| gemini | maj5 | unitary | PASS | 240 | 240 | 0 | 501 | operator | opt2 seed 2026 |
| gemini | cmul7 | unitary | PASS | 70 | 60 | 10 | 137 | operator | opt2 seed 2026 |
| gemini | qpe_t | state | PASS | 15 | 9 | 6 | 50 | mps-exact-overlap | opt3 seed 2026 +state-resynthesis |
| gemini | c3x_linear | unitary | PASS | 150 | 85 | 65 | 233 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| gemini | reverse6_nn | unitary | PASS | 45 | 45 | 0 | 27 | operator | opt0 seed 2026 |
| gemini | bv22 | state | PASS | 3 | 3 | 0 | 9 | partition+clifford-tableau | opt2 seed 2026 |
| gemini | add3 | unitary | PASS | 41 | 41 | 0 | 75 | operator | opt2 seed 2026 |
| perplexity | maj5 | unitary | PASS | 240 | 240 | 0 | 501 | operator | opt2 seed 2026 |
| perplexity | cmul7 | unitary | PASS | 1116 | 236 | 880 | 723 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| perplexity | qpe_t | state | PASS | 15 | 9 | 6 | 50 | mps-exact-overlap | opt3 seed 2026 +state-resynthesis |
| perplexity | c3x_linear | unitary | PASS | 94 | 85 | 9 | 233 | operator | opt3 seed 2026 +unitary-resynthesis (QSD) |
| perplexity | reverse6_nn | unitary | PASS | 45 | 45 | 0 | 27 | operator | opt0 seed 2026 |
| perplexity | bv22 | state | PASS | 3 | 3 | 0 | 9 | partition+clifford-tableau | opt2 seed 2026 |
| perplexity | add3 | unitary | PASS | 25 | 25 | 0 | 48 | operator | opt2 seed 2026 |

## Totals per assistant (circuits with a proven result)

| assistant | circuits | CX before | CX after | saved |
|---|---:|---:|---:|---:|
| chatgpt | 7 | 1594 | 644 | 950 (60%) |
| claude | 7 | 1784 | 1354 | 430 (24%) |
| gemini | 7 | 564 | 483 | 81 (14%) |
| perplexity | 7 | 1538 | 643 | 895 (58%) |

## Totals per task

| task | circuits | CX before | CX after | saved |
|---|---:|---:|---:|---:|
| maj5 | 4 | 2032 | 1715 | 317 |
| cmul7 | 4 | 2646 | 768 | 1878 |
| qpe_t | 4 | 60 | 38 | 22 |
| c3x_linear | 4 | 418 | 279 | 139 |
| reverse6_nn | 4 | 180 | 180 | 0 |
| bv22 | 4 | 12 | 12 | 0 |
| add3 | 4 | 132 | 132 | 0 |
