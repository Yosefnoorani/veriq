"""Deterministic demo of the agent loop Veriq's MCP server is built for.

A *simulated* LLM (a fixed rule table, no model calls, no network) is asked for a 3-qubit GHZ
circuit that uses only {h, cx} on a linear 0-1-2 device. It submits drafts to the real
`verify_circuit` tool over stdio and revises its draft based on the failed checks and hints, until the
verdict is PASS. Each run produces the same transcript.

    python scripts/agent_loop_demo.py
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import anyio
from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]

REFERENCE = """\
from qiskit import QuantumCircuit

def build():
    # trusted spec (constraints apply to the candidate only): fan-out GHZ from qubit 0
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 2)
    qc.cx(0, 1)
    return qc
"""

TEMPLATE = """\
from qiskit import QuantumCircuit

def build():
    qc = QuantumCircuit(3)
    qc.h(0)
{body}    return qc
"""


class SimulatedLLM:
    """A deterministic stand-in for a model: drafts a circuit, then patches it from tool feedback."""

    def __init__(self):
        self.gates = [("cx", 0, 1), ("cx", 2, 1)]  # first draft: classic control/target slip

    def draft(self) -> str:
        body = "".join(f"    qc.{g}({a}, {b})\n" for g, a, b in self.gates)
        return TEMPLATE.format(body=body)

    def revise(self, result: dict) -> str:
        failed = {c["name"] for c in result["checks"] if c["status"] == "FAIL"}
        if "State equivalence (from |0...0>)" in failed:
            # hint said the state is wrong; the model notices q2 never gets entangled and fans out from q0
            self.gates = [("cx", 0, 1), ("cx", 0, 2)]
            return "state differs from GHZ -> entangle q2 too: cx(0, 2)"
        if "Coupling-map constraint" in failed:
            # hint said 0-2 is not an edge; chain the CNOTs along the line instead
            self.gates = [("cx", 0, 1), ("cx", 1, 2)]
            return "cx(0, 2) is not on the 0-1-2 line -> chain cx(1, 2)"
        raise RuntimeError(f"simulated model has no rule for {sorted(failed)}")


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "veriq.mcp_server", "--root", str(ROOT)],
                                   cwd=str(ROOT))
    llm = SimulatedLLM()
    async with Client(params) as client:
        print("tools:", ", ".join(t.name for t in (await client.list_tools()).tools))
        for turn in range(1, 6):
            code = llm.draft()
            print(f"\n=== turn {turn}: model submits ===\n" + textwrap.indent(code, "  | "))
            r = await client.call_tool("verify_circuit", {
                "code": code, "reference_code": REFERENCE, "mode": "state",
                "allowed_gates": ["h", "cx"], "coupling": "linear", "shots": 2000})
            res = r.structured_content
            print(f"verify_circuit -> {res['verdict']}: {res['summary']}")
            for h in res["hints"]:
                print("  hint:", h)
            if res["verdict"] == "PASS":
                print(f"\nverified after {turn} turn(s); final metrics:", json.dumps(res["metrics"]["gate_counts"]))
                return 0
            print("model revises:", llm.revise(res))
    return 1


if __name__ == "__main__":
    raise SystemExit(anyio.run(main))
