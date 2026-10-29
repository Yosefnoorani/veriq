# pytest plugin

Installing Veriq registers a pytest plugin through the `pytest11` entry point. No configuration is needed.

```bash
pip install veriq-quantum
```

## `veriq_equiv` fixture

```python
from qiskit import QuantumCircuit

def test_my_swap_is_a_swap(veriq_equiv):
    mine = QuantumCircuit(2); mine.cx(0, 1); mine.cx(1, 0); mine.cx(0, 1)
    ref = QuantumCircuit(2); ref.swap(0, 1)
    veriq_equiv(mine, ref)                 # proved with QCEC / exact operator comparison
```

A failing comparison raises `AssertionError` (`veriq.testing.EquivalenceError`) with a counterexample input:

```
E   veriq.testing.EquivalenceError: circuits are NOT unitary-equivalent
E     counterexample: {'input_state': '|01>', 'fidelity': 0.0, ...}
```

Arguments: `veriq_equiv(a, b, mode="unitary", timeout=30, allow_unknown=False)`. `a` and `b` can be
`QuantumCircuit` objects, paths to circuit files (`.qasm`, `.qpy`, `.py`, anything `veriq check` loads), or
OpenQASM 2/3 source text.

## Modes

All modes ignore global phase.

| mode | passes when | use it for |
|---|---|---|
| `unitary` (default) | the circuits implement the same unitary (final measurements stripped) | gates, oracles, decompositions, compiler passes |
| `state` | they prepare the same state from \|0…0⟩ | state-preparation circuits |
| `measured` | every input state gives the same outcome probabilities on the measured qubits (phases just before measurement are don't-cares) | measured algorithm circuits where only statistics matter (≤ 10 qubits) |

`state` is weaker than `unitary`. A circuit can pass `state` and still be wrong on other inputs. In the
[real-bugs study](../benchmark/real_bugs/README.md), most model solutions that passed their tests but were
wrong failed in exactly this way.

## Undecided results

When Veriq cannot decide (timeout, mid-circuit measurement, or too many qubits for `measured`), the assertion
**fails** by default, because a test should not pass on "we could not tell". Pass `allow_unknown=True` to
accept undecided results.

## Marker and options

```python
import pytest

@pytest.mark.veriq(mode="state", timeout=120)
def test_ghz(veriq_equiv):
    veriq_equiv(build_ghz(20), reference_ghz(20))
```

- `@pytest.mark.veriq(timeout=..., mode=..., allow_unknown=...)` sets the fixture's defaults for one test.
- `veriq_timeout = 60` in `[pytest]` / `[tool.pytest.ini_options]`, or `--veriq-timeout 60` on the command
  line, sets the default timeout in seconds (default 30).

## Without the fixture

```python
from veriq.testing import assert_equivalent, check_equivalent

assert_equivalent(a, b, mode="unitary")
check_equivalent(a, b)   # -> {"verdict": "equivalent" | "not_equivalent" | "unknown", "mode": ..., "evidence": ...}
```

The plugin imports Qiskit only when the fixture is first used, so it adds no start-up cost to other test runs.
