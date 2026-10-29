# Large circuits (20–50+ qubits)

<sub>Moved from the README. See also the [README](../README.md).</sub>

Above 12 qubits a brute-force truth table is impossible, so `veriq.scale.decide_equivalence` runs a tiered
engine (the CLI, the CI action and the MCP tools use it automatically):

1. **Partitioning:** if the joint interaction graph splits into independent blocks, each block is checked on its own.
2. **Exact Clifford check:** stabilizer tableaux are compared (equal up to global phase). For 100-200 qubits this takes seconds. On a mismatch, a stabilizer-input witness is attached.
3. **Operator** (≤10 qubits).
4. **mqt.qcec**, with configurable strategies (`zx`, `alternating`, `construction`, `simulation`). Each strategy runs in its own subprocess with a **hard** timeout, because QCEC's own timeout does not stop a large check.
5. **MPS falsification** (Aer matrix-product states): basis, `|+…+>` and random product inputs, with fidelity |⟨ψ|B†A|ψ⟩|². In state mode (`zero_input_equal`), the untruncated MPS overlap from |0…0⟩ is exact.

Every result has one of three statuses. **PROVEN** and **NOT** are decided. **PROBABLY** means only that the
simulated inputs (or QCEC's random simulations) found no difference. It is **falsification only** and veriq
reports it as `INCONCLUSIVE`, never as a proof.

```bash
python benchmark/scale/run.py          # GHZ, QFT, AQFT, oracle, Clifford+T, Clifford, Cuccaro, blocks; n=8..50
python benchmark/scale/report.py       # -> benchmark/scale/results.md, time_vs_qubits.png
```

Results: [benchmark/scale/results.md](../benchmark/scale/results.md) and [the chart](../benchmark/scale/time_vs_qubits.png).
