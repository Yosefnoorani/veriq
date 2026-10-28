# Multi-framework frontends (OpenQASM 2/3, Cirq, TKET)

Veriq's engine works on Qiskit `QuantumCircuit`s. `src/veriq/frontends/` loads circuits written in other
frameworks and converts them **exactly** (global phase included) to Qiskit, so candidate and reference can come
from different frameworks:

```bash
pip install 'veriq[qasm3,cirq,tket]'          # extras: qasm3 = qiskit-qasm3-import, cirq = cirq-core,
                                              #         tket = pytket + pytket-qiskit
veriq verify kernel.qasm kernel_cirq.py       # second positional = reference (same as --reference)
veriq verify ansatz_tket.json --reference ansatz.qasm --framework tket
```

| framework | inputs | detected by |
|---|---|---|
| `qiskit` | `.py` building a `QuantumCircuit` | object type |
| `qasm2` / `qasm3` | `.qasm`, `.qasm2`, `.qasm3` | `OPENQASM 2`/`3` header (qasm3 needs `qiskit-qasm3-import`) |
| `cirq` | `.py` building a `cirq.Circuit` (or `FrozenCircuit`), Cirq JSON (`cirq.to_json`) | object type / `"cirq_type"` key |
| `tket` (alias `pytket`) | `.py` building a `pytket.Circuit`, TKET JSON (`Circuit.to_dict()`) | object type / `"commands"`+`"qubits"` keys |

`.py` files use the usual convention (`build()` or a module-level `circuit`/`qc`; `--function NAME` for others).
`--framework` / `--reference-framework` (CLI), `framework` / `reference-framework` (`.veriq.yml`; `framework` is
also allowed in `defaults`) and `framework` / `reference_framework` / `other_framework` (MCP `verify_circuit`,
`compare_circuits`) override detection; a mismatch (e.g. `--framework tket` on a file that builds a Cirq
circuit) is a load error (exit 3), not a silent conversion. A missing extra gives
`... pip install 'veriq[cirq]'` instead of a traceback.

## Qubit mapping and endianness (read this once)

* **Cirq:** qubits are ordered by Cirq's own default order, `sorted(circuit.all_qubits())` (LineQubit by index,
  GridQubit by (row, col), NamedQubit by natural name order so `q_2 < q_10`); the i-th becomes Qiskit qubit i.
  Only qubits the circuit touches exist: add `cirq.I(q)` to keep an idle qubit (Cirq has no register width).
* **TKET:** `circ.qubits` (TKET's default order: register name, then index) → Qiskit qubit i; bits likewise.
* **Endianness:** the *circuits* map qubit-for-qubit, but Cirq/TKET matrices and state vectors are big-endian
  (qubit 0 = most significant bit) while Qiskit's are little-endian. So
  `Operator(qc).reverse_qargs().data == cirq.unitary(c) == tket_circ.get_unitary()`. A counterexample
  label `|0010>` from Veriq is little-endian (qubit 0 is the rightmost character).
* **Angles:** TKET parameters are in half-turns (multiples of π) and are multiplied by π; Cirq `exponent`s are
  converted from each gate's own matrix, never from a hand-written angle formula.
* **Global phase:** every gate is matched against the framework's own unitary up to a phase, and that phase is
  added to `qc.global_phase`; `cirq.GlobalPhaseGate`, TKET `circ.phase` and `Phase` ops add theirs. The
  converted Operator equals the framework's unitary exactly (tests check this), so *controlled* phases are
  never lost; whole-circuit global phase is then ignored by the equivalence check as usual.
* **Conversion order:** native Qiskit gate (checked exactly) → Cirq `decompose_once` / TKET `AutoRebase` of
  that one op (checked exactly) → `UnitaryGate` (counted as `opaque_ops`). Symbolic parameters, classical
  control, noise channels and Cirq measurement `invert_mask` are rejected.

The mapping is recorded in `qc.metadata["veriq_frontend"]` (framework, version, source format, qubit map, op
counts) and each certificate input carries a `frontend` block, e.g.
`{"framework": "tket", "framework_version": "2.18.5", "source_format": "json", "opaque_ops": 0}`
(for OpenQASM 3 also `qasm3_importer_version`).

## Sandbox (MCP)

User framework code runs in the same sandboxed worker as Qiskit code (separate process, rlimits, no network,
read-only source dir); the converted circuit leaves the sandbox as QPY with its frontend metadata. `code`
may be Python, OpenQASM, or Cirq/TKET JSON text (auto-detected by a leading `{`).

## Evidence

`benchmark/frameworks/run_frameworks.py` translates the 7 hard-round references plus the chatgpt and claude
submissions (21 circuits) with each framework's own converter and checks them; see
[benchmark/frameworks/results.md](../benchmark/frameworks/results.md). Measured: 63/63 translations
(OpenQASM 3, Cirq, TKET) loaded and proven equivalent with 0 opaque ops; 87/87 deliberate mis-translations that
actually change the unitary (reversed qubit order, dropped controlled phase, radians given as Cirq exponent /
TKET half-turns) caught as NOT_EQUIVALENT with 0 false alarms; 9 reversals of palindromic `reverse6_nn`
circuits are genuinely harmless and were proven equivalent; 21/21 extra-global-phase controls proven
equivalent. The harness also found that Qiskit's default `transpile(..., optimization_level=0)` changed the
unitary of 3/21 circuits (mcx synthesis assuming |0> helpers) when flattening for Cirq's QASM importer.

## Limitations

* Unitary circuits plus final measurements; no classical control, no symbolic parameters.
* Cirq `.py`/JSON circuits have no fixed width: idle qubits disappear unless you add `cirq.I`.
* QASM 2 has no global phase; equivalence is up to global phase anyway.
* Ops with no native match on more than 10 qubits skip the exact decomposition-phase fix-up (they still go
  through the framework's own decomposition); large opaque ops become `UnitaryGate`s.
