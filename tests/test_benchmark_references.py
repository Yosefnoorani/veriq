"""The week-2 benchmark references must match their mathematical specs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

import references as R  # noqa: E402


def test_references_verified():
    out = R.verify_references()
    assert set(out) == set(R.TASKS)


def test_adder_truth_table_is_a_permutation():
    t = R.adder_truth_table()
    assert sorted(t.values()) == list(range(32))
    assert t[0b0_11_11] == 0b1_10_11  # a=3, b=3, c=0 -> b=2, carry=1
