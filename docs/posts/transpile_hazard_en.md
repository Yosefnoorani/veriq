# Your transpiled circuit passes every test and is still wrong

*Draft. Numbers from the Veriq hard round (Qiskit 2.6.1, qiskit-aer 0.18.2, mqt.qcec 3.11.0).*

## The hook

Here is a 5-qubit block with a single gate: `mcx([0,1,2], 3)`. Transpile it with Qiskit's
defaults, run it on Aer from |00000>, and the histogram matches the source exactly (TVD 0).
Put the controls in superposition and it still matches. Then feed it |10100> and the
compiled circuit flips the target, while the original does nothing.

I didn't go looking for this. It showed up as false alarms in my own tool.

## The bug (which is really a footgun)

Since Qiskit 1.3, `transpile()` takes `qubits_initially_zero=True` by default. Under that
assumption, `HighLevelSynthesis` may use idle qubits as *clean* ancillas, qubits assumed
to be |0>, to get a cheaper MCX decomposition (12 CX instead of 14 in this example).

This is intended and documented. The 1.3 release notes say to set it to `False` "when
manually calling transpiler passes on subcircuits of a larger quantum circuit." A Qiskit
maintainer put it plainly in issue #13562: default transpilation "is guaranteed to give
you the correct measurement results, but does not necessarily preserve the unitary."

So this isn't a Qiskit bug. The trap is quieter than a bug. Whenever you transpile a block
and then reuse it (`to_gate()`, `compose`, a cached library of compiled oracles), you can
end up with a block that is correct only if a qubit it "doesn't use" happens to be |0>.
You get no warning.

Minimal reproducer (triggers on 1.3.0, 1.4.3, 2.0.0 and 2.6.1 at optimization levels 0–3;
1.2.4 is fine):

```python
qc = QuantumCircuit(5); qc.mcx([0, 1, 2], 3)
t = transpile(qc, basis_gates=["cx", "rz", "sx", "x"])
Operator(t).equiv(Operator(qc))   # False
# fix: transpile(..., qubits_initially_zero=False)  -> True
```

It needs an MCX with at least 3 controls and at least one qubit that can be borrowed.
In my demo, a program sets q4 as a flag (|1>) and then calls the compiled block as a
`to_gate()` with all controls on. It should get |11111>. It gets |10111>.

## Why sampling can't catch it

The compiled block is correct for every input where q4 = 0. Any test that starts from
|0...0> keeps q4 = 0, so every histogram you collect is identical, however many shots you
take. More shots won't help: the test is asking the wrong question.

The same pattern shows up in my mutation study. I injected 1036 mutations into
verified circuits from the hard round, and 966 of them really changed the circuit:

- The standard Aer histogram from |0...0> caught 327 of them (**34%**).
- An exhaustive basis-input sweep caught 596 more.
- **43 (4.5%)** were caught only by the formal equivalence proof. 39 of those are phase
  mutants with TVD 0 on every basis input. The other 4 are π written as 3.14: TVD around
  1e-6, against a 0.05 threshold at 4096 shots.

## How Veriq catches it

Veriq proves the compiled circuit equivalent to its source as a unitary (QCEC, with a
dense operator fallback). It doesn't only compare samples. On this block:

```
✔ PASS  Statistical test (Aer)   TVD=0.000
✘ FAIL  Reference equivalence    Counterexample: on input |10100> the outputs overlap only 0.0000.
=> VERDICT: FAIL
```

Both results come from the same report: sampling is green and the proof is red, with a concrete input you
can rerun. When Veriq transpiles a block itself, it now uses
`qubits_initially_zero=False`. It also records a `zero_init_hazard` note whenever the
default compile would have broken the block.

I found this the honest way. In the hard round, 5 of 28 LLM-written circuits that were
correct got a FAIL from Veriq's own transpile check, until I traced the cause to this
default.

## Call to action

- If you transpile pieces and compose them later, pass `qubits_initially_zero=False`, or
  transpile only the final full circuit.
- If your test suite only samples from |0...0>, it can't see this class of bug.
- The demo is short: `python examples/transpile_hazard/demo.py`. It runs in about two seconds.
  I'd like to hear if it reproduces on your setup, or if you have other cases where
  sampling says PASS and the proof says no.
