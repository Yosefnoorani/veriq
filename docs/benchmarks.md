# Benchmarks and studies

<sub>Moved from the README. See also the [README](../README.md).</sub>

## Real bugs in published model solutions

See [benchmark/real_bugs/README.md](../benchmark/real_bugs/README.md).

## LLM benchmark (week 2)

`benchmark/` holds 28 circuits written by ChatGPT, Claude, Gemini and Perplexity (verbatim in
`benchmark/llm/raw/`), independently verified references (`benchmark/references.py`), and the harness:

```bash
.venv/bin/python benchmark/run_llm.py   # -> benchmark/results/{results.json,results.md,reports/*.html}
```

## Hard round: 7 non-standard tasks, proof-only bugs

`benchmark/hard/` holds the 7-task prompt (`prompt.md`, reconstructed), the four assistants' answers
verbatim (`raw/*.py`, never edited), references proven against exhaustive truth tables
(`references.py`), and the harness:

```bash
.venv/bin/python benchmark/hard/run_hard.py              # ~2 min incl. mutation study
.venv/bin/python benchmark/hard/run_hard.py --no-mutants # ~10 s, verdicts and costs only
# -> benchmark/hard/results/{results.json,results.md,mutation.json,reports/*.html}
```

Findings (details in `benchmark/hard/results/results.md`):
- All 28 circuits are correct (28/28 PASS, proved). Gemini's C3X uses `rz` instead of `p` and differs by
  the global phase e^{-iπ/16}, which is allowed.
- The costs are very different: after transpiling to {cx, rz, sx, x}, cmul7 ranges from 70 to 1116 CX
  (15.9x), maj5 from 240 to 1312 (5.5x), and C3X on a linear chain from 24 to 150 (6.2x).
- In 5 of 28 circuits, Qiskit's default compile is not unitary-equivalent (the `qubits_initially_zero`
  hazard). Only a unitary proof sees this.
- Mutation study: 1036 injected bugs (deleted gate, negated angle, π written as 3.14, flipped CX,
  cp→crz, p→rz) were added to the 28 correct circuits. Of 966 truly wrong mutants, the usual Aer
  histogram from |0...0> catches only 327 (34%). 596 more need an exhaustive basis-input sweep. 43 are
  caught by the proof alone:
  - 39 phase errors in the C3X circuits leave every basis-input distribution unchanged, so no sampling
    test can catch them;
  - in 4 QPE circuits, π written as 3.14 moves the output distribution by a TVD of about 1e-6, far below
    shot noise.

## Showcase: the silent transpile footgun

`examples/transpile_hazard/` contains a 5-qubit `mcx([0,1,2], 3)` block. After a default
`transpile()` it passes Aer sampling (TVD 0), yet Veriq proves it NOT equivalent, with
counterexample |10100>. Reused via `to_gate()`, it gives the wrong output.

This is documented Qiskit behaviour (`qubits_initially_zero=True` since 1.3), not a Qiskit
bug. The fix is `qubits_initially_zero=False`. See that folder's README. Post drafts are in
`docs/posts/transpile_hazard_{en,he}.md`.

```
python examples/transpile_hazard/demo.py
```

## Veriq Bench v0.1 (public benchmark)

`benchmark/veriqbench/` packages the 7 hard tasks as a versioned, reproducible benchmark. Each task has a spec (prompt,
reference and constraints). The bug corpus is stored as data: 1036 single-gate mutants plus 28 originals, one JSON file
each, with fields for the task, the source assistant, the mutation class, the location, whether the mutant is
equivalent, and which detectors catch it. Field definitions are in
[SCHEMA.md](../benchmark/veriqbench/SCHEMA.md), and the integrity hashes are in `MANIFEST.json`.

```bash
veriq bench run --model-outputs DIR            # score new model outputs: proof, CX/depth, constraints, optimized-CX gap
veriq bench corpus-eval --detector histogram   # score a detection method (built-in or file.py:fn) against the corpus
veriq bench leaderboard                        # -> benchmark/veriqbench/leaderboard/{leaderboard.md,leaderboard.html}
```

Results recomputed on the 966 wrong mutants (0/98 false positives for every detector):

| Detector | Recall |
|---|---|
| histogram | 33.9% |
| zero-state | 34.3% |
| all-basis | 96.0% |
| proof | 100% |

In the hard round all 28 submissions passed. Their CX cost, however, ranges from 1.5× to 2.1× the best proven circuit
(geomean). Details are in the [leaderboard](../benchmark/veriqbench/leaderboard/leaderboard.md) and the paper draft
[docs/paper/veriq_bench.md](paper/veriq_bench.md).

**Warning:** submissions run in-process without a sandbox, so only run code you trust.
