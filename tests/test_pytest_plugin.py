"""The pytest plugin (veriq_equiv fixture, veriq marker) and veriq.testing.assert_equivalent."""
import math

import pytest
from qiskit import QuantumCircuit

from veriq.testing import EquivalenceError, assert_equivalent, check_equivalent

pytest_plugins = ["pytester"]


def _plugin_args():
    """The installed package registers the plugin via its pytest11 entry point; load it by hand otherwise."""
    from importlib.metadata import entry_points

    installed = any(ep.value == "veriq.pytest_plugin" for ep in entry_points(group="pytest11"))
    return [] if installed else ["-p", "veriq.pytest_plugin"]


def bell():
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    return qc


def swap_cx():
    qc = QuantumCircuit(2)
    qc.cx(0, 1); qc.cx(1, 0); qc.cx(0, 1)
    return qc


def swap_gate():
    qc = QuantumCircuit(2)
    qc.swap(0, 1)
    return qc


def test_unitary_equivalent_up_to_global_phase():
    a = QuantumCircuit(1); a.rz(math.pi / 2, 0)
    b = QuantumCircuit(1); b.s(0)
    assert assert_equivalent(a, b)["verdict"] == "equivalent"
    assert_equivalent(swap_cx(), swap_gate())


def test_not_equivalent_raises_with_counterexample():
    a = QuantumCircuit(2); a.cx(0, 1)
    b = QuantumCircuit(2); b.cx(1, 0)
    with pytest.raises(EquivalenceError) as ei:
        assert_equivalent(a, b)
    assert ei.value.verdict == "not_equivalent"
    assert "counterexample" in str(ei.value)
    assert isinstance(ei.value, AssertionError)


def test_state_mode_only_checks_zero_input():
    a = bell()
    b = QuantumCircuit(2); b.h(0); b.cx(0, 1); b.z(1); b.z(0)  # ZZ fixes the Bell state but not the unitary
    assert check_equivalent(a, b, mode="state")["verdict"] == "equivalent"
    assert check_equivalent(a, b, mode="unitary")["verdict"] == "not_equivalent"
    c = QuantumCircuit(2); c.x(0); c.cx(0, 1); c.x(0)  # differs from |0> after a prior gate
    d = QuantumCircuit(2); d.x(1)
    assert check_equivalent(c, d, mode="state")["verdict"] == "equivalent"
    assert check_equivalent(c, d, mode="unitary")["verdict"] == "not_equivalent"


def test_measured_mode_ignores_phase_before_measurement_but_not_superposed_inputs():
    a = QuantumCircuit(2, 2); a.cx(0, 1); a.measure([0, 1], [0, 1])
    b = QuantumCircuit(2, 2); b.cx(0, 1); b.cz(0, 1); b.s(0); b.measure([0, 1], [0, 1])
    assert check_equivalent(a, b, mode="measured")["verdict"] == "equivalent"
    assert check_equivalent(a, b, mode="unitary")["verdict"] == "not_equivalent"
    # a diagonal gate before measuring only q1 is a don't-care, even though it touches the unmeasured q0
    ch = QuantumCircuit(2, 1); ch.ch(0, 1); ch.measure(1, 0)
    extra = QuantumCircuit(2, 1); extra.ch(0, 1); extra.cz(0, 1); extra.measure(1, 0)
    assert check_equivalent(ch, extra, mode="measured")["verdict"] == "equivalent"
    bad = QuantumCircuit(2, 1); bad.h(1); bad.measure(1, 0)
    r = check_equivalent(ch, bad, mode="measured")
    assert r["verdict"] == "not_equivalent" and "counterexample" in r["evidence"]


def test_different_qubit_counts_and_unknown():
    with pytest.raises(EquivalenceError):
        assert_equivalent(QuantumCircuit(1), QuantumCircuit(2))
    mid = QuantumCircuit(1, 1); mid.measure(0, 0); mid.x(0)
    with pytest.raises(EquivalenceError) as ei:
        assert_equivalent(mid, QuantumCircuit(1, 1))
    assert ei.value.verdict == "unknown"
    assert assert_equivalent(mid, QuantumCircuit(1, 1), allow_unknown=True)["verdict"] == "unknown"


def test_qasm_text_and_bad_mode():
    src = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\nh q[0];\ncx q[0],q[1];\n'
    assert_equivalent(src, bell())
    with pytest.raises(ValueError):
        check_equivalent(bell(), bell(), mode="nope")
    with pytest.raises(TypeError):
        check_equivalent(42, bell())


def test_fixture_marker_and_options(pytester):
    pytester.makeini("[pytest]\nveriq_timeout = 7\n")
    pytester.makepyfile(
        """
        import pytest
        from qiskit import QuantumCircuit

        def test_ok(veriq_equiv):
            a = QuantumCircuit(1); a.h(0); a.h(0)
            veriq_equiv(a, QuantumCircuit(1))

        def test_fails(veriq_equiv):
            a = QuantumCircuit(1); a.x(0)
            veriq_equiv(a, QuantumCircuit(1))

        @pytest.mark.veriq(mode="state")
        def test_marker_mode(veriq_equiv):
            a = QuantumCircuit(2); a.cx(0, 1)          # identity on |00>
            veriq_equiv(a, QuantumCircuit(2))

        def test_ini_timeout(veriq_equiv, request):
            assert float(request.config.getini("veriq_timeout")) == 7
        """
    )
    res = pytester.runpytest(*_plugin_args(), "-q")
    res.assert_outcomes(passed=3, failed=1)
    res.stdout.fnmatch_lines(["*NOT unitary-equivalent*"])
    assert "veriq(timeout" in "\n".join(pytester.runpytest(*_plugin_args(), "--markers").outlines)
