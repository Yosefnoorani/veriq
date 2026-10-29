"""pytest plugin (auto-registered through the ``pytest11`` entry point when veriq is installed).

Provides:
  * the ``veriq_equiv`` fixture: ``veriq_equiv(a, b, mode="unitary")`` asserts equivalence;
  * the ``veriq`` marker: ``@pytest.mark.veriq(timeout=60, mode="state", allow_unknown=False)`` sets the
    fixture's defaults for one test;
  * the ``veriq_timeout`` ini option / ``--veriq-timeout`` command-line option (default 30 s).

Qiskit is only imported when the fixture is first used, so the plugin adds no start-up cost to other test runs.
"""
from __future__ import annotations

import pytest


def pytest_addoption(parser):
    group = parser.getgroup("veriq")
    group.addoption("--veriq-timeout", action="store", type=float, default=None,
                    help="per-comparison timeout in seconds for veriq_equiv (default 30)")
    parser.addini("veriq_timeout", "per-comparison timeout in seconds for veriq_equiv", default="30")


def pytest_configure(config):
    config.addinivalue_line("markers", "veriq(timeout=None, mode='unitary', allow_unknown=False): "
                                       "defaults for the veriq_equiv fixture in this test")


@pytest.fixture
def veriq_equiv(request):
    """Return a callable ``(a, b, mode=..., timeout=..., allow_unknown=...)`` that asserts equivalence."""
    from .testing import assert_equivalent

    cfg = request.config
    timeout = cfg.getoption("--veriq-timeout") or float(cfg.getini("veriq_timeout"))
    defaults = {"timeout": timeout, "mode": "unitary", "allow_unknown": False}
    marker = request.node.get_closest_marker("veriq")
    if marker is not None:
        defaults.update({k: v for k, v in marker.kwargs.items() if v is not None})

    def _assert(a, b, **kw):
        return assert_equivalent(a, b, **{**defaults, **kw})

    return _assert
