# Limitations and roadmap

<sub>Moved from the README. See also the [README](../README.md).</sub>

## Limitations

- Formal checks cover the **unitary part** only; mid-circuit measurement, reset and classical control flow give `INCONCLUSIVE`.
- The exhaustive basis-state counterexample search goes up to 12 qubits, and the Operator check to 10. Above that, equivalence is *proven* only by the Clifford tableau, by QCEC (ZX, alternating or construction) or, for states, by exact MPS overlap. Everything else is MPS / random-simulation falsification (`PROBABLY`), which is reported as INCONCLUSIVE. Some bugs are invisible to product-state inputs, for example swapping the marked string of a 50-qubit phase oracle. These stay INCONCLUSIVE: they are not reported as PASS.
- MPS falsification is exact for low-entanglement circuits but slows down sharply as entanglement grows. Highly entangling 40-50 qubit circuits may hit the time cap.
- For more than 20 qubits the statistical test is a two-sample chi² on sampled outcomes. When the outputs are spread out (distinct outcomes > shots/10) it returns INCONCLUSIVE.
- The statistical test uses a noiseless simulator; noise-aware thresholds come later.
- Hardware preflight uses frozen IBM calibration snapshots (from `qiskit-ibm-runtime`) and illustrative JSON profiles; its ESP / duration / TVD numbers are estimates under a simple noise model (no crosstalk, leakage or drift), not hardware measurements. No live device or cloud account is used.
- Front-ends: Qiskit, OpenQASM 2/3, Cirq and TKET (exact conversion to Qiskit). No classical control or symbolic parameters in Cirq/TKET input; Cirq circuits drop untouched qubits unless `cirq.I` keeps them. Other frameworks (PennyLane, Braket, Quil) are not supported yet.
- Certificates: the canonical circuit hash depends on Qiskit's QASM exporter version (the source-file hash is the stable anchor); a signature checked only against the embedded key proves integrity, not identity; there is no sigstore or transparency log yet.

## Roadmap

- **Week 1 (this release):** CLI, four checks, HTML/JSON report, examples, tests.
- **Week 2 — benchmark:** collect ~20 circuits written by different LLMs (ChatGPT, Claude, Gemini, …) for standard tasks, run Veriq on all of them, and publish the bug-catch rate — the first evidence that the tool is needed.
- **Week 3 — QML claim audit:** check "quantum advantage" claims of quantum-ML notebooks against strong classical baselines on the same data, with fair hyper-parameter budgets and statistical significance.
- **MCP server:** ✅ `veriq mcp` (verify / check_transpile / compare / metrics / repair_hints / optimize / explain; sandboxed).
- **Repair + verified optimization:** ✅ repair reports with exact localization, `veriq repair` loop with pluggable fixers, `veriq optimize` (cheapest proven compilation).
- **Large circuits:** ✅ Clifford tableau, QCEC strategies with hard timeouts, MPS falsification, partitioning, and a scaling benchmark up to 50 qubits (200 for Clifford). Next: decision-diagram (DD) simulation of counterexamples, and noise-aware statistics.
- **Veriq Bench v0.1:** ✅ tasks, mutant corpus, `veriq bench run|corpus-eval|leaderboard`, leaderboard, paper draft. Next: a sandboxed runner, pinned model versions per submission, more tasks and rounds, and real-world (non-synthetic) bugs.
- **Week 4 — CI integration:** ✅ GitHub Action + `veriq ci` ([docs/ci.md](ci.md)) and a pytest plugin (`veriq_equiv` fixture, `assert_equivalent`; [docs/pytest.md](pytest.md)). Next: `assert_distribution`.
- **Hardware preflight:** ✅ `veriq preflight` (proven compile, native/coupling checks, ESP/duration/TVD estimates, noise-aware layout, go/warn/no-go; CI key, MCP tool, certificate). Next: live calibration fetch (opt-in), backend-aware optimization, idle-error-aware layout.
- **Multi-framework frontends:** ✅ OpenQASM 3, Cirq, TKET (CLI, CI, MCP, sandbox, certificates). Next: PennyLane, Braket, Quil.
- **Signed certificates:** ✅ `veriq.certificate/1`, Ed25519 `keygen`/`certify`/`cert verify --recheck`, CI artifacts, MCP. Next: sigstore keyless signing + transparency log, in-toto/SLSA attestation format.
