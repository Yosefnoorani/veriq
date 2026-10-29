"""The README demo GIF claims: the histogram test PASSES, Veriq FAILS with a counterexample
and a localised region, and the safe compile PASSES. Keep those claims true."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "examples" / "transpile_hazard"


def test_histogram_test_passes_on_the_wrong_block():
    spec = importlib.util.spec_from_file_location("_demo_hist", D / "test_histogram.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.test_compiled_block_matches_source_histogram()  # must not raise


def _veriq(*args):
    return subprocess.run([sys.executable, "-m", "veriq.cli", *args], cwd=D, capture_output=True, text=True,
                          timeout=300)


def test_veriq_fails_it_with_counterexample_and_region(tmp_path):
    rr = tmp_path / "bug.json"
    p = _veriq("check", "compiled.py", "-r", "block.py", "--repair-report", str(rr), "-q")
    assert p.returncode == 1
    r = json.loads(rr.read_text())
    assert r["counterexample"]["input_state"] == "|10100>"
    assert r["counterexample"]["actual_output_top"] == {"11100": 1.0}
    region = r["localization"]["regions"][0]
    assert 4 in region["support"]  # the borrowed idle qubit is inside the localised region


def test_safe_compile_passes():
    assert _veriq("check", "compiled.py", "-f", "build_safe", "-r", "block.py", "-q").returncode == 0


def test_demo_assets_exist_and_are_small():
    gif = ROOT / "docs" / "assets" / "veriq_demo.gif"
    assert gif.exists() and gif.stat().st_size < 3_000_000
    assert (ROOT / "docs" / "assets" / "veriq_demo.png").exists()
