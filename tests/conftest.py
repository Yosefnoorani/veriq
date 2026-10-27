from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"


@pytest.fixture
def ex():
    return lambda name: str(EX / name)
