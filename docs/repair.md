# Repair reports and the repair loop

When a circuit FAILs, a verdict alone is not enough to fix it. Veriq produces a **machine-readable repair
report** (`schema: veriq.repair_report/1`) that says what is wrong, where, and often exactly how to fix it.
It also drives a bounded **verify → report → fix → re-verify** loop with a fixer you plug in.

## The repair report

```bash
veriq verify examples/ghz_buggy.py -r examples/ghz_correct.py --mode state --repair-report report.json
```

(`verify` is an alias of `check`; the flag works with either.) From MCP, `verify_circuit` embeds a compact
`repair_report` whenever the verdict is not PASS, and the `repair_hints` tool returns the full report.
From Python, call `veriq.repair_report.build_repair_report(candidate, reference, mode)`.

| key | content |
|---|---|
| `verdict`, `failing_checks` | the verdict and the failing checks with their summaries |
| `counterexample` | an input, with the **expected** (reference) and **actual** (candidate) output distributions and the fidelity |
| `localization.regions` | the gate ranges where the bug is (`gate_start`..`gate_end`, the gates with their text, the qubits involved) |
| `localization.fixes` | exact single-gate fixes, e.g. `replace gate #2 cx(2, 1) by cx(1, 2)`, `delete gate #4`, `insert cp(pi/4) on (0, 2) before gate #7` |
| `hardware_violations` | gate-set, coupling-map and black-box violations, with the first offending gates |
| `metric_deltas` | qubits, depth, size, 2-qubit, multi-qubit and CX counts vs the reference |
| `hints` | plain-language next steps |

### How localization works (exact, ≤ 10 qubits)

Let P_g be the first g gates of the candidate C, and R the reference. The correction that, inserted at gap g, makes C
exactly equal to R is D_g = P_g · C† · R · P_g†. Veriq computes D_g for every gap incrementally and measures its
**support**, the set of qubits it acts on non-trivially. The gaps where the support is smallest are the bug's
location. That is where the smallest possible edit makes the circuit right. When D_g is a recognizable 1- or
2-qubit gate (x, h, s, t, sx, cx either way, cz, swap, p(θ), cp(θ), …, up to global phase), Veriq turns it into an
exact fix (delete / replace / insert) and checks the fix. In state mode it compares reduced density matrices of the
two states along the circuit instead. Above 10 qubits or 2000 gates, `localization.available` is false, and you still
get the counterexample, violations and metrics.

A region can span several gates. When the bug commutes with its neighbours, any position in the region is an equally
valid place to fix it, so the region width is reported.

## The repair loop

```bash
veriq repair examples/ghz_buggy.py -r examples/ghz_correct.py --mode state --out fixed.qasm --json log.json
#   attempt 0: FAIL
#   attempt 1: PASS  after: flip gate #2 cx(2, 1) -> cx(1, 2)
#   => PASS (stop: PASS, 1 fix(es), 0.31s)
```

On every attempt, `veriq.repair.repair_loop` runs the full check suite (the same as `veriq check`), builds the repair
report and hands it to the fixer. It stops at:

* `PASS`: done, and the verdict comes from Veriq's checks, not from the fixer;
* `INCONCLUSIVE`: nothing could be proven or refuted, so further edits would be blind (for example, mid-circuit measurement);
* `fixer_gave_up`: the fixer returned None;
* `build_error`: the fixer returned code that does not build;
* `max_attempts`: the default is 5.

`--out` writes the final circuit only if it PASSes. `--json` writes the attempt log and the last report.

### Plugging in a fixer (for example an LLM)

A fixer is any callable `fixer(request) -> QuantumCircuit | str | None`. `request` is a `veriq.repair.FixRequest`
with `circuit`, `source` (the current source text when there is one), `report` (the repair report), `reference`,
`mode`, `attempt` and `history`. Return a circuit, new **source text** (Python defining `build()` or OpenQASM), or
`None` to give up.

```python
# my_fixer.py: Veriq itself never calls an external API; your fixer decides what to call.
import json

def llm_fixer(req):
    prompt = (
        "This Qiskit circuit fails verification. Fix it and return ONLY the corrected Python "
        "(a build() function returning a QuantumCircuit).\n\n"
        f"Source:\n{req.source}\n\nVeriq repair report:\n{json.dumps(req.report, indent=1)[:8000]}"
    )
    answer = my_llm_client.complete(prompt)   # your client, your key, your choice of model
    return extract_code_block(answer)          # str -> Veriq loads it and re-verifies it
```

```bash
veriq repair candidate.py -r reference.py --fixer my_fixer:llm_fixer --max-attempts 5
```

Over MCP, the `verify-and-repair` prompt runs the same loop inside the assistant. The assistant writes the circuit,
calls `verify_circuit`, reads `repair_report`, edits, and repeats, at most `max_attempts` times. It stops at PASS,
or at INCONCLUSIVE, where it must say the result is unverified.

### The built-in `demo` fixer

`--fixer demo` (the default) is deterministic and offline, with no API keys. It:

1. applies the report's exact single-gate fixes (a raw 2×2/4×4 matrix fix is synthesized into u/cx);
2. otherwise tries small edits inside the localized regions (delete a gate, negate an angle, flip a CX, crz→cp,
   rz→p, or rescale all angles by π/3.14) and keeps the first one that makes the circuit exactly equal to the
   reference (≤ 10 qubits);
3. otherwise gives up.

**It knows the vocabulary of typical slips**, the same operators the mutation study injects. Its success rate
therefore measures the plumbing (report → fixer → re-verify → stop), not how well a language model repairs real bugs.

## Evidence: the hard-round mutation study

`benchmark/repair/run_repair.py` regenerates the 1036 mutants from the hard round (same seed and order; checked
against `benchmark/hard/results/mutation.json`). It skips the 70 that were proven equivalent and localizes the rest.
Full table: [benchmark/repair/results.md](../benchmark/repair/results.md).

* **Localization accuracy: 847/958 = 88.4%** of single-gate mutants have the injected mutation inside a flagged
  region. A deletion counts when the region contains the gap where the gate is missing. Other mutations count when the
  region contains the changed gate or an adjacent gap.
* 97 of the 111 misses still have an **exact single-gate fix inside a flagged region**. The bug can equally be fixed
  there; a typical case is one CX deleted from a SWAP in a swap network, which can be repaired in a neighbouring
  SWAP. Counting those, a flagged region is a valid fix location for **98.5%**.
* On average, 3.5 regions covering 18 gaps in total are flagged, in circuits of 79 gates.
* Repair-loop demo with the demo fixer: **152/188** sampled mutants (up to 3 per assistant × task × operator)
  ended at PASS. All 36 others stopped with `fixer_gave_up`. They are mostly deleted multi-controlled gates (mcx with
  3+ qubits) and state-mode deletions, which have no 1-2-qubit fix to synthesize.

## Limitations

* Exact localization and fixes need ≤ 10 qubits and ≤ 2000 gates. Above that, only the counterexample, violations
  and metrics are reported.
* Single-gate fixes cover 1- and 2-qubit corrections only. A bug spread over many gates (for example, every angle
  wrong) gets regions and a "no single fix" hint, but no fix.
* "Minimal support" finds where the *smallest* fix goes. That is not always the line a human got wrong: commuting
  gates make several positions equivalent.
* The loop trusts no fixer. A fixer's output counts only after Veriq's checks PASS it, and an INCONCLUSIVE result stops
  the loop instead of being treated as success.
