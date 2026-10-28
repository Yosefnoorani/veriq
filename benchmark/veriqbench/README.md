# Veriq Bench v0.1

A small, versioned, reproducible benchmark for **LLM-written quantum circuits**, built from the Veriq hard round
(2026-10-27). It has two parts:

1. **Tasks**: 7 hard circuit-construction tasks with exact references, hard constraints and a fixed cost model.
   `veriq bench run` scores a new set of model outputs. Correctness is decided by an equivalence proof, not by sampling.
2. **Bug corpus**: 1036 single-mutation variants of the 28 verified-correct hard-round circuits, labelled with ground truth
   (equivalent or not) and with what each detection method caught. `veriq bench corpus-eval` scores a detection method.

```
v0.1/
  prompt.md               the verbatim hard-round prompt (all 7 tasks)
  references.py           reference builders (each verified exhaustively / analytically)
  tasks/<task>.json       prompt, reference, constraints, correctness, cost model   (7)
  best_known.json         lowest proven-equivalent CX per task (upper bound, not optimum)
  corpus/mutants.jsonl    1036 mutants (task, source assistant, mutation class, location, equivalent, detected_by, qasm)
  corpus/correct.jsonl    the 28 correct circuits
  submissions/hard-round-2026-10-27/   the 4 assistants' verbatim answers + provenance.json
  MANIFEST.json           sha256 of every file
build_v0_1.py             regenerates v0.1/ deterministically from benchmark/hard + benchmark/optimize
SCHEMA.md                 every field, every output format, the detector interface
results/                  run + corpus-eval outputs for the hard round
leaderboard/              leaderboard.md + leaderboard.html (self-contained)
```

| task | qubits | mode | constraints |
|---|---|---|---|
| `maj5` | 6 | unitary | q5 ^= MAJ(q0..q4), no ancillas |
| `cmul7` | 5 | unitary | controlled x → 7x mod 15 (control q4), no ancillas |
| `qpe_t` | 4 | state | QPE of T with 3 counting qubits, own inverse QFT; final state exactly \|1⟩\|001⟩ |
| `c3x_linear` | 4 | unitary | C3X with gates {cx,h,x,s,sdg,t,tdg,rz,p}, linear coupling only |
| `reverse6_nn` | 6 | unitary | reverse 6 qubits, CX only, nearest-neighbour CX only |
| `bv22` | 6 | state | Bernstein–Vazirani for s = 22, ancilla returned to \|0⟩ |
| `add3` | 6 | unitary | \|a⟩\|b⟩ → \|a⟩\|a+b mod 8⟩ with {x,cx,ccx,mcx}, no ancillas |

## Quick start

```bash
# score a directory of model outputs (DIR/<model>.py, DIR/<model>/<task>.py|.qasm, or DIR/<model>/solution.py)
veriq bench run --model-outputs path/to/outputs -o run.json
veriq bench run --model-outputs benchmark/veriqbench/v0.1/submissions/hard-round-2026-10-27 --no-optimize

# score a detection method against the corpus (built-ins: histogram, zero-state, all-basis, proof, veriq)
veriq bench corpus-eval --detector histogram -o ce_hist.json
veriq bench corpus-eval --detector my_detectors.py:my_fn      # fn(candidate, reference, mode, **kw) -> True/False/None

# rebuild the leaderboard
veriq bench leaderboard --run benchmark/veriqbench/results/run_hard-round-2026-10-27.json \
    --corpus-eval benchmark/veriqbench/results/corpus_eval_*.json --out-dir benchmark/veriqbench/leaderboard
```

`PASS` = the proof passes **and** every constraint holds. CX is measured after transpiling to `cx, rz, sx, x` at
optimization level 1, `seed_transpiler=2026`, with `qubits_initially_zero=False` for unitary tasks (the default `True`
does not preserve the unitary, see Qiskit issue #13562) and a linear coupling map for `c3x_linear` and `reverse6_nn`.

**Safety:** `bench run` imports submission files in-process. Run untrusted model output inside a container or sandbox.

## Reproducibility

`python benchmark/veriqbench/build_v0_1.py` rebuilds `v0.1/` byte-identically (check `MANIFEST.json`). Inputs are the
committed hard-round raw answers (`benchmark/hard/raw`, never modified), the mutation study and the optimization results.
Seeds: mutants 2026, histogram shots 4096 with seed 7, transpiler 2026.

## Caveats

* n = 4 assistants, one round, one attempt each. The exact model versions behind the web chats are **unknown**.
* `best_known` CX values are upper bounds found by `veriq optimize`, not proven optima.
* The corpus covers 6 single-point mutation operators on 7 small tasks (≤ 6 qubits); it is not a sample of real LLM bugs.
