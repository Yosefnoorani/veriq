# Real bugs: AI-written quantum code that passes its tests but is wrong

We ran Veriq on **published model solutions from public quantum-coding benchmarks**. Every number on this page
was produced by the scripts in this directory from the files in `raw/`. No model was re-run and no result was
invented.

## Headline

> **Of 257 model-written circuits that pass their benchmark's own unit tests, at least 7 (2.7%) are provably
> wrong. Counting gates that fail only on superposed inputs, the figure is 14 (5.4%).**
>
> QuanBench (44-task set, GPT-4.1 at T=0.8, plus 117-task set, GPT-4o), published generations, manually reviewed.

| run (published generations) | tasks | samples | tests pass | Veriq-confirmed correct | wrong but passed: strict / incl. superposed | unverified |
|---|---|---|---|---|---|---|
| QuanBench44 · GPT-4.1 (T=0.8) | 44 | 220 | 85 (38.6%) | 62 (28.2%) | 0 / 5 | 18 |
| QuanBench117 · GPT-4o | 117 | 585 | 172 (29.4%) | 138 (23.6%) | 7 / 9 | 25 |
| **combined** | 161 | 805 | **257** | 200 | **7 (2.7%) / 14 (5.4%)** | 43 |

Sources: `results/headline.json` and `results/model_table.{json,md}`, with one row per task in `results/task_index.jsonl`.

### Definitions

- **tests pass**: the dataset's own `check()` passes, run with the dataset harness's semantics
  (`quanbench_capture.py`, Qiskit 0.46 as QuanBench targets).
- **wrong (strict)**: the circuit gives the wrong output distribution on an input the task cares about. That is
  the task's fixed input (usually |0…0⟩) or a computational-basis input of a gate the prompt asks for. The
  verdict was checked against the *prompt's* specification, not only the canonical solution
  (`spec_checks.py`, `results/spec_checks.json`).
- **wrong, superposed inputs only**: the prompt asks for a gate, and the circuit matches it on every basis input
  but not on superposed inputs. Example: the `ry(π/4)·cx·ry(−π/4)·cx` "controlled-Hadamard" is
  controlled-(H·Z). With control |1⟩ and target |+⟩, CH gives 01 with certainty and the candidate gives 11.
- **Veriq-confirmed correct**: proved equivalent to the canonical circuit by QCEC or an exact operator
  comparison (up to global phase), or judged correct in the manual review. The manual review accepts
  don't-cares such as a diagonal phase just before measurement, or a different but valid answer.
- **unverified**: tests pass but no verdict is counted. Reasons: no circuit was returned, Veriq could not decide
  (mid-circuit measurement), the task has no unique answer (variational or heuristic tasks), the difference
  is only a qubit-order convention (QFT bit order), the spec is ambiguous or self-inconsistent, or the case looks
  suspicious but is unconfirmed.

### The 14 cases

| task | sample | verdict | what is wrong |
|---|---|---|---|
| QB117-09 | 3 | wrong | QPE of X can only read 000 or 100; 57.3% of the candidate's mass is on impossible outcomes |
| QB117-13 | 1 | wrong | Simon s=11: the "oracle" makes the output always 00, so it carries no information about s |
| QB117-78 | 2 | wrong | Simon s=10: a constant oracle (only an X on the output register) |
| QB117-81 | 4 | wrong | Simon s=001: a 4-to-1 function, so the output support is 2 strings instead of 4 |
| QB117-114 | 0 | wrong | swap test of \|++⟩ vs \|00⟩ prepares \|+0⟩, so P(0)=0.75 instead of 0.625 |
| QB117-37 | 1, 2 | wrong | the "controlled-H" rotates the target even when the control is 0 (P(10)=0.146 from \|00⟩); the test only checks control=1 |
| QB44-37 | 0–4 | superposed only | controlled-(H·Z) instead of CH; the test only composes X on the control |
| QB117-37 | 0, 4 | superposed only | same construction |

`results/manual_review.json` holds every flagged passing sample (89 of them) with its verdict and a reason.

### Caveats (why this is a lower bound and not a precise rate)

- **Undercount.** A candidate that equals a *broken* canonical is counted as correct. 11 of the 117 QuanBench117
  canonicals and 1 of the 44 QuanBench44 canonicals fail their own tests under our harness. For tasks 05, 09, 21,
  28 and 43 we checked the prompt directly instead of trusting the canonical.
- **Scope.** There are 2 models and 1 generation run each (5 samples per task), from the published files
  that ship with QuanBench. QuanBench+ ships no generations, so it is not in the headline.
- **Not counted.** 43 passing samples have no verdict (see *unverified*). Counting them as correct would
  lower the share; counting them as wrong would be unjustified.
- **Sampling.** The harness uses Aer with unseeded shots, exactly as the dataset does, so a borderline
  statistical test could flip on a rerun. All Veriq verdicts are exact (QCEC or dense operator), not sampled.
- **Judgement calls.** QFT bit order (task 08) is treated as a convention and not counted. Task 21 (the prompt, the
  canonical and the tests disagree) and task 11 (two valid oracle readings) are *ambiguous*. Task 25 is
  *suspicious, unconfirmed*. None of these are counted as wrong.

## Qiskit HumanEval: how strong are the tests?

Qiskit HumanEval ships no model generations, so we measured **test strength** instead. For every task whose
canonical solution returns a circuit, we made small single-edit mutants (delete a gate, negate an angle, swap
the qubits of a 2-qubit gate, or write π as 3.14), ran the dataset's own `check()` on each, and asked Veriq
whether each surviving mutant is actually wrong.

<!-- HUMANEVAL_TABLE -->
| | normal | hard |
|---|---|---|
| Tasks in the run (of 151 per split) | 151 | 127 |
| Canonical returns a circuit and gets mutants | 64 | 57 |
| Mutants made | 311 | 278 |
| Killed by the dataset's own tests | 206 (66.2%) | 180 (64.7%) |
| **Survived the tests** | **105** (33.8%) | **98** (35.3%) |
| of which Veriq: equivalent (harmless) | 7 | 7 |
| of which Veriq: **different output state** (wrong) | **39** | **38** |
| of which Veriq: same \|0…0⟩ state, different unitary | 15 | 13 |
| of which undecided (>12 qubits, parameterised, non-unitary) | 44 | 40 |
| Tasks with a surviving state-changing mutant | 10 of 64 | 9 of 57 |
| Tasks with any surviving non-equivalent mutant | 13 of 64 | 12 of 57 |

*Partial run: 151 of 151 normal and 127 of 151 hard tasks so far.*
<!-- /HUMANEVAL_TABLE -->

Sources: `results/humaneval_mutants_summary.json` and the per-mutant rows in `raw/humaneval_mutants.jsonl`.
"Undecided" survivors are mostly circuits wider than 12 qubits, or parameterised or non-unitary circuits.

## Reproduce

```bash
# 1. capture (Qiskit 0.46 env; QuanBench at commit 562b6ee)
qb046/bin/python benchmark/real_bugs/quanbench_capture.py --quanbench Quanbench --problems QuanBench44.jsonl \
    --samples Quanbench_eval/generated/quanbench44/results_gpt-4.1_T0.8.jsonl \
    --out benchmark/real_bugs/raw/quanbench44_gpt-4.1_T0.8.capture.jsonl      # likewise canonical-only and 117/GPT-4o
# 2. compare with Veriq (Veriq venv); reads raw/*.capture.jsonl or the committed .gz copies
.venv/bin/python benchmark/real_bugs/quanbench_veriq.py
# 3. prompt-level spec checks, manual-review join, headline, model table
.venv/bin/python benchmark/real_bugs/spec_checks.py
.venv/bin/python benchmark/real_bugs/review.py          # fails if any flagged passing sample has no verdict
.venv/bin/python benchmark/real_bugs/model_table.py
# 4. HumanEval mutant audit (Qiskit 2.4.2 env, the dataset's requirements.txt)
qhe/bin/python benchmark/real_bugs/humaneval_mutants.py --dataset qiskit-human-eval \
    --out benchmark/real_bugs/raw/humaneval_mutants.jsonl
.venv/bin/python benchmark/real_bugs/humaneval_summary.py
```

`raw/*.capture.jsonl.gz` hold every circuit returned during the tests, serialised with QPY.
`raw/*.veriq.jsonl` hold the per-sample Veriq comparisons.

## Datasets and licences

| dataset | version used | licence | citation |
|---|---|---|---|
| [QuanBench](https://github.com/GuoXiaoYu1125/Quanbench) (QuanBench44, QuanBench117 and their published generations) | commit `562b6ee` | MIT, © 2026 QuanBench contributors | arXiv:2510.16779 |
| [Qiskit HumanEval](https://github.com/qiskit-community/qiskit-human-eval) (normal and hard) | commit `555f329` | Apache-2.0; use is also subject to the IBM Quantum terms of use (https://quantum.ibm.com/terms) | Vishwakarma et al., arXiv:2406.14712 (IEEE QCE 2024) |
| [QuanBench+](https://github.com/jawadkotaichh/quanbench-plus) | commit `2dfd1a8` | MIT, © 2026 Jawad Kotaich | arXiv:2604.08570 |

This directory redistributes **no prompts or canonical solutions**. `raw/` holds only the circuits the published
code returned during the tests (QPY), with task IDs, call-argument reprs and verdicts. These are derived data from
the MIT- and Apache-2.0-licensed datasets above, and the copyright notices are reproduced here.
