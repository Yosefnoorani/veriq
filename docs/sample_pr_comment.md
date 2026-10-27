# Sample Veriq PR comment

This is the comment the action posts on a pull request, rendered from real `veriq ci` output
(Qiskit 2.6.1, 27 Oct 2026). The action keeps **one** comment per PR: it finds its earlier comment by the
hidden marker `<!-- veriq-ci-comment -->` and edits it in place on every push, adding a link to the workflow run.
The same Markdown goes to the job summary.

## A PR that breaks something

A PR that edits `qft.py` and `compiled.py` and leaves both broken. In this config every entry expects PASS:

---

## Veriq

❌ **Veriq: 2 of 5 checks did not give the expected verdict.**

| Check | Verdict | Expected | CX as written → compiled¹ | Notes |
|---|---|---|---|---|
| `qft_correct` | ✅ PASS | PASS ✓ | 0 → 15 | – |
| `qft_buggy` | ❌ FAIL ⟵ | PASS | 0 → 15 | Reference equivalence: counterexample \|0001>; expected PASS |
| `hazard_compiled` | ❌ FAIL ⟵ | PASS | 12 → 21 | Reference equivalence: counterexample \|10100>; expected PASS |
| `hazard_safe` | ✅ PASS | PASS ✓ | 14 → 21 | – |
| `hard_chatgpt_maj5` | ✅ PASS | PASS ✓ | 0 → 512 | zero_init_hazard |

> **zero_init_hazard**: Qiskit's default `transpile()` (`qubits_initially_zero=True`) would borrow idle qubits as clean ancillas here, so the default-compiled block is only valid from |0…0>. Veriq verified with `qubits_initially_zero=False`.

<sub>¹ compiled = Veriq's transpile target: generic basis ['rz', 'sx', 'x', 'cx'] + linear coupling, opt=3; unitary-mode checks use `qubits_initially_zero=False`.</sub><br>
<sub>Full HTML reports: workflow artifact `veriq-reports`.</sub><br>
<sub>veriq 0.1.0 · qiskit 2.6.1 · qiskit-aer 0.18.2 · mqt.qcec 3.11.0</sub>
<sub>[Workflow run](https://github.com/OWNER/REPO/actions/runs/RUN_ID) · commit abc1234</sub>

---

Exit code 1, so the check fails. `hazard_compiled` is the transpile footgun from
[examples/transpile_hazard](../examples/transpile_hazard/). Sampling it from |00000> looks fine, but Veriq finds the
input |10100> where it differs from the reference. `hard_chatgpt_maj5` passes, but it carries the `zero_init_hazard` note:
Qiskit's default compile of that block would only be correct with clean ancillas.

## This repo's own run (`.veriq.yml`, all as expected)

---

## Veriq

✅ **Veriq: all 13 checks gave the expected verdict.**

| Check | Verdict | Expected | CX as written → compiled¹ | Notes |
|---|---|---|---|---|
| `bell_correct` | ✅ PASS | PASS ✓ | 1 → 1 | – |
| `bell_qasm2` | ✅ PASS | PASS ✓ | 1 → 1 | – |
| `ghz_qasm3` | ✅ PASS | PASS ✓ | 2 → 2 | – |
| `ghz_buggy` | ❌ FAIL | FAIL ✓ | 2 → 2 | Reference equivalence: counterexample \|000>; Statistical test (Aer) failed |
| `qft_correct` | ✅ PASS | PASS ✓ | 0 → 15 | – |
| `qft_buggy` | ❌ FAIL | FAIL ✓ | 0 → 15 | Reference equivalence: counterexample \|0001> |
| `grover_correct` | ✅ PASS | PASS ✓ | 0 → 37 | – |
| `grover_buggy` | ❌ FAIL | FAIL ✓ | 0 → 37 | Reference equivalence: counterexample \|000>; Statistical test (Aer) failed |
| `hazard_block` | ✅ PASS | PASS ✓ | 0 → 21 | zero_init_hazard |
| `hazard_compiled` | ❌ FAIL | FAIL ✓ | 12 → 21 | Reference equivalence: counterexample \|10100> |
| `hazard_safe` | ✅ PASS | PASS ✓ | 14 → 21 | – |
| `hard_claude_c3x_linear` | ✅ PASS | PASS ✓ | 24 → 24 | – |
| `hard_chatgpt_maj5` | ✅ PASS | PASS ✓ | 0 → 512 | zero_init_hazard |

> **zero_init_hazard**: Qiskit's default `transpile()` (`qubits_initially_zero=True`) would borrow idle qubits as clean ancillas here, so the default-compiled block is only valid from |0…0>. Veriq verified with `qubits_initially_zero=False`.

<sub>¹ compiled = Veriq's transpile target: generic basis ['rz', 'sx', 'x', 'cx'] + linear coupling, opt=3; unitary-mode checks use `qubits_initially_zero=False`.</sub><br>
<sub>Full HTML reports: workflow artifact `veriq-reports`.</sub><br>
<sub>veriq 0.1.0 · qiskit 2.6.1 · qiskit-aer 0.18.2 · mqt.qcec 3.11.0</sub>

---

The four `❌ FAIL | FAIL ✓` rows are deliberately buggy examples marked `expect: fail`. If Veriq ever stopped
catching them, the job would fail.
