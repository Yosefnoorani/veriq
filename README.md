# Veriq — a truth layer for AI-written quantum code

![Veriq demo: a compiled circuit passes the histogram test, Veriq proves it wrong with a counterexample and a bug region](docs/assets/veriq_demo.gif)

**Tests and histograms say "looks right". Veriq proves whether a quantum circuit *is* right and, when it isn't, shows the input that breaks it.**

| | |
|---|---|
| **2.7% – 5.4%** | of published model solutions that **pass their benchmark's own tests are provably wrong** (7 strict, 14 counting gates wrong only on superposed inputs, of 257 passing QuanBench solutions from GPT-4.1 and GPT-4o; manually reviewed; a lower bound). [Study →](benchmark/real_bugs/README.md) |
| **34% vs 100%** | of 966 injected bugs caught by the usual Aer histogram from \|0…0⟩, vs. by Veriq's equivalence proof (0/98 false positives). [Veriq Bench →](benchmark/veriqbench/leaderboard/leaderboard.md) |
| **5 of 28** | correct LLM circuits whose *default* Qiskit compile is no longer the same unitary (the `qubits_initially_zero` hazard); only a unitary proof sees it. [Example →](examples/transpile_hazard/README.md) |

## Install

```bash
pip install veriq-quantum          # import name and CLI: veriq   (Python 3.10+)
# until the first PyPI release:  pip install "git+https://github.com/Yosefnoorani/veriq"
```

## Quickstart

```bash
veriq check candidate.py -r reference.py                 # PASS / FAIL / INCONCLUSIVE (exit 0 / 1 / 2)
veriq check compiled.py -r block.py --repair-report bug.json   # FAIL -> counterexample + bug region + fix
veriq check ghz.py -r ghz_ref.py --mode state             # compare states from |0...0> instead of unitaries
veriq optimize my_circuit.py -o best.qasm                 # fewer CX, proven equivalent
veriq mcp                                                 # let your AI assistant verify before it answers
```

## Features

- **Formal equivalence** (MQT QCEC, exact operator, Clifford tableaux) with a concrete counterexample input, plus transpile integrity and statistical tests: [usage](docs/usage.md)
- **pytest plugin**: the `veriq_equiv` fixture and `assert_equivalent(a, b)`: [docs/pytest.md](docs/pytest.md)
- **CI**: a GitHub Action with a sticky PR comment, and `veriq ci`: [docs/ci.md](docs/ci.md)
- **MCP server** for Claude Desktop, Cursor and other MCP clients (sandboxed): [docs/mcp.md](docs/mcp.md)
- **Repair**: bug localization and a bounded verify → fix loop: [docs/repair.md](docs/repair.md)
- **Verified optimization**: the cheapest compilation, proven equal: [docs/optimize.md](docs/optimize.md)
- **Hardware preflight**: go / warn / no-go before you submit: [docs/preflight.md](docs/preflight.md)
- **Large circuits** (20–50+ qubits): [docs/large-circuits.md](docs/large-circuits.md)
- **OpenQASM 3, Cirq and TKET** front-ends: [docs/frameworks.md](docs/frameworks.md)
- **Signed certificates** (Ed25519): [docs/certificates.md](docs/certificates.md)
- **Benchmarks**: Veriq Bench, the hard round, real bugs: [docs/benchmarks.md](docs/benchmarks.md)
- Limitations and roadmap: [docs/limitations.md](docs/limitations.md). Releasing: [docs/release.md](docs/release.md)

Apache-2.0
