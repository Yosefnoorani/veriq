# Veriq Bench: Proof-Checked Evaluation of LLM-Written Quantum Circuits and of the Tests That Judge Them

*Draft v0.1, 2026-10-28. Not peer reviewed. Every number comes from the committed Veriq runs. Numbers marked † were
produced in the hard round or in Stage 1 (2026-10-27/28) and were **not recomputed** for this draft; every other number
was recomputed by `veriq bench run` / `veriq bench corpus-eval` on 2026-10-28 (Asia/Jerusalem).*

## Abstract

Benchmarks for LLM-generated quantum code usually decide correctness by running unit tests that sample a circuit's output
histogram from |0…0⟩. We ask how much that judge misses. Veriq Bench v0.1 has 7 hard circuit-construction tasks
(≤ 6 qubits) with exact references, hard gate-set/coupling/no-ancilla constraints and a fixed CX cost model, plus a corpus of
1036 single-point mutants of 28 verified-correct circuits written by four public chat assistants. Correctness is decided by
a formal equivalence proof (MQT QCEC plus exact operator/state checks), not by sampling. On the corpus, a standard
4096-shot Aer histogram test from |0…0⟩ catches **327 of 966 (33.9%)** genuinely wrong mutants. An exact all-basis
truth-table check raises this to **927/966 (96.0%)**. The remaining **39** mutants have, for every computational-basis input,
exactly the reference's output distribution, so no measurement-from-basis-states test can detect them; the proof catches
**966/966** with **0/98** false positives. On the tasks, all four assistants' first answers were proven correct and compliant
(28/28), but their CX cost differs by up to **18.6×** from the cheapest proven-equivalent circuit for the same task.
The benchmark, its runner, and a detector-scoring harness are released as data plus two commands.

## 1 Introduction

LLMs now write Qiskit code well enough that benchmarks such as Qiskit HumanEval [1] score them by executing generated code
against unit tests. For circuits, "the test passes" usually means "the measured histogram from |0…0⟩ is close to the expected
one". That check has two blind spots. It only exercises one input state, so an oracle that is wrong on other inputs passes;
and it compares probabilities, so phase errors that cancel in |amplitude|² are invisible. Both are common in exactly the
circuits people ask LLMs for (oracles, arithmetic, phase estimation), where the circuit is later used as a subroutine on
superposed inputs.

Formal equivalence checking of quantum circuits is mature [2, 3, 4]. Veriq Bench connects the two: it scores LLM output with
proofs, and it scores *the test methods themselves* against a labelled bug corpus. Contributions:

1. **Tasks** (§3.1): 7 tasks with exact references, constraints, and a fixed, documented cost model, scored by
   `veriq bench run --model-outputs DIR` (proof, constraint compliance, CX/depth, gap to the best proven-equivalent CX).
2. **Bug corpus** (§3.2): 1036 mutants with ground-truth equivalence labels and per-detector detection labels, scored by
   `veriq bench corpus-eval --detector X` for any detector `fn(candidate, reference, mode) -> bool | None`.
3. **Results** (§4) for four chat assistants and five detectors, and a toolchain hazard: Qiskit's default
   `qubits_initially_zero=True` makes transpilation preserve results from |0…0⟩ but not the unitary [5].

## 2 Related work

**LLM quantum-code benchmarks.** Qiskit HumanEval [1] (arXiv 2406.14712) adapts HumanEval to Qiskit: the paper describes
101 tasks (the released dataset [1b] has more) checked by unit tests, and reports the best pass@1 of 46.53% for
granite-8b-code-qk, the model of the Qiskit Code Assistant [6]. QCircuitBench [7] evaluates LLMs on quantum-algorithm
design, including oracle construction. Both judge correctness by execution or simulation of the generated
program. Veriq Bench is much smaller, but it judges by proof and also measures how often execution-based judging is wrong.

**Equivalence checking.** Burgholzer and Wille [2] combine decision-diagram-based construction/alternating checks with random
stimuli simulation. They observe that a few random simulations (r = 16 in their setup) usually expose non-equivalence: in their
experiments removing a single random gate was detected by simulation with an average success rate of 85.2%. Peham et al. [3] add
ZX-calculus rewriting. Both are implemented in MQT QCEC [4], which Veriq calls. Our corpus measures the weaker judges used in
practice (one fixed input state, finite shots) rather than random stimuli.

**Mutation testing and bug benchmarks for quantum programs.** Mutation analysis is standard in classical testing [8]. For
quantum programs, Muskit [9] and QMutPy [10, 11] generate gate-level mutants of Qiskit programs to assess test suites; our
operators (delete gate, negate angle, π→3.14, flip CX, CP→CRZ, P→RZ) are in the same spirit and deliberately simple.
Bugs4Q [12] and QBugs [13] collect real bugs in Qiskit programs; Paltenghi and Pradel [14] study 223 real bugs in quantum
computing platforms and find 39.9% to be quantum-specific. Property-based testing of Q# programs [15] targets the same
oracle problem from the specification side. Unlike those corpora, every Veriq mutant carries a *proven* equivalence label and
the recorded outcome of four detectors.

**Synthesis and cost.** Our best-known CX values come from proven-equivalent re-compilation, including quantum Shannon
decomposition [16]; exact optimal synthesis [17] is out of reach for most of our tasks, so best-known values are upper bounds.

**Toolchain.** Qiskit [18] transpiles with `qubits_initially_zero=True` by default. Qiskit issue #13562 [5] (opened 2024-12-12,
Qiskit 1.3.0; closed 2025-01-08) reports a multi-controlled X that was no longer unitary-equivalent after transpilation; the
maintainer response explains that the default may use idle qubits as clean ancillas, which "is guaranteed to give you the correct
measurement results, but does not necessarily preserve the unitary", and that `qubits_initially_zero=False` avoids it.

## 3 Method

### 3.1 Tasks and scoring

| task | qubits | mode | requirement |
|---|---|---|---|
| maj5 | 6 | unitary | q5 ^= MAJ(q0..q4), no ancillas |
| cmul7 | 5 | unitary | controlled x → 7x mod 15 (x = 15 fixed) |
| qpe_t | 4 | state | QPE of T, 3 counting qubits, own inverse QFT; final state exactly \|1⟩\|001⟩ |
| c3x_linear | 4 | unitary | exact C3X, gates {cx,h,x,s,sdg,t,tdg,rz,p}, CX only between neighbours |
| reverse6_nn | 6 | unitary | reverse qubit order with nearest-neighbour CX only |
| bv22 | 6 | state | Bernstein–Vazirani for s = 22, ancilla returned to \|0⟩ |
| add3 | 6 | unitary | \|a⟩\|b⟩ → \|a⟩\|a+b mod 8⟩ with {x,cx,ccx,mcx}, no ancillas |

The prompt forbids library algorithm circuits (QFT, PhaseEstimation, arithmetic, UnitaryGate, StatePreparation, …).
References are verified against the exhaustive truth table (unitary tasks) or the analytic state.

*Correctness.* Unitary tasks require the full operator to equal the reference up to global phase (QCEC, or exact operator
comparison at this size). State tasks require the output state from |0…0⟩ to equal the reference state up to global phase.
*Compliance.* Gate set, coupling, qubit count, no measurement/reset, and no black-box gates. **PASS = correct ∧ compliant.**
*Cost.* CX count and depth after `transpile(optimization_level=1, basis_gates=[cx,rz,sx,x], seed_transpiler=2026)`, with a
linear coupling map for c3x_linear and reverse6_nn and `qubits_initially_zero=False` for unitary tasks (`True` for state tasks).
*Gap.* For each PASS submission, CX minus the best-known CX: the lowest CX of any circuit that `veriq optimize` **proved**
equivalent to a correct submission (Qiskit levels 0–3 over seeds, plus exact resynthesis for ≤ 6 qubits). We also report each
submission's own proven-optimized CX.

### 3.2 Bug corpus

From the 28 correct hard-round circuits we generated 1036 mutants (seed 2026, ≤ 30 per operator per circuit) with six
operators. Each mutant is labelled `equivalent` by proof (70 equivalent, 966 wrong) and assigned a study class by what the
weakest detector that finds it is: `caught_by_histogram` (Aer, 4096 shots from |0…0⟩, two-sample test vs the reference),
`missed_by_histogram_caught_by_truth_table` (only an exact sweep over all basis inputs sees it),
`proof_only_sampling_too_weak` (the |0…0⟩ distribution differs, but below what 4096 shots resolve), and
`proof_only_invisible_to_sampling` (every basis input gives exactly the reference distribution). The 70 equivalent mutants plus
the 28 originals form 98 negatives for the false-positive rate. Mutants are stored as OpenQASM 2 with stable custom-gate names,
and every file is hashed in `MANIFEST.json`.

### 3.3 Submissions

The hard-round prompt was pasted once, on 2026-10-27, into a new chat of four public web assistants: ChatGPT (free tier,
"Think" on), Claude (free tier, default model), Gemini (Pro) and Perplexity (free tier, default). The first answer was kept verbatim:
no retries, no edits. **The exact model versions were not shown by the web UIs and were not recorded; they are unknown.**

## 4 Results

### 4.1 Tasks

All 28 submissions are proven correct and compliant (recomputed; the hard round† also had 28/28 PASS).

| assistant | PASS | CX total (opt-1) | proven-optimized CX total | best-known total | CX / best (geo-mean over 7 tasks) |
|---|---|---:|---:|---:|---:|
| Gemini | 7/7 | 564 | 483 | 405 | 1.53× |
| Claude | 7/7 | 1784 | 1354 | 405 | 1.89× |
| Perplexity | 7/7 | 1538 | 643 | 405 | 1.99× |
| ChatGPT | 7/7 | 1594 | 644 | 405 | 2.12× |

Best-known CX per task: maj5 239, cmul7 60, qpe_t 9, c3x_linear 24, reverse6_nn 45, bv22 3, add3 25. The largest gaps are
ChatGPT's and Perplexity's cmul7 (1116 CX vs 60, 18.6×; their own proven-optimized versions reach 236), Claude's maj5 (1312 vs
239, 5.49×) and ChatGPT's and Gemini's c3x_linear (150 vs 24, 6.25×). Claude's c3x_linear meets the best known (24) and Gemini's
cmul7 (70) is the source of the 60-CX best. Across all 28, verified optimization lowers total CX from 5480 to 3124.
Correctness does not separate these assistants on this task set; cost does.

### 4.2 Detectors on the corpus

| detector | recall on 966 wrong mutants | false positives (98) | proof-only-invisible (39) |
|---|---:|---:|---:|
| histogram (Aer 4096 shots, \|0…0⟩) | 327 (33.9%) | 0 | 0 |
| zero-state (exact distribution, \|0…0⟩) | 331 (34.3%) | 0 | 0 |
| all-basis (exact distribution, every basis input) | 927 (96.0%) | 0 | 0 |
| proof (QCEC / exact operator or state) | 966 (100%) | 0 | 39 |
| veriq (full `veriq check` pipeline) | 966 (100%) | 0 | 39 |

All four built-in detectors reproduce the labels recorded in the hard round exactly (agreement 1.000). Even infinite shots from
|0…0⟩ (zero-state) gain only the 4 `sampling_too_weak` mutants: the histogram's main limit is the single input state, not
shot noise. The 39 invisible mutants are mostly negated or deleted phase gates (28 negate_angle, 11 delete_gate†, per the hard-round
breakdown) whose effect is a relative phase between basis states. Histogram recall by operator (recomputed): flip_cx 45/296 (15.2%),
delete_gate 222/574 (38.7%), negate_angle 48/76 (63.2%), cp_to_crz 12/12, pi_as_3.14 0/8; p_to_rz produced only equivalent mutants.

### 4.3 Toolchain hazard†

With Qiskit's default `qubits_initially_zero=True`, transpilation changed the unitary of 5 of the 28 correct circuits
(ChatGPT add3 and maj5, Gemini maj5, Perplexity add3 and maj5) while leaving every |0…0⟩ histogram unchanged: idle qubits were
borrowed as clean ancillas during `mcx` synthesis, the behaviour documented in [5]. The benchmark's cost model therefore uses
`qubits_initially_zero=False` for unitary tasks. (Hard-round result, not recomputed here.)

### 4.4 Localization and repair (Stage 1)†

On the 958 non-equivalent, single-gate mutants that remain once the equivalent ones are excluded, Veriq's region report contains the injected
mutation in 847/958 (88.4%) cases, and is a valid single-gate fix location in 98.5%. An offline demo fixer that knows the mutation
vocabulary repaired 152/188 sampled mutants to PASS; it tests the plumbing, not LLM repair skill. These numbers come from Stage 1 and were
not recomputed.

## 5 Threats to validity

* **Tiny sample.** Four assistants, one prompt, one attempt each, one day. No pass@k, no variance estimate. Leaderboard ranks
  are not statistically meaningful.
* **Unknown model versions.** The web UIs did not expose versions, and free tiers may route requests to different models.
* **Synthetic bugs.** Six single-point operators, not a sample of real LLM bugs. The 34% histogram recall depends on the
  operator mix (e.g. flip_cx mutants are mostly invisible from |0…0⟩). Recall on real bugs could be higher or lower.
* **Correlated corpus.** Mutants of the same circuit are not independent, and ChatGPT and Perplexity have identical CX counts on 6 of
  7 tasks, which suggests very similar circuits.
* **Small circuits.** ≤ 6 qubits, so exact all-basis and operator checks are cheap. At scale, an all-basis sweep is exponential and
  proofs can time out. QCEC sometimes returned "no conclusion" (the ZX checker said not equivalent, simulation said probably
  equivalent); at ≤ 10 qubits Veriq then falls back to an exact dense-operator check, which does not exist at scale.
* **Best-known ≠ optimal.** Gaps are relative to upper bounds found by our own optimizer.
* **Tool bias.** The detectors and the proof are part of Veriq. The proof detector agrees with the ground truth by construction
  (the labels come from proofs). The independent evidence is that the exact all-basis check never contradicts it (0 false
  positives, every all-basis detection also proof-detected).
* **Execution.** `bench run` imports submission code in-process; it is not a sandbox.

## 6 Reproducibility

```bash
git clone <repo> && cd veriq && python -m venv .venv && .venv/bin/pip install -e .[dev]
.venv/bin/python benchmark/veriqbench/build_v0_1.py               # rebuilds v0.1/ byte-identically (MANIFEST.json)
.venv/bin/veriq bench run -m benchmark/veriqbench/v0.1/submissions/hard-round-2026-10-27 \
    -o benchmark/veriqbench/results/run_hard-round-2026-10-27.json        # ~45 s
for d in histogram zero-state all-basis proof veriq; do
  .venv/bin/veriq bench corpus-eval -d $d -o benchmark/veriqbench/results/corpus_eval_$d.json; done
.venv/bin/veriq bench leaderboard --run benchmark/veriqbench/results/run_hard-round-2026-10-27.json \
    --corpus-eval benchmark/veriqbench/results/corpus_eval_*.json --out-dir benchmark/veriqbench/leaderboard
```

Versions used: Python 3.13.5, Qiskit 2.6.1, qiskit-aer 0.18.2, mqt.qcec 3.11.0, veriq 0.1.0. Seeds: mutants 2026,
transpiler 2026, histogram 7. The data schema is in `benchmark/veriqbench/SCHEMA.md`, the tests in `tests/test_bench.py`.

## References

All entries were checked to exist (arXiv/DOI/GitHub pages opened on 2026-10-28).

1. S. Vishwakarma et al., "Qiskit HumanEval: An Evaluation Benchmark for Quantum Code Generative Models," arXiv:2406.14712, 2024. https://arxiv.org/abs/2406.14712
   1b. Dataset: https://github.com/qiskit-community/qiskit-human-eval
2. L. Burgholzer and R. Wille, "Advanced Equivalence Checking for Quantum Circuits," IEEE TCAD, 2021. doi:10.1109/TCAD.2020.3032630. https://arxiv.org/abs/2004.08420
3. T. Peham, L. Burgholzer and R. Wille, "Equivalence Checking of Quantum Circuits with the ZX-Calculus," IEEE JETCAS, 2022. doi:10.1109/JETCAS.2022.3202204. https://arxiv.org/abs/2208.12820
4. MQT QCEC, Munich Quantum Toolkit. https://github.com/munich-quantum-toolkit/qcec
5. Qiskit issue #13562, "Multi-Controlled CX & Custom basis transpilation," 2024. https://github.com/Qiskit/qiskit/issues/13562
6. N. Dupuis et al., "Qiskit Code Assistant: Training LLMs for generating Quantum Computing Code," arXiv:2405.19495, 2024. https://arxiv.org/abs/2405.19495
7. R. Yang et al., "QCircuitBench: A Large-Scale Dataset for Benchmarking Quantum Algorithm Design," arXiv:2410.07961, 2024. https://arxiv.org/abs/2410.07961
8. Y. Jia and M. Harman, "An Analysis and Survey of the Development of Mutation Testing," IEEE TSE 37(5), 2011. doi:10.1109/TSE.2010.62
9. E. Mendiluze, S. Ali, P. Arcaini and T. Yue, "Muskit: A Mutation Analysis Tool for Quantum Software Testing," ASE 2021 (Tool Demos), pp. 1266–1270. doi:10.1109/ASE51524.2021.9678563. https://github.com/Simula-COMPLEX/muskit
10. D. Fortunato, J. Campos and R. Abreu, "QMutPy: A Mutation Testing Tool for Quantum Algorithms and Applications in Qiskit," ISSTA 2022 (Tool). doi:10.1145/3533767.3543296
11. D. Fortunato, J. Campos and R. Abreu, "Mutation Testing of Quantum Programs: A Case Study With Qiskit," IEEE TQE, 2022. doi:10.1109/TQE.2022.3195061
12. P. Zhao, J. Zhao, Z. Miao and S. Lan, "Bugs4Q: A Benchmark of Real Bugs for Quantum Programs," ASE 2021. doi:10.1109/ASE51524.2021.9678908. https://arxiv.org/abs/2108.09744
13. J. Campos and A. Souto, "QBugs: A Collection of Reproducible Bugs in Quantum Algorithms and a Supporting Infrastructure to Enable Controlled Quantum Software Testing and Debugging Experiments," arXiv:2103.16968, 2021. https://arxiv.org/abs/2103.16968
14. M. Paltenghi and M. Pradel, "Bugs in Quantum Computing Platforms: An Empirical Study," OOPSLA 2022. doi:10.1145/3527330. https://arxiv.org/abs/2110.14560
15. S. Honarvar, M. R. Mousavi and R. Nagarajan, "Property-based Testing of Quantum Programs in Q#," ICSE Workshops 2020. doi:10.1145/3387940.3391459
16. V. V. Shende, S. S. Bullock and I. L. Markov, "Synthesis of Quantum-Logic Circuits," IEEE TCAD, 2006. doi:10.1109/TCAD.2005.855930. https://arxiv.org/abs/quant-ph/0406176
17. M. Amy, D. Maslov, M. Mosca and M. Roetteler, "A Meet-in-the-Middle Algorithm for Fast Synthesis of Depth-Optimal Quantum Circuits," IEEE TCAD, 2013. doi:10.1109/TCAD.2013.2244643. https://arxiv.org/abs/1206.0758
18. A. Javadi-Abhari et al., "Quantum computing with Qiskit," arXiv:2405.08810, 2024. https://arxiv.org/abs/2405.08810
