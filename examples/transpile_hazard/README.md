# Transpile hazard: a compiled block that passes sampling and is still wrong

**Not a Qiskit bug.** Since Qiskit 1.3, `transpile()` defaults to `qubits_initially_zero=True`.
With that setting, `HighLevelSynthesis` can use idle qubits as *clean* ancillas
(qubits assumed to be in |0>) when it decomposes an `MCXGate`. This is documented in the
1.3 release notes and the `HighLevelSynthesis` docs. The output is guaranteed correct
only when the whole circuit starts in |0...0>. It is **not** guaranteed to keep the unitary.
When you transpile a block and then reuse it (`to_gate()`, `compose`, a library of
pre-compiled oracles), nothing warns you. A maintainer said exactly this in
[Qiskit#13562](https://github.com/Qiskit/qiskit/issues/13562): "default transpilation is
guaranteed to give you the correct measurement results, but does not necessarily preserve
the unitary."

## Minimal reproducer

```python
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import Operator

qc = QuantumCircuit(5)          # q4 is never touched
qc.mcx([0, 1, 2], 3)
t = transpile(qc, basis_gates=["cx", "rz", "sx", "x"], optimization_level=1)
print(Operator(t).equiv(Operator(qc)))                      # False
t2 = transpile(qc, basis_gates=["cx", "rz", "sx", "x"], optimization_level=1,
               qubits_initially_zero=False)
print(Operator(t2).equiv(Operator(qc)))                     # True
```

The pattern that triggers it is an MCX with at least 3 controls plus at least one qubit
that the synthesis can treat as a clean ancilla. It does not trigger in these cases:
- 1 or 2 controls;
- an MCX that already uses every qubit;
- `qubits_initially_zero=False`.

The idle qubit doesn't have to be completely untouched. It is also borrowed when it is
used only as a control of another MCX, and when it is wrapped in local gates such as
`h(4) … h(4)`. The results stay correct for every input with q4 = 0.

| Qiskit | opt 0 | opt 1 | opt 2 | opt 3 |
|---|---|---|---|---|
| 1.2.4 (option did not exist yet) | ok | ok | ok | ok |
| 1.3.0 | hazard | hazard | hazard | hazard |
| 1.4.3 | hazard | hazard | hazard | hazard |
| 2.0.0 | hazard | hazard | hazard | hazard |
| 2.6.1 | hazard | hazard | hazard | hazard |

(The table checks `Operator` equivalence on the reproducer above with `seed_transpiler=1`.
It covers only these versions; versions in between were not tested.)

## The demo

```
python examples/transpile_hazard/demo.py
```

- `block.py`: the source block, `mcx([0,1,2], 3)` on 5 qubits.
- `compiled.py`: `build()` is the default transpile; `build_safe()` uses `qubits_initially_zero=False`.
- `demo.py` shows four things:
  - (a) Aer sampling from |0..0>, with the controls in superposition, gives TVD 0, so **PASS**;
  - (b) Veriq vs the source gives **FAIL**, with counterexample |10100> (q4 = 1, q2 = 1);
  - (c) used as a `to_gate()` inside a program where q4 is a flag set to |1>, the block gives the wrong output;
  - (d) the safe compile is proved equivalent.

You can get the same result from the CLI:

```
veriq check examples/transpile_hazard/compiled.py -r examples/transpile_hazard/block.py   # FAIL
veriq check examples/transpile_hazard/block.py   # PASS + a note about the zero-init hazard
```

When Veriq is in `unitary` mode (the default), it compiles with `qubits_initially_zero=False`.
It also runs the default compile once and records `zero_init_hazard` in the evidence, so the
problem is reported as a note and doesn't hide inside a green result.
