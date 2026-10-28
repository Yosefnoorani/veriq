"""Veriq as an MCP server: lets an LLM agent prove its quantum circuits correct before answering.

    veriq mcp                      # stdio (default; what Claude Desktop / Cursor launch)
    veriq mcp --http --port 8765   # streamable HTTP on 127.0.0.1:8765/mcp

SECURITY: the tools EXECUTE the Python code they are given (that is how a Qiskit circuit is built).
Code never runs in this server process: each piece of code is built in its own sandboxed subprocess
(see veriq.sandbox) and only the resulting circuit (QPY) comes back; analysis runs in a second clean
subprocess. Still, run this server locally, for your own agent, not as a shared network service.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from .sandbox import MAX_SOURCE_BYTES, Limits, run_worker

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
GATE = r"^[a-z][a-z0-9_]{0,31}$"
COUPLING = r"^(linear|ring|all|[0-9]{1,3}-[0-9]{1,3}([,;] *[0-9]{1,3}-[0-9]{1,3})*)$"
SUFFIXES = {".py", ".qasm", ".qasm2", ".qasm3"}
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

INSTRUCTIONS = """Veriq proves quantum circuits correct. Use it BEFORE you present a quantum circuit as correct.
- verify_circuit: full check of a circuit you wrote (Python building a Qiskit QuantumCircuit, or OpenQASM),
  ideally against a trusted reference. Iterate until verdict is PASS; use `hints` and `counterexample`.
- compare_circuits: are two circuits the same unitary (or the same prepared state)?
- check_transpile: is Qiskit's compiled output of a circuit still equivalent (flags zero_init_hazard)?
- circuit_metrics: qubits, depth, 2-qubit gate count, compiled cost.
- explain_verdict: plain-language explanation of a result.
- repair_hints: on a FAIL, a machine-readable repair report: counterexample (expected vs actual output),
  the localized gate region where the bug is, exact single-gate fixes when one exists, hardware
  violations, metric deltas. verify_circuit also embeds a compact `repair_report` when it does not PASS.
- optimize_circuit: cheapest compilation (two-qubit gate count, then depth) that is PROVEN equivalent to
  the input; unproven candidates are never returned.
Statuses are honest: PROVEN_EQUIVALENT is a formal proof; PROBABLY_EQUIVALENT means only that simulations
found no difference (NOT a proof); NOT_EQUIVALENT comes with a counterexample input when one is found.
Read veriq://conventions for Qiskit's little-endian bit order. Python sources must define `build()`
returning a QuantumCircuit (or a module-level `circuit`), or name the builder with `function`."""

CONVENTIONS = """# Veriq conventions (read before writing circuits)

## Bit order: Qiskit is little-endian
- Qubit 0 is the RIGHTMOST character of a bitstring: on 3 qubits, "001" means qubit 0 = 1.
- `Statevector.from_label("01")` sets qubit 0 to 1 and qubit 1 to 0.
- Counterexample inputs like `|0001>` follow the same rule (qubit 0 = 1).
- A textbook QFT (qubit 0 = most significant) needs the final swap layer to match `QFTGate` / `QFT`.

## What "equivalent" means
- mode="unitary" (default): same unitary for EVERY input, up to one global phase. Use for oracles,
  adders, QFT, any reusable block.
- mode="state": same state prepared from |0...0>, up to global phase. Use for state preparation (GHZ, W,
  Grover output) where different unitaries are fine.

## Status vocabulary
- PROVEN_EQUIVALENT: a decision procedure (QCEC decision diagrams / ZX, exact Clifford tableau, or dense
  matrix) proved it.
- NOT_EQUIVALENT: proved different; a counterexample input is attached when one was found.
- PROBABLY_EQUIVALENT: random-stimuli simulations found no difference. Strong evidence, NOT a proof.
- UNKNOWN: limits (time, size) reached.
Tool verdicts: PASS / FAIL / INCONCLUSIVE (+ ERROR when the sandbox stopped the job: timeout, memory, crash).

## Building circuits from code
- Python: define `build()` returning a `QuantumCircuit` (or a module-level `circuit`). Several builders in
  one module: pass `function`. Only qiskit / numpy / the standard library are available. No network,
  no files outside the sandbox temp dir.
- OpenQASM 2 or 3 source is accepted too (starts with `OPENQASM`).
- Final measurements are ignored for equivalence; mid-circuit measurement/reset make it INCONCLUSIVE.
- `allowed_gates` / `coupling` / `no_black_boxes` constrain the circuit AS WRITTEN (before transpilation).
"""

EXAMPLES: dict[str, dict[str, str]] = {
    "bell": {"description": "Bell pair (|00>+|11>)/sqrt2, correct.", "code": '''from qiskit import QuantumCircuit


def build():
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    return qc
'''},
    "ghz_buggy": {"description": "3-qubit GHZ with a bug (CX on the wrong qubits). Verify in mode=state "
                                 "against `ghz_reference` to see a FAIL and its hints.", "code": '''from qiskit import QuantumCircuit


def build():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(0, 1)  # bug: should be cx(1, 2) or cx(0, 2)
    return qc
'''},
    "ghz_reference": {"description": "3-qubit GHZ reference.", "code": '''from qiskit import QuantumCircuit


def build():
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    return qc
'''},
    "qft3_reference": {"description": "3-qubit QFT reference from Qiskit's library (QFTGate), decomposed.",
                       "code": '''from qiskit import QuantumCircuit
from qiskit.circuit.library import QFTGate


def build():
    qc = QuantumCircuit(3)
    qc.append(QFTGate(3), range(3))
    return qc.decompose()
'''},
    "qft3_hand_written": {"description": "Hand-written 3-qubit QFT matching QFTGate (Hadamards, controlled "
                                         "phases, final swap).", "code": '''from math import pi

from qiskit import QuantumCircuit


def build():
    qc = QuantumCircuit(3)
    for j in reversed(range(3)):
        qc.h(j)
        for k in reversed(range(j)):
            qc.cp(pi / 2 ** (j - k), k, j)
    qc.swap(0, 2)
    return qc
'''},
    "bell_qasm": {"description": "Bell pair as OpenQASM 2.", "code": '''OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
h q[0];
cx q[0],q[1];
'''},
}


class Runner:
    """Resolves inputs, runs the sandbox stages, enforces limits."""

    def __init__(self, limits: Limits | None = None, roots: list[str] | None = None, max_concurrency: int = 2):
        self.limits = limits or Limits.from_env()
        rs = roots or [os.environ.get("VERIQ_MCP_ROOT") or os.getcwd()]
        self.roots = [Path(r).resolve() for r in rs]
        self.limiter = anyio.CapacityLimiter(max_concurrency)

    # ---- input validation
    def source(self, code: str | None, path: str | None, function: str | None, label: str,
               required: bool = True, prefix: str = "") -> dict[str, Any] | None:
        if code is not None and path is not None:
            raise ToolError(f"{label}: give either `{prefix}code` or `{prefix}path`, not both")
        if code is None and path is None:
            if required:
                raise ToolError(f"{label}: one of `{prefix}code` (source text) or `{prefix}path` (file) is required")
            if function:
                raise ToolError(f"{label}: `{label}_function` given without code or path")
            return None
        if function is not None and not IDENT.match(function):
            raise ToolError(f"{label}: function name {function!r} is not a valid Python identifier")
        if code is not None:
            if not code.strip():
                raise ToolError(f"{label}: code is empty")
            if len(code.encode()) > MAX_SOURCE_BYTES:
                raise ToolError(f"{label}: code is larger than {MAX_SOURCE_BYTES} bytes")
            return {"code": code, "function": function}
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.roots[0] / p
        p = p.resolve()
        if not any(p == r or r in p.parents for r in self.roots):
            raise ToolError(f"{label}: path {str(p)!r} is outside the allowed root(s) "
                            f"{[str(r) for r in self.roots]} (start the server with --root to change)")
        if p.suffix.lower() not in SUFFIXES:
            raise ToolError(f"{label}: unsupported file type {p.suffix!r}; expected one of {sorted(SUFFIXES)}")
        if not p.is_file():
            raise ToolError(f"{label}: file not found: {p}")
        return {"path": str(p), "function": function}

    # ---- sandbox stages (blocking; call through `run`)
    def _build(self, src: dict[str, Any]) -> dict[str, Any]:
        job = {"op": "build", "source": src}
        if "path" in src:
            job["readable_dirs"] = [str(Path(src["path"]).parent)]
        r = run_worker(job, self.limits.build_timeout_s, self.limits)
        if not r.ok:
            return {"status": "sandbox_error", "kind": r.error, "detail": r.detail, "stderr_tail": r.stderr_tail[-600:]}
        return r.data

    def execute(self, tool: str, sources: dict[str, dict | None], options: dict[str, Any]) -> dict[str, Any]:
        from concurrent.futures import ThreadPoolExecutor

        names = [k for k, v in sources.items() if v is not None]
        with ThreadPoolExecutor(max_workers=max(1, len(names))) as ex:
            built = dict(zip(names, ex.map(self._build, [sources[k] for k in names])))
        for k in names:
            b = built[k]
            st = b.get("status")
            if st == "ok":
                if b.get("num_qubits", 0) > self.limits.max_qubits:
                    return _error("limit", f"{k} has {b['num_qubits']} qubits; this server allows at most "
                                           f"{self.limits.max_qubits} (VERIQ_MCP_MAX_QUBITS / --max-qubits)")
                continue
            if st == "build_error":
                return _build_fail(k, b)
            if st == "load_error":
                raise ToolError(f"{k}: {b['message']}")
            if st == "sandbox_error":
                return _error(b["kind"], f"building the {k}: {b['detail']}", b.get("stderr_tail", ""))
            return _error("protocol", f"unexpected build result for {k}")
        job = {"op": "analyze", "tool": tool, "max_qubits": self.limits.max_qubits,
               "circuits": {k: (built[k]["qpy"] if k in built else None) for k in sources}, "options": options}
        r = run_worker(job, self.limits.analyze_timeout_s, self.limits)
        if not r.ok:
            return _error(r.error or "crash", f"analysis: {r.detail}", r.stderr_tail[-600:])
        if r.data.get("status") == "limit":
            return _error("limit", r.data["message"])
        res = r.data["result"]
        res["sandbox"] = {"isolation": self.limits.to_dict()["isolation"],
                          "build_stdout": {k: built[k].get("stdout", "")[-500:] for k in names if built[k].get("stdout")}}
        return res

    async def run(self, tool: str, sources: dict[str, dict | None], options: dict[str, Any]) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(partial(self.execute, tool, sources, options), limiter=self.limiter)


def _source_meta(src: dict[str, Any]) -> dict[str, Any]:
    """Path/function and sha256 of the source as given (code text or file bytes) for certificates."""
    import hashlib

    if "code" in src:
        return {"path": None, "function": src.get("function"),
                "source_sha256": hashlib.sha256(src["code"].encode()).hexdigest()}
    return {"path": src["path"], "function": src.get("function"),
            "source_sha256": hashlib.sha256(Path(src["path"]).read_bytes()).hexdigest()}


def _error(kind: str, detail: str, stderr_tail: str = "") -> dict[str, Any]:
    hints = {
        "timeout": "The job hit the sandbox time limit. Simplify the circuit, avoid loops that never end, or "
                   "raise --analyze-timeout / --build-timeout when starting the server.",
        "memory": "The job hit the sandbox memory limit. Use fewer qubits or raise --memory-mb.",
        "crash": "The sandboxed process crashed. Check the code for native-extension misuse.",
        "limit": "The circuit exceeds this server's size limits.",
    }
    return {"verdict": "ERROR", "status": "ERROR", "equivalent": None, "error": {"kind": kind, "detail": detail,
            "stderr_tail": stderr_tail}, "summary": f"ERROR ({kind}): {detail}",
            "hints": [hints.get(kind, "Internal error; retry or report it.")]}


def _build_fail(which: str, b: dict[str, Any]) -> dict[str, Any]:
    msg = b.get("message", "")
    return {"verdict": "FAIL", "status": "BUILD_FAILED", "equivalent": None,
            "summary": f"FAIL: the {which} code does not build: {msg[:400]}",
            "checks": [{"name": "Build", "status": "FAIL", "summary": f"Does not build: {msg[:400]}",
                        "evidence": {"which": which, "error_type": b.get("error_type"),
                                     "exception": b.get("exception"), "message": msg[:2000],
                                     "stdout": b.get("stdout", "")[-500:]}}],
            "counterexample": None, "metrics": {},
            "hints": [f"The {which} code raised {b.get('exception') or 'an error'}: {msg[:300]}. "
                      "It must define `build()` returning a QuantumCircuit (or `circuit`), or pass the builder "
                      "name in `function`."]}


# --------------------------------------------------------------------------- output schemas

Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE", "ERROR"]
EqStatus = Literal["PROVEN_EQUIVALENT", "NOT_EQUIVALENT", "PROBABLY_EQUIVALENT", "UNKNOWN", "BUILD_FAILED", "ERROR"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow")


class ErrorInfo(_Out):
    kind: str = Field(description="timeout | memory | crash | limit | protocol")
    detail: str
    stderr_tail: str = ""


class CheckOut(_Out):
    name: str
    status: Literal["PASS", "FAIL", "INCONCLUSIVE", "SKIPPED"]
    summary: str
    evidence: dict[str, Any] = {}
    seconds: float = 0.0


class Counterexample(_Out):
    input_state: str = Field(description="Input basis/product state, little-endian label like |0010> or |+0+>")
    fidelity: float = Field(description="|<candidate output|reference output>|^2 on that input")
    candidate_output_top: dict[str, float] = {}
    reference_output_top: dict[str, float] = {}


class OptimizeResult(_Out):
    summary: str | None = None
    mode: str | None = None
    best: dict[str, Any] | None = Field(None, description="cheapest PROVEN candidate (cx, depth, config, "
                                        "proof method); null when nothing could be proven")
    best_qasm: str | None = None
    baseline: dict[str, Any] | None = None
    qiskit_level3: dict[str, Any] | None = None
    tried: list[dict[str, Any]] = []
    proof_scope: str | None = None


class RepairReport(_Out):
    verdict: str | None = None
    mode: str | None = None
    summary: str | None = None
    failing_checks: list[dict[str, Any]] = []
    counterexample: dict[str, Any] | None = None
    localization: dict[str, Any] | None = Field(None, description="regions: suspected gate ranges; fixes: exact "
                                                "single-gate edits (delete/replace/insert) that make it correct")
    hardware_violations: list[dict[str, Any]] = []
    metric_deltas: dict[str, Any] = {}
    hints: list[str] = []
    error: ErrorInfo | None = None


class VerifyResult(_Out):
    verdict: Verdict
    summary: str
    checks: list[CheckOut] = []
    counterexample: Counterexample | None = None
    metrics: dict[str, Any] = {}
    hints: list[str] = Field(default=[], description="Concrete suggestions for fixing the circuit")
    repair_report: dict[str, Any] | None = Field(None, description="Compact repair report when not PASS "
                                                 "(counterexample, localized region, exact fixes)")
    certificate: dict[str, Any] | None = Field(None, description="Unsigned veriq.certificate/1 when "
                                               "certificate=true (sign with `veriq certify`)")
    error: ErrorInfo | None = None
    seconds: float | None = None


class CompareResult(_Out):
    verdict: Verdict
    equivalent: bool | None = Field(None, description="true only when PROVEN; null when undecided")
    status: EqStatus
    method: str | None = None
    summary: str
    counterexample: Counterexample | None = None
    hints: list[str] = []
    error: ErrorInfo | None = None


class TranspileResult(_Out):
    verdict: Verdict
    equivalent: bool | None = None
    status: str
    summary: str
    zero_init_hazard: bool | None = None
    runs: dict[str, Any] = {}
    hints: list[str] = []
    error: ErrorInfo | None = None


class MetricsResult(_Out):
    source: dict[str, Any] | None = None
    compiled: dict[str, Any] | None = None
    is_clifford: bool | None = None
    verdict: Verdict | None = None
    error: ErrorInfo | None = None


class Explanation(_Out):
    verdict: str
    explanation: str
    next_steps: list[str]
    safe_to_present_as_verified: bool


# --------------------------------------------------------------------------- server factory

Code = Annotated[str | None, Field(description="Circuit source: Python that builds a qiskit.QuantumCircuit "
                                               "(define build() or `circuit`), or OpenQASM 2/3 text.",
                                   max_length=MAX_SOURCE_BYTES)]
PathArg = Annotated[str | None, Field(description="Path to a .py or .qasm file on the server machine (inside "
                                                  "the allowed root). Use instead of code.", max_length=4096)]
Func = Annotated[str | None, Field(description="Builder function to call in a multi-function Python module.",
                                   max_length=64)]
Mode = Annotated[Literal["unitary", "state"], Field(description="unitary: same unitary for every input (blocks, "
                                                    "oracles, QFT); state: same state prepared from |0...0>.")]
ProofTimeout = Annotated[float, Field(ge=1, le=300, description="Seconds per formal proof attempt.")]


def create_server(limits: Limits | None = None, roots: list[str] | None = None) -> MCPServer:
    runner = Runner(limits, roots)
    mcp = MCPServer(name="veriq", title="Veriq: verified quantum circuits", instructions=INSTRUCTIONS,
                    version=_version())

    @mcp.tool(annotations=READ_ONLY, description="""Verify a quantum circuit you wrote, before presenting it.

Give the circuit as `code` (Python building a qiskit QuantumCircuit via build()/`circuit`, or OpenQASM) or a
file `path`. Strongly recommended: a trusted reference (`reference_code`/`reference_path`), e.g. built from
qiskit.circuit.library, so Veriq can PROVE equivalence. Runs: compile-integrity proof, reference equivalence
(mode=unitary or state), optional gate-set / coupling / no-black-box constraints, an Aer sampling test, metrics.
Returns verdict PASS | FAIL | INCONCLUSIVE | ERROR, per-check results, a counterexample input when not
equivalent, metrics and `hints` on how to fix it. If FAIL: fix the circuit and call again until PASS.""")
    async def verify_circuit(
        code: Code = None, path: PathArg = None, function: Func = None,
        reference_code: Code = None, reference_path: PathArg = None, reference_function: Func = None,
        mode: Mode = "unitary",
        allowed_gates: Annotated[list[Annotated[str, Field(pattern=GATE)]] | None,
                                 Field(max_length=64, description="Only these gate names may appear (as written), "
                                       "e.g. ['h','t','tdg','cx'].")] = None,
        coupling: Annotated[str | None, Field(pattern=COUPLING, max_length=20000,
                                              description="'linear', 'ring' or edges '0-1,1-2': 2-qubit gates must "
                                                          "act on these pairs; 3+-qubit gates are not allowed.")] = None,
        no_black_boxes: Annotated[bool, Field(description="FAIL on UnitaryGate, initialize, StatePreparation, "
                                              "library blocks (QFTGate...).")] = False,
        shots: Annotated[int, Field(ge=16, le=100_000, description="Aer shots for the statistical test.")] = 4096,
        expect: Annotated[dict[Annotated[str, Field(pattern=r"^[01 ]{1,64}$")], Annotated[float, Field(ge=0)]] | None,
                          Field(max_length=4096, description="Expected measurement distribution "
                                "{bitstring: probability} (little-endian), used when there is no reference.")] = None,
        timeout: ProofTimeout = 30.0,
        certificate: Annotated[bool, Field(description="Also return an UNSIGNED veriq.certificate/1 (input "
                                           "hashes, verdict, proof method, assumptions, versions). Save it as "
                                           "JSON and sign with `veriq certify`.")] = False,
    ) -> VerifyResult:
        cand = runner.source(code, path, function, "candidate")
        ref = runner.source(reference_code, reference_path, reference_function, "reference", required=False, prefix="reference_")
        if expect is not None and not expect:
            raise ToolError("expect: empty distribution")
        opts = {"mode": mode, "allowed_gates": allowed_gates, "coupling": coupling, "no_black_boxes": no_black_boxes,
                "shots": shots, "expect": expect, "timeout": timeout}
        if certificate:
            opts["certificate"] = True
            opts["sources"] = {k: _source_meta(v) for k, v in (("candidate", cand), ("reference", ref)) if v}
        return VerifyResult.model_validate(
            await runner.run("verify_circuit", {"candidate": cand, "reference": ref}, opts))

    @mcp.tool(annotations=READ_ONLY, description="""Check that Qiskit's transpiler output is equivalent to the source circuit.

Transpiles `code`/`path` with the given options (default: basis rz,sx,x,cx, linear coupling, optimization 3)
and proves the compiled circuit equivalent as a unitary. With qubits_initially_zero unset, compiles both ways
and reports `zero_init_hazard`: true when Qiskit's default (qubits_initially_zero=True) output is only
correct on |0...0> input, so `transpile(block)` must not be reused as a gate/sub-block.""")
    async def check_transpile(
        code: Code = None, path: PathArg = None, function: Func = None,
        optimization_level: Annotated[int, Field(ge=0, le=3)] = 3,
        basis_gates: Annotated[list[Annotated[str, Field(pattern=GATE)]] | None, Field(max_length=32)] = None,
        coupling: Annotated[str | None, Field(pattern=COUPLING, max_length=20000,
                                              description="'linear' (default), 'ring', 'all' or edges '0-1,1-2'.")] = "linear",
        seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 1234,
        qubits_initially_zero: Annotated[bool | None, Field(description="Compile with this setting only; unset = "
                                                            "check both and report zero_init_hazard.")] = None,
        timeout: ProofTimeout = 30.0,
    ) -> TranspileResult:
        cand = runner.source(code, path, function, "candidate")
        opts = {"optimization_level": optimization_level, "basis_gates": basis_gates, "coupling": coupling,
                "seed": seed, "qubits_initially_zero": qubits_initially_zero, "timeout": timeout}
        return TranspileResult.model_validate(await runner.run("check_transpile", {"candidate": cand}, opts))

    @mcp.tool(annotations=READ_ONLY, description="""Decide whether two circuits are equivalent.

Circuit A is `code`/`path`, circuit B is `other_code`/`other_path`. mode=unitary compares the full unitaries
(up to global phase); mode=state compares the states prepared from |0...0>. Returns `equivalent`
(true/false/null), `status` PROVEN_EQUIVALENT | NOT_EQUIVALENT | PROBABLY_EQUIVALENT (simulation only, not a
proof) | UNKNOWN, the `method` used, and a `counterexample` input state when not equivalent.""")
    async def compare_circuits(
        code: Code = None, path: PathArg = None, function: Func = None,
        other_code: Code = None, other_path: PathArg = None, other_function: Func = None,
        mode: Mode = "unitary", timeout: ProofTimeout = 30.0,
    ) -> CompareResult:
        a = runner.source(code, path, function, "candidate")
        b = runner.source(other_code, other_path, other_function, "reference", prefix="other_")
        return CompareResult.model_validate(
            await runner.run("compare_circuits", {"candidate": a, "reference": b}, {"mode": mode, "timeout": timeout}))

    @mcp.tool(annotations=READ_ONLY, description="""Cost metrics of a circuit: qubits, depth, size, two-qubit and 3+-qubit gate counts,
gate counts, Clifford or not, and (compile=true) the same after compiling to basis rz,sx,x,cx on a linear
coupling map with optimization level 3.""")
    async def circuit_metrics(code: Code = None, path: PathArg = None, function: Func = None,
                              compile: bool = True) -> MetricsResult:
        cand = runner.source(code, path, function, "candidate")
        return MetricsResult.model_validate(await runner.run("circuit_metrics", {"candidate": cand}, {"compile": compile}))

    @mcp.tool(annotations=READ_ONLY, description="""Repair report for a circuit that fails verification: what is wrong and where.

Same inputs as verify_circuit (candidate `code`/`path`, trusted reference, mode, constraints). Returns
`counterexample` (an input with the expected = reference and actual = candidate output distributions),
`localization` (the suspected gate `regions` by index, and exact single-gate `fixes` such as "replace gate #7
cx(2, 1) by cx(1, 2)" or "delete gate #4" when a 1- or 2-qubit change makes the circuit correct; exact up to
10 qubits), `hardware_violations` (gate set, coupling map, black boxes), `metric_deltas` vs the reference,
and `hints`. Apply a fix, then call verify_circuit again: a fix is only accepted once verify_circuit PASSes.""")
    async def repair_hints(
        code: Code = None, path: PathArg = None, function: Func = None,
        reference_code: Code = None, reference_path: PathArg = None, reference_function: Func = None,
        mode: Mode = "unitary",
        allowed_gates: Annotated[list[Annotated[str, Field(pattern=GATE)]] | None, Field(max_length=64)] = None,
        coupling: Annotated[str | None, Field(pattern=COUPLING, max_length=20000)] = None,
        no_black_boxes: bool = False,
        timeout: ProofTimeout = 30.0,
    ) -> RepairReport:
        cand = runner.source(code, path, function, "candidate")
        ref = runner.source(reference_code, reference_path, reference_function, "reference", required=False, prefix="reference_")
        opts = {"mode": mode, "allowed_gates": allowed_gates, "coupling": coupling, "no_black_boxes": no_black_boxes,
                "timeout": timeout}
        return RepairReport.model_validate(
            await runner.run("repair_hints", {"candidate": cand, "reference": ref}, opts))

    @mcp.tool(annotations=READ_ONLY, description="""Find the cheapest PROVEN-equivalent compilation of a circuit.

Compiles the circuit many ways (Qiskit optimization levels 0-3, several seeds, approximation off,
qubits_initially_zero=False, plus an extra resynthesis round), ranks candidates by two-qubit gate count and
then depth, and proves them cheapest-first. Returns `best` (+ `best_qasm`) = the first candidate with a
formal PROVEN_EQUIVALENT proof; a candidate that is only PROBABLY_EQUIVALENT is never returned. `tried`
lists every proof attempt. mode="state" only requires the same state from |0..0>.""")
    async def optimize_circuit(
        code: Code = None, path: PathArg = None, function: Func = None,
        mode: Mode = "unitary",
        basis_gates: Annotated[list[Annotated[str, Field(pattern=GATE)]] | None, Field(max_length=16)] = None,
        coupling: Annotated[str | None, Field(pattern=COUPLING, max_length=20000)] = None,
        seeds: Annotated[int, Field(ge=1, le=8)] = 3,
        allow_permutation: bool = False,
        timeout: Annotated[float, Field(ge=1, le=60)] = 20.0,
        budget: Annotated[float, Field(ge=5, le=90, description="total seconds for the whole search")] = 60.0,
    ) -> OptimizeResult:
        cand = runner.source(code, path, function, "candidate")
        opts = {"mode": mode, "basis_gates": basis_gates, "coupling": coupling, "seeds": seeds,
                "allow_permutation": allow_permutation, "timeout": timeout, "budget": budget}
        return OptimizeResult.model_validate(await runner.run("optimize_circuit", {"candidate": cand}, opts))

    @mcp.tool(annotations=READ_ONLY, description="""Explain a Veriq result in plain language with concrete next steps.

Pass the JSON object returned by verify_circuit, compare_circuits or check_transpile as `result`. Executes no
code.""")
    async def explain_verdict(result: Annotated[dict[str, Any], Field(description="A Veriq tool result object.")]
                              ) -> Explanation:
        return Explanation.model_validate(explain(result))

    @mcp.resource("veriq://conventions", name="conventions", mime_type="text/markdown",
                  description="Bit order (little-endian), equivalence modes and the status vocabulary.")
    def conventions() -> str:
        return CONVENTIONS

    @mcp.resource("veriq://examples", name="examples", mime_type="application/json",
                  description="Index of example circuits (correct and buggy) to try the tools with.")
    def examples_index() -> str:
        return json.dumps({k: {"description": v["description"], "uri": f"veriq://examples/{k}"}
                           for k, v in EXAMPLES.items()}, indent=2)

    @mcp.resource("veriq://examples/{name}", name="example", mime_type="text/plain",
                  description="Source of one example circuit; pass it as `code`.")
    def example(name: str) -> str:
        if name not in EXAMPLES:
            raise ValueError(f"unknown example {name!r}; see veriq://examples")
        return EXAMPLES[name]["code"]

    @mcp.resource("veriq://limits", name="limits", mime_type="application/json",
                  description="Sandbox limits of this server (timeouts, memory, max qubits, isolation).")
    def limits_res() -> str:
        return json.dumps(dict(runner.limits.to_dict(), roots=[str(r) for r in runner.roots]), indent=2)

    @mcp.prompt(name="write-verified-circuit", title="Write a verified quantum circuit",
                description="Write a Qiskit circuit for a task and prove it with verify_circuit before answering.")
    def write_verified_circuit(task: str, reference_hint: str = "", mode: str = "unitary") -> str:
        ref = (f"\nUse this as the trusted reference: {reference_hint}" if reference_hint else
               "\nIf Qiskit's library has the operation (QFTGate, MCXGate, PhaseOracle, ...), build a reference "
               "from it in `reference_code`.")
        return f"""Task: {task}

Write Python that defines `build()` returning a qiskit QuantumCircuit for this task.{ref}
Before you answer:
1. Read veriq://conventions (Qiskit is little-endian: qubit 0 is the rightmost bit).
2. Call the `verify_circuit` tool with your code (mode="{mode}") and the reference.
3. If the verdict is not PASS, use `counterexample` and `hints` to fix the circuit and call verify_circuit
   again. Repeat until PASS (at most 5 attempts).
4. Answer with the final code and quote the verdict and the proof method from the last result. Never call a
   circuit verified if the last verdict was FAIL, INCONCLUSIVE or ERROR, or the status was only
   PROBABLY_EQUIVALENT; say so explicitly instead."""

    @mcp.prompt(name="verify-and-repair", title="Verify a circuit and repair it until it is proved",
                description="Generate, verify, read the repair report, fix and re-verify, with bounded retries.")
    def verify_and_repair(task: str, reference_hint: str = "", mode: str = "unitary", max_attempts: str = "5") -> str:
        ref = (f"\nTrusted reference: {reference_hint}" if reference_hint else
               "\nBuild a trusted reference from qiskit.circuit.library (QFTGate, MCXGate, PhaseOracle, ...) or an "
               "explicit truth table, and pass it as `reference_code`.")
        return f"""Task: {task}

Write Python that defines `build()` returning a qiskit QuantumCircuit for this task.{ref}
Loop, at most {max_attempts} attempts:
1. Call `verify_circuit` with your code, the reference and mode="{mode}".
2. If the verdict is PASS: stop. If it is INCONCLUSIVE or ERROR: stop and say the circuit is NOT verified
   (do not keep editing blindly; report what could not be decided).
3. If it is FAIL: read `repair_report` (or call `repair_hints` for the full report):
   - `counterexample`: the input where it breaks, expected (reference) vs actual (candidate) outputs;
   - `localization.regions`: the gate indices where the bug is; `localization.fixes`: exact single-gate
     edits that make it correct, when one exists;
   - `hardware_violations`: gates or qubit pairs that the constraints forbid.
   Fix the code (prefer the smallest edit that the report points to), then go to 1.
Answer with the final code and quote the last verdict and proof method. If you ran out of attempts, or the
last verdict was not PASS, say explicitly that the circuit is NOT verified. Never present a circuit as
verified on PROBABLY_EQUIVALENT."""

    _forbid_unknown_arguments(mcp)
    mcp._veriq_runner = runner  # for tests
    return mcp


def _forbid_unknown_arguments(mcp: MCPServer) -> None:
    """Strict inputs: a misspelled argument (e.g. `refrence_code`) is an error, not silently ignored."""
    manager = getattr(mcp, "_tool_manager", None)
    if manager is None:  # SDK internals changed; fail loudly rather than silently accept unknown args
        raise RuntimeError("cannot enforce strict tool arguments with this mcp SDK version")
    for tool in manager.list_tools():
        meta = tool.fn_metadata
        base = meta.arg_model
        strict = type(base.__name__, (base,), {"model_config": ConfigDict(**base.model_config, extra="forbid"),
                                               "__module__": base.__module__})
        meta.arg_model = strict
        tool.parameters = dict(tool.parameters, additionalProperties=False)


def explain(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict) or not ("verdict" in result or "status" in result):
        raise ToolError("result must be an object returned by a Veriq tool (with `verdict` or `status`)")
    v = str(result.get("verdict") or result.get("status"))
    st = result.get("status")
    lines: list[str] = []
    meaning = {
        "PASS": "Every applicable check passed. Where a reference was given, equivalence was formally proved.",
        "FAIL": "At least one check found a real defect. The circuit is wrong for the stated spec.",
        "INCONCLUSIVE": "Nothing failed, but at least one property could not be decided within the limits.",
        "ERROR": "The sandbox stopped the job (time, memory, crash or size limit); no verdict about the circuit.",
        "PROVEN_EQUIVALENT": "Formally proved equivalent.",
        "NOT_EQUIVALENT": "Proved NOT equivalent.",
        "PROBABLY_EQUIVALENT": "Simulations found no difference, but this is not a proof.",
        "UNKNOWN": "Could not decide.",
    }
    lines.append(meaning.get(v, f"Verdict {v}."))
    if st and st != v and st in meaning:
        lines.append(meaning[st])
    for c in result.get("checks", []) or []:
        if c.get("status") in ("FAIL", "INCONCLUSIVE"):
            lines.append(f"{c.get('name')}: {c.get('status')}: {c.get('summary')}")
    cx = result.get("counterexample")
    if cx:
        lines.append(f"Counterexample: start from {cx.get('input_state')} (little-endian; rightmost = qubit 0). "
                     f"Your output and the reference's overlap only {cx.get('fidelity')}.")
    if result.get("zero_init_hazard"):
        lines.append("zero_init_hazard: Qiskit's default transpile used untouched qubits as clean ancillas; the "
                     "compiled block is only valid on |0...0>.")
    nxt = list(result.get("hints") or [])
    if not nxt:
        nxt = {"PASS": ["Present the circuit and cite the proof."],
               "PROVEN_EQUIVALENT": ["Present the circuit and cite the proof."],
               "PROBABLY_EQUIVALENT": ["Do not call it proved. Reduce the size or try a longer timeout."],
               }.get(v, ["Fix the circuit using the evidence above and verify again."])
    trustworthy = v in ("PASS", "PROVEN_EQUIVALENT")
    return {"verdict": v, "explanation": " ".join(lines), "next_steps": nxt, "safe_to_present_as_verified": trustworthy}


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("veriq")
    except Exception:
        return "0"


def build_parser(p: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    p = p or argparse.ArgumentParser(prog="veriq-mcp", description="Veriq MCP server (stdio by default).")
    p.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    p.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1; keep it local)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--root", action="append", help="directory that `path` inputs may read from (repeatable; "
                                                   "default: current directory)")
    p.add_argument("--max-qubits", type=int, help="largest circuit accepted (default 50)")
    p.add_argument("--memory-mb", type=int, help="address-space limit per sandbox process (default 3072)")
    p.add_argument("--build-timeout", type=float, help="seconds to build one circuit from code (default 30)")
    p.add_argument("--analyze-timeout", type=float, help="seconds for one analysis (default 120)")
    return p


def main(argv: list[str] | None = None, args: argparse.Namespace | None = None) -> int:
    args = args or build_parser().parse_args(argv)
    lim = Limits.from_env()
    if args.max_qubits:
        lim.max_qubits = args.max_qubits
    if args.memory_mb:
        lim.memory_mb = args.memory_mb
    if args.build_timeout:
        lim.build_timeout_s = args.build_timeout
    if args.analyze_timeout:
        lim.analyze_timeout_s = args.analyze_timeout
    server = create_server(lim, args.root)
    if args.http:
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(f"veriq-mcp: WARNING: serving code-executing tools on {args.host}; anyone who can reach it can "
                  "run code on this machine.", file=sys.stderr)
        anyio.run(lambda: server.run_streamable_http_async(host=args.host, port=args.port))
    else:
        server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
