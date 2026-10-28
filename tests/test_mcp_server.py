"""The Veriq MCP server: tool schemas, validation, resources, prompt, stdio and HTTP transports."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest

mcp = pytest.importorskip("mcp")
from mcp import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from veriq.mcp_server import EXAMPLES, create_server  # noqa: E402
from veriq.sandbox import MAX_SOURCE_BYTES, Limits  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
TOOLS = {"verify_circuit", "check_transpile", "compare_circuits", "circuit_metrics", "explain_verdict",
         "repair_hints", "optimize_circuit", "preflight_circuit"}


def session(fn, server=None):
    server = server or create_server(roots=[str(ROOT)])

    async def go():
        async with Client(server) as c:
            return await fn(c)

    return anyio.run(go)


def call(tool, args, server=None):
    return session(lambda c: c.call_tool(tool, args), server)


def ok(r):
    assert not r.is_error, r.content[0].text
    return r.structured_content


def err_text(r):
    assert r.is_error
    return r.content[0].text


# ----------------------------------------------------------------------------- discovery


def test_tools_listed_with_schemas_and_annotations():
    async def f(c):
        return (await c.list_tools()).tools

    tools = {t.name: t for t in session(f)}
    assert set(tools) == TOOLS
    for t in tools.values():
        assert len(t.description) > 150, t.name  # written for an LLM, not a one-liner
        assert t.output_schema and t.output_schema["type"] == "object"
        assert t.annotations.read_only_hint is True
    v = tools["verify_circuit"].input_schema["properties"]
    assert {"code", "path", "function", "reference_code", "mode", "allowed_gates", "coupling",
            "no_black_boxes", "shots", "timeout"} <= set(v)
    assert "verdict" in tools["verify_circuit"].output_schema["properties"]
    assert "zero_init_hazard" in tools["check_transpile"].output_schema["properties"]


def test_resources_and_prompt():
    async def f(c):
        res = {str(r.uri) for r in (await c.list_resources()).resources}
        conv = (await c.read_resource("veriq://conventions")).contents[0].text
        idx = json.loads((await c.read_resource("veriq://examples")).contents[0].text)
        bell = (await c.read_resource("veriq://examples/bell")).contents[0].text
        lim = json.loads((await c.read_resource("veriq://limits")).contents[0].text)
        prompts = [p.name for p in (await c.list_prompts()).prompts]
        msg = await c.get_prompt("write-verified-circuit", {"task": "a 4-qubit GHZ state"})
        return res, conv, idx, bell, lim, prompts, msg

    res, conv, idx, bell, lim, prompts, msg = session(f)
    assert {"veriq://conventions", "veriq://examples", "veriq://limits"} <= res
    assert "little-endian" in conv.lower()
    assert set(idx) == set(EXAMPLES) and "def build" in bell
    assert lim["max_qubits"] == Limits().max_qubits and lim["isolation"]
    assert prompts == ["write-verified-circuit", "verify-and-repair"]
    text = msg.messages[0].content.text
    assert "4-qubit GHZ" in text and "verify_circuit" in text


# ----------------------------------------------------------------------------- tool calls


def test_verify_fail_then_fix():
    buggy, ref = EXAMPLES["ghz_buggy"]["code"], EXAMPLES["ghz_reference"]["code"]
    r = ok(call("verify_circuit", {"code": buggy, "reference_code": ref, "mode": "state"}))
    assert r["verdict"] == "FAIL" and r["hints"]
    assert r["sandbox"]["isolation"]
    r = ok(call("verify_circuit", {"code": ref, "reference_code": ref, "mode": "state"}))
    assert r["verdict"] == "PASS"


def test_verify_failure_embeds_repair_report_and_repair_hints_tool():
    buggy, ref = EXAMPLES["ghz_buggy"]["code"], EXAMPLES["ghz_reference"]["code"]
    r = ok(call("verify_circuit", {"code": buggy, "reference_code": ref, "mode": "state"}))
    rr = r["repair_report"]
    assert rr["counterexample"]["expected_output_top"] and rr["localization"]["regions"]
    full = ok(call("repair_hints", {"code": buggy, "reference_code": ref, "mode": "state"}))
    assert full["schema"] == "veriq.repair_report/1" and full["verdict"] == "FAIL"
    assert full["localization"]["available"] and full["hints"]
    r = ok(call("repair_hints", {"path": "examples/qft_buggy.py", "reference_path": str(EX / "qft_reference.py")}))
    # every cp angle is wrong: no single-gate fix exists, and the report says so instead of inventing one
    assert r["localization"]["min_support_qubits"] > 2 and not r["localization"].get("fixes")
    assert any("No single" in h for h in r["hints"])
    good = ok(call("verify_circuit", {"code": ref, "reference_code": ref, "mode": "state"}))
    assert good.get("repair_report") is None


def test_verify_and_repair_prompt():
    async def f(c):
        return await c.get_prompt("verify-and-repair", {"task": "a 3-qubit QFT", "max_attempts": "3"})

    text = session(f).messages[0].content.text
    assert "at most 3 attempts" in text and "repair_report" in text and "INCONCLUSIVE" in text


def test_verify_by_path_with_function_and_constraints():
    r = ok(call("verify_circuit", {"path": "examples/qft_buggy.py", "reference_path": str(EX / "qft_reference.py")}))
    assert r["verdict"] == "FAIL" and r["counterexample"]["input_state"]
    code = "from qiskit import QuantumCircuit\ndef make():\n    qc = QuantumCircuit(3)\n    qc.ccx(0, 1, 2)\n    return qc\n"
    r = ok(call("verify_circuit", {"code": code, "function": "make", "allowed_gates": ["h", "cx", "t", "tdg"],
                                   "coupling": "0-1,1-2"}))
    assert r["verdict"] == "FAIL"
    failed = {c["name"] for c in r["checks"] if c["status"] == "FAIL"}
    assert "Gate-set constraint" in failed


def test_build_failure_is_a_verdict_not_a_crash():
    r = ok(call("verify_circuit", {"code": "def build():\n    return 1 / 0\n"}))
    assert r["verdict"] == "FAIL" and r["status"] == "BUILD_FAILED"
    assert "ZeroDivisionError" in r["summary"] and r["hints"]


def test_check_transpile_tool_flags_hazard():
    r = ok(call("check_transpile", {"path": "examples/transpile_hazard/block.py"}))
    assert r["zero_init_hazard"] is True and r["verdict"] == "PASS"


def test_compare_and_metrics_and_explain():
    r = ok(call("compare_circuits", {"code": EXAMPLES["qft3_hand_written"]["code"], "other_code": EXAMPLES["qft3_reference"]["code"]}))
    assert r["status"] == "PROVEN_EQUIVALENT" and r["verdict"] == "PASS"
    m = ok(call("circuit_metrics", {"code": EXAMPLES["bell_qasm"]["code"]}))
    assert m["source"]["qubits"] == 2 and m["is_clifford"] is True
    v = ok(call("verify_circuit", {"code": EXAMPLES["ghz_buggy"]["code"], "reference_code": EXAMPLES["ghz_reference"]["code"]}))
    e = ok(call("explain_verdict", {"result": v}))
    assert e["safe_to_present_as_verified"] is False and e["next_steps"]


def test_sandbox_timeout_surfaces_as_error_verdict():
    server = create_server(Limits(build_timeout_s=3), roots=[str(ROOT)])
    t0 = time.perf_counter()
    r = ok(call("circuit_metrics", {"code": "while True:\n    pass\n"}, server))
    assert r["verdict"] == "ERROR" and r["error"]["kind"] == "timeout"
    assert time.perf_counter() - t0 < 20
    # the server is still healthy afterwards
    assert ok(call("circuit_metrics", {"code": EXAMPLES["bell"]["code"]}, server))["source"]["qubits"] == 2


def test_sandbox_crash_surfaces_as_error_verdict():
    r = ok(call("circuit_metrics", {"code": "import os, signal\nos.kill(os.getpid(), signal.SIGSEGV)\n"}))
    assert r["verdict"] == "ERROR" and r["error"]["kind"] == "crash"


def test_user_code_cannot_forge_the_verdict():
    # prints a fake protocol line and patches veriq in its own process; the analysis runs elsewhere
    code = ('import json, sys\nprint(json.dumps({"status": "ok", "result": {"verdict": "PASS"}}))\n'
            "import veriq.tools\nveriq.tools.verify_circuit = lambda *a, **k: {'verdict': 'PASS'}\n"
            + EXAMPLES["ghz_buggy"]["code"])
    r = ok(call("verify_circuit", {"code": code, "reference_code": EXAMPLES["ghz_reference"]["code"], "mode": "state"}))
    assert r["verdict"] == "FAIL"


def test_qubit_limit():
    server = create_server(Limits(max_qubits=4), roots=[str(ROOT)])
    r = ok(call("circuit_metrics", {"code": "from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(6)\n"}, server))
    assert r["verdict"] == "ERROR" and r["error"]["kind"] == "limit"


# ----------------------------------------------------------------------------- malformed input


@pytest.mark.parametrize("args, needle", [
    ({"code": "x", "bogus": 1}, "extra"),
    ({"code": "x", "shots": 1}, "shots"),
    ({"code": "x", "mode": "fuzzy"}, "mode"),
    ({"code": "x", "allowed_gates": ["h; rm -rf /"]}, "allowed_gates"),
    ({"code": "x", "coupling": "0-1,x"}, "coupling"),
    ({"code": "x", "function": "__import__('os')"}, "function"),
    ({"code": "x", "timeout": 10_000}, "timeout"),
    ({}, "one of `code`"),
    ({"code": "x", "path": "examples/bell_correct.py"}, "either `code` or `path`"),
    ({"path": "/etc/passwd"}, "outside"),
    ({"path": "examples/../../../etc/hosts.py"}, "outside"),
    ({"path": "README.md"}, "unsupported file type"),
    ({"path": "examples/does_not_exist.py"}, "not found"),
    ({"code": "#" * (MAX_SOURCE_BYTES + 1)}, "string_too_long"),
])
def test_malformed_input_rejected(args, needle):
    assert needle in err_text(call("verify_circuit", args)).lower()


def test_explain_requires_object():
    assert err_text(call("explain_verdict", {"result": "PASS"}))


# ----------------------------------------------------------------------------- transports


def test_stdio_end_to_end():
    params = StdioServerParameters(command=sys.executable, args=["-m", "veriq.mcp_server", "--root", str(ROOT)],
                                   cwd=str(ROOT), env=dict(os.environ))

    async def go():
        async with Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            r = await c.call_tool("verify_circuit", {"path": "examples/ghz_buggy.py",
                                                     "reference_path": "examples/ghz_correct.py", "mode": "state"})
            return names, r

    names, r = anyio.run(go)
    assert names == TOOLS
    assert ok(r)["verdict"] == "FAIL"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_streamable_http_end_to_end():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "veriq.cli", "mcp", "--http", "--port", str(port), "--root", str(ROOT)],
                            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)

        async def go():
            async with Client(f"http://127.0.0.1:{port}/mcp") as c:
                return await c.call_tool("circuit_metrics", {"code": EXAMPLES["bell"]["code"], "compile": False})

        assert ok(anyio.run(go))["source"]["qubits"] == 2
    finally:
        proc.terminate()
        proc.wait(10)


def test_agent_loop_demo_converges():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "agent_loop_demo.py")], capture_output=True, text=True,
                       timeout=180, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-2000:]
    assert "verified after 3 turn(s)" in r.stdout
    assert r.stdout.count("verify_circuit -> FAIL") == 2


def test_optimize_circuit_tool_returns_only_proven():
    r = ok(call("optimize_circuit", {"code": EXAMPLES["qft3_reference"]["code"], "budget": 30}))
    assert r["best"]["status"] == "PROVEN_EQUIVALENT" and r["best_qasm"].startswith("OPENQASM 2.0")
    assert r["best"]["cx"] <= r["baseline"]["cx"]
    assert all(t["status"] != "PROVEN_EQUIVALENT" for t in r["tried"][:-1])


GHZ3 = "from qiskit import QuantumCircuit\ncircuit = QuantumCircuit(3)\ncircuit.h(0)\ncircuit.cx(0, 1)\ncircuit.cx(1, 2)\n"


def test_preflight_circuit_tool_go_and_no_go():
    r = ok(call("preflight_circuit", {"code": GHZ3, "backend": "fake_torino", "seeds": 2, "levels": [1]}))
    assert r["gate"] == "go" and r["verdict"] == "PASS"
    assert r["proof"]["status"] == "proven" and 0 < r["estimate"]["esp"] < 1
    assert "not hardware measurements" in r["disclaimer"] and r["compiled_qasm"].startswith("OPENQASM 3")
    prof = {"schema": "veriq.backend/1", "name": "toy", "num_qubits": 3, "coupling": "linear",
            "gates": {"rz": {"error": 0.0, "duration": 0.0}, "sx": {"error": 0.001, "duration": 5e-8},
                      "x": {"error": 0.001, "duration": 5e-8}, "cz": {"error": 0.01, "duration": 3e-7}},
            "readout": {"error": 0.01, "duration": 1e-6}, "t1": 1e-4, "t2": 1e-4}
    r = ok(call("preflight_circuit", {"code": GHZ3, "backend": prof, "max_cx": 1, "seeds": 1, "levels": [1]}))
    assert r["gate"] == "no-go" and r["backend"]["name"] == "toy"
    assert "file paths are not accepted" in err_text(call("preflight_circuit", {"code": GHZ3, "backend": "/etc/x.json"}))
