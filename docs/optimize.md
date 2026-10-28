# Verified CX optimizer (`veriq optimize`)

Most compilers make one circuit and trust it. `veriq optimize` makes **many** compilations of your circuit, ranks
them by two-qubit-gate count (then depth), and **proves** them equivalent to your input, cheapest first. It
returns the first one with a formal proof (`PROVEN_EQUIVALENT`). A candidate that is only `PROBABLY_EQUIVALENT`
(simulations found no difference), `UNKNOWN` or `NOT_EQUIVALENT` is **never** returned. If nothing can be
proven, you get no circuit.

```bash
veriq optimize my_circuit.py                       # basis cx,rz,sx,x, all-to-all
veriq optimize my_circuit.py -o best.qasm --json report.json
veriq optimize prep.py --mode state                # only the state from |0..0> must match
veriq optimize c3x.py --coupling linear            # routed on a line; proof up to the routed layout
veriq optimize qft.py --allow-permutation          # accept an output qubit permutation (recorded in the layout)
```

Exit code 0 means a proven circuit was found; 2 means nothing could be proven.
From Python: `veriq.optimize.optimize_circuit(qc, mode=..., basis_gates=..., coupling=..., seeds=..., timeout=..., budget=...)`.
From MCP: the `optimize_circuit` tool, which takes the same inputs plus `code`/`path` and returns `best`, `best_qasm` and `tried`.

## Candidates

All of them use `approximation_degree=1.0` (approximation off) and `qubits_initially_zero=False`, so no pass may
assume the inputs are |0⟩. In state mode, `qubits_initially_zero=True` variants are added, and they are proven in
state mode too.

| family | what |
|---|---|
| `transpile` levels 0-3 | `--seeds` seeds per level (1 seed at level 0) |
| no-permutation-elision | levels 2-3 with `ElidePermutations` / `Split2QUnitaries` removed from the init stage (see below) |
| extra round | level 3 followed by Collect2qBlocks → ConsolidateBlocks → UnitarySynthesis → 1q optimisation → CommutativeCancellation, repeated while it saves CX |
| exact resynthesis (≤ 6 qubits) | the exact matrix rebuilt by quantum Shannon decomposition (unitary mode), or the exact output state by `StatePreparation` (state mode), then transpiled at levels 1 and 3 |

Identical candidates are deduplicated before any proof runs. At most 12 proofs are attempted, all within `--budget`.

## What "proven" means here

* With no coupling map, a candidate is compared as a **plain circuit on the same qubits**: any layout or output
  permutation the transpiler recorded is dropped first. Qiskit levels 2-3 like to turn a final SWAP layer into a
  "virtual" output permutation. Such a circuit is *not* a drop-in replacement, so its proof fails and it is skipped.
  On the 3-qubit QFT, the plain level-3 output (12 CX) is `NOT_EQUIVALENT` as a standalone circuit. `veriq optimize`
  returns 18 CX by default, or 12 CX with `--allow-permutation`, in which case the result tells you the permutation
  (`final_index_layout`).
* With `--coupling`, the routed circuit keeps its layout, and the proof is "equal up to the recorded
  initial/final layout". That is how a routed circuit is used.
* `--mode state` proves only "same state from |0…0⟩". Use it for state preparations, never for blocks that get
  other inputs.
* Proof engines are the ones from `veriq.scale.decide_equivalence`: dense Operator (≤ 10 qubits), Clifford
  tableau, QCEC (ZX/alternating/…) and, in state mode, an exact untruncated MPS overlap.

## Evidence: the 28 hard-round circuits

`benchmark/optimize/run_optimize.py` optimizes every circuit the four assistants wrote in the hard round
(`benchmark/hard/raw/*.py`, read-only). Results are in [benchmark/optimize/results.md](../benchmark/optimize/results.md).
"Before" is the hard-round cost metric (Qiskit level 1, `qubits_initially_zero=False`).

| assistant | CX before | CX after (proven) | saved |
|---|---:|---:|---:|
| ChatGPT | 1594 | 644 | 950 (60%) |
| Claude | 1784 | 1354 | 430 (24%) |
| Gemini | 564 | 483 | 81 (14%) |
| Perplexity | 1538 | 643 | 895 (58%) |

28/28 circuits got a proven result. The big wins come from small dense blocks: cmul7 went from 1116 to 236 CX, and
c3x_linear from 150 to 85, both through exact resynthesis. The swap network (reverse6_nn), BV and the adder were
already at the optimizer's floor.

## Limitations

* This is the cheapest **proven** candidate among those generated. It is not an optimal circuit; there is no
  lower-bound search.
* Exact resynthesis is limited to ≤ 6 qubits, and QSD's CX count grows like 4ⁿ, so it only wins on dense blocks.
* Above 10 qubits, unitary-mode proofs depend on QCEC or Clifford structure. A cheaper candidate that cannot be
  proven within `--timeout` is skipped, never returned.
* The optimized circuit equals *your* circuit, not the intended one: a wrong circuit stays wrong. Verify it with
  `veriq check` against a reference first.
