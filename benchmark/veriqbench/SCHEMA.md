# Veriq Bench v0.1 — data schema

All files live under `benchmark/veriqbench/v0.1/` and are listed with their sha256 in `MANIFEST.json`.
They are generated deterministically by `build_v0_1.py` (two builds give a byte-identical manifest).
Run outputs (`results/`) and the leaderboard (`leaderboard/`) are kept **outside** `v0.1/` so the manifest stays valid.

## `tasks/<task>.json` — one per task (7)

| field | meaning |
|---|---|
| `id` | task id: `maj5`, `cmul7`, `qpe_t`, `c3x_linear`, `reverse6_nn`, `bv22`, `add3` |
| `version` | `"0.1"` |
| `order` | position in the original prompt (1..7) |
| `title`, `function` | human title; the Python function name the prompt asks for |
| `qubits` | required qubit count (no extra/ancilla qubits allowed) |
| `mode` | `unitary` (full operator must match, up to global phase) or `state` (only the output state from \|0…0⟩ must match) |
| `prompt.shared_preamble` / `prompt.task` / `prompt.shared_suffix` | the exact prompt text, split so a single task can be re-asked; `prompt.full_prompt_file` = `prompt.md` (the verbatim prompt used in the hard round) |
| `reference.file` / `reference.function` | `references.py` and the function that builds the reference circuit |
| `reference.verified_against` | how the reference itself was checked (e.g. exhaustive truth table, analytic state) |
| `reference.qasm` | the reference as OpenQASM 2 (`null` for `qpe_t`, whose reference is built in Python only) |
| `constraints` | `no_black_boxes`, `allowed_gates` (list or `null` = any standard gate), `coupling` (edge list or `null`), `no_measurements`, `no_extra_qubits` |
| `correctness` | prose statement of what "correct" means for the task |
| `cost_model` | `basis_gates` (`cx, rz, sx, x`), `optimization_level` 1, `seed_transpiler` 2026, `qubits_initially_zero` (true only for `state` tasks), `coupling_map` (`"linear"` or `null`), `metric` |

The cost model transpiles with `qubits_initially_zero=False` for unitary tasks on purpose: with the Qiskit default
(`True`) the transpiler may use idle qubits as clean ancillas, which preserves results from \|0…0⟩ but **not** the unitary
(see Qiskit issue #13562). In the hard round this changed the unitary of 5/28 transpiled circuits.

## `corpus/mutants.jsonl` — 1036 lines, one mutant each

| field | meaning |
|---|---|
| `id` | `vb01-0001` … `vb01-1036` |
| `task`, `source_assistant`, `mode` | which task, which assistant's correct circuit was mutated, and the task mode |
| `mutation_class` | `delete_gate`, `negate_angle`, `pi_as_3.14`, `flip_cx`, `cp_to_crz`, `p_to_rz` |
| `description` | human-readable mutation (e.g. `delete #0 mcx(0, 1, 2, 5)`) |
| `location` | `{gate_index, gate, qubits, params}` of the mutated top-level instruction; `null` for `pi_as_3.14` (all 8 write π as 3.14 in every angle of the circuit, not in one gate) |
| `equivalent` | `true` if the mutant is still equivalent to the reference (a *negative*: an equivalent mutant) |
| `study_class` | `caught_by_histogram`, `missed_by_histogram_caught_by_truth_table`, `proof_only_sampling_too_weak`, `proof_only_invisible_to_sampling`, `equivalent_mutant` |
| `detected_by` | recorded booleans: `histogram` (Aer 4096 shots from \|0…0⟩, seed 7), `zero_state_exact` (exact TVD from \|0…0⟩ > 1e-9), `all_basis` (max exact TVD over all basis inputs > 1e-9), `proof` (equivalence proof says not-equivalent) |
| `recorded` | the raw hard-round values behind those labels: `proof`, `aer_hist_from_zero`, `exact_tvd_from_zero`, `exact_max_tvd_all_basis_inputs` |
| `qasm` | the mutant as OpenQASM 2 (round-trip checked; custom-gate names normalised to `name_vN`) |

Mutants were generated with seed 2026, at most 30 per operator per circuit, from the 28 verified-correct hard-round circuits.

## `corpus/correct.jsonl` — 28 lines

The unmutated, verified-correct circuits (`id` = `ok-<assistant>-<task>`, `equivalent: true`, `qasm`).
Together with the 70 equivalent mutants they are the **98 negatives** used to measure false positives.

## `best_known.json`

Per task: `cx`, `depth`, `from` (which submission it was derived from), `method`, `status` (`PROVEN_EQUIVALENT`), `coupling`.
It is the lowest CX found by `veriq optimize` for a circuit *proven* equivalent to a correct submission —
an **upper bound** on the optimum, not the optimum.

## `submissions/<round>/`

`<model>.py` (verbatim answer files) and `provenance.json`: `round`, `prompt_date`, `how`, and per model
`label`, `interface`, `model_version` (unknown for the hard round: the web UIs did not show it and it was not recorded),
`date`, `attempts`, `source_sha256`.

## Submission layouts accepted by `veriq bench run --model-outputs DIR`

* `DIR/<model>.py` — one file defining all 7 functions (the original prompt format);
* `DIR/<model>/<task>.py` or `DIR/<model>/<task>.qasm` — one file per task (a `.py` defines the task function, or `build()` / `circuit`);
* `DIR/<model>/solution.py` — one file per model.

A missing task scores `MISSING`; an exception while building scores `BUILD_ERROR`.
**Submissions are executed in-process; run untrusted code in a sandbox/container.**

## Run output — schema `veriq.bench_run/1`

Top level: `schema`, `bench_version`, `bench`, `model_outputs`, `generated`, `versions` (veriq, python, qiskit, mqt.qcec, …),
`settings` (`optimize`, `budget_s`, `seeds`, `timeout_s`), `provenance` (copied from `DIR/provenance.json` if present),
`tasks`, `best_known` (bundled table, improved by anything proven in the run; `source` says which), `summary`, `results`, `seconds`.

`results[]` (one per model × task): `model`, `task`, `file`, `status` (`PASS`/`FAIL`/`ERROR`/`BUILD_ERROR`/`MISSING`),
`correct` (the proof passed), `proof`, `constraints` (`gate_set`, `coupling`, `no_black_boxes`, `qubits`, `no_measurements`;
each `PASS`/`FAIL`/`null` = not applicable), `compliant`, `failing_checks`, `metrics` (as written), `cost` (`cx`, `depth`, … under the
task cost model), `optimized` (`cx`, `depth`, `status`, `method` of the best proven-equivalent rewrite, if `optimize`),
`gap` (`best_cx`, `cx_gap` = cost − best, `cx_ratio` = cost / best, `optimized_cx_gap`), `seconds`.

`PASS` requires a passing proof **and** all constraints compliant.

`summary[model]`: `tasks`, `pass`, `correct`, `compliant`, `cx_total_pass`, `best_cx_total_pass`, `cx_ratio_geomean` (over PASS tasks).

## Corpus-eval output — schema `veriq.corpus_eval/1`

Top level: `schema`, `detector`, `description`, `bench`, `generated`, `versions`, `settings` (`shots`, `seed`, `timeout_s`, `negatives`, `limit`),
`summary`, `seconds`, `results` (`id`, `task`, `mutation_class`, `study_class`, `equivalent`, `flagged`, `recorded`, `error`).

`summary`: `wrong_mutants`, `detected`, `missed`, `undecided_on_wrong`, `recall`, `negatives`, `false_positives`,
`undecided_on_negatives`, `false_positive_rate`, `precision`, `errors`, `agreement_with_recorded_labels`
(only for built-in detectors that have a recorded label), and `by_study_class` / `by_mutation_class` / `by_task` recall tables.

## Detector interface

```python
def my_detector(candidate: QuantumCircuit, reference: QuantumCircuit, mode: str, **kw) -> bool | None:
    """True = 'this circuit is buggy', False = 'looks correct', None = undecided.
    kw carries shots, seed, timeout (ignore what you don't need)."""
```

Pass it as `--detector path/to/file.py:my_detector` or `--detector package.module:my_detector`.
Built-ins: `histogram`, `zero-state`, `all-basis`, `proof`, `veriq` (the full `veriq check` pipeline).
