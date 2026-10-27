# Veriq as an MCP server

`veriq mcp` (or the `veriq-mcp` script) exposes Veriq's checks as [Model Context Protocol](https://modelcontextprotocol.io)
tools. An AI assistant that writes a Qiskit circuit can then **verify it before showing it to you**. It gets a
structured verdict, a concrete counterexample input, and hints it can act on, and it can revise until the verdict is `PASS`.

Built on the official Python SDK (`mcp` ≥ 2.3). In SDK v2 the high-level server class is `MCPServer`; v1 called it `FastMCP`.

```bash
pip install 'veriq[mcp]'          # or: pip install -e '.[mcp]' from a checkout
veriq mcp                         # stdio (default), what desktop clients spawn
veriq mcp --http --port 8765      # streamable HTTP on http://127.0.0.1:8765/mcp
```

> **Security: this server executes code.** Each tool call runs the Python you (or the model) pass it. The code runs
> in a sandboxed subprocess (see below), but the sandbox is defence in depth, not a security boundary you should
> expose to strangers. Run the server **locally, for yourself**. Bind HTTP to `127.0.0.1` (the default; Veriq warns
> if you pick anything else) and do not put it on a shared network.

## Client configuration

Use absolute paths. With a virtualenv, point at its `veriq-mcp` (or `python -m veriq.mcp_server`).
`--root` limits which files the `path` arguments can read (the default is the server's working directory).

**Claude Desktop**: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "veriq": {
      "command": "/path/to/veriq/.venv/bin/veriq-mcp",
      "args": ["--root", "/path/to/your/quantum/project"]
    }
  }
}
```

**Cursor**: `.cursor/mcp.json` in the project (or `~/.cursor/mcp.json` globally):

```json
{
  "mcpServers": {
    "veriq": {
      "command": "/path/to/veriq/.venv/bin/veriq-mcp",
      "args": ["--root", "${workspaceFolder}"],
      "env": { "VERIQ_MCP_MAX_QUBITS": "50" }
    }
  }
}
```

**Any stdio client**: the command is `veriq-mcp` or `python -m veriq.mcp_server` (same flags), speaking JSON-RPC on
stdin/stdout. Logs go to stderr.

**HTTP**: `veriq mcp --http --port 8765`, then connect to `http://127.0.0.1:8765/mcp` (streamable HTTP).

Flags and environment variables:

| flag | env | default | meaning |
|---|---|---|---|
| `--root DIR` (repeatable) | `VERIQ_MCP_ROOT` | cwd | directories `path` arguments may read |
| `--max-qubits N` | `VERIQ_MCP_MAX_QUBITS` | 50 | larger circuits are refused (`error.kind = "limit"`) |
| `--memory-mb N` | `VERIQ_MCP_MEMORY_MB` | 3072 | address-space limit per worker process |
| `--build-timeout S` | `VERIQ_MCP_BUILD_TIMEOUT` | 30 | wall clock for running the user's code |
| `--analyze-timeout S` | `VERIQ_MCP_ANALYZE_TIMEOUT` | 120 | wall clock for the checks (a tool's `timeout` can lower it) |

## Tools

All tools are read-only (`readOnlyHint`), take **strictly validated** input (unknown arguments, bad enums, gate
names that are not identifiers, malformed coupling strings, and oversize code all produce an error *before*
anything runs), and return **structured JSON** with an output schema.

A circuit is given as `code` (Python or OpenQASM 2/3 text) **or** `path` (a `.py`/`.qasm` file under a root), plus an
optional `function` (default: `build()`, else `make_circuit()`/`circuit()`, else a module-level `circuit`/`qc`).

| tool | what it answers | key outputs |
|---|---|---|
| `verify_circuit` | "Is this circuit correct?" Runs Veriq's full check suite: transpile integrity, equivalence to a trusted reference (`mode`: `unitary` or `state` = same state from \|0…0⟩), gate-set (`allowed_gates`), `coupling` (`linear`/`ring`/`all`/`0-1,1-2`), `no_black_boxes`, statistical test (`shots`, `expect`) | `verdict` PASS/FAIL/INCONCLUSIVE/ERROR, `checks[]`, `counterexample`, `metrics`, `hints[]` |
| `check_transpile` | "Did compilation change what my circuit does?" Compiles at `optimization_level` for `basis_gates`/`coupling`, and by default **both** with and without `qubits_initially_zero` | `equivalent`, `status`, `zero_init_hazard`, per-run `method`/`counterexample`/`equal_on_zero_input` |
| `compare_circuits` | "Are A and B the same?" (`mode` unitary or state) | `status` PROVEN_EQUIVALENT / NOT_EQUIVALENT / PROBABLY_EQUIVALENT / UNKNOWN, `method`, `counterexample` |
| `circuit_metrics` | Size/depth/2-qubit counts, before and after a standard compile | `source`, `compiled`, `is_clifford` |
| `explain_verdict` | Plain-language reading of any result above, and whether it is safe to present as verified | `explanation`, `next_steps[]`, `safe_to_present_as_verified` |

`PROBABLY_EQUIVALENT` means *no difference found by simulation*. It is **not** a proof: `verify_circuit` maps it to
`INCONCLUSIVE`, and `explain_verdict` returns `safe_to_present_as_verified: false`.

A user's code that raises an exception is a normal result (`verdict: FAIL`, `status: BUILD_FAILED`, with the exception
in `summary`). A sandbox failure is `verdict: ERROR` with `error.kind` = `timeout | memory | crash | limit | protocol`.
Invalid *arguments* are MCP tool errors (`isError: true`).

**Resources**: `veriq://conventions` (bit order, "equivalent up to global phase", what each verdict means);
`veriq://examples` and `veriq://examples/{name}` (buggy and correct circuits to try);
`veriq://limits` (this server's sandbox limits and isolation method).

**Prompt**: `write-verified-circuit(task, reference_hint?, mode?)` tells the model to write the circuit, call
`verify_circuit` (with a trusted reference where possible), fix the circuit until PASS, and only then answer, citing
the checks.

### Sample call

```json
{"name": "verify_circuit",
 "arguments": {"path": "examples/qft_buggy.py", "reference_path": "examples/qft_reference.py"}}
```

Response (`structuredContent`, evidence elided):

```json
{
  "verdict": "FAIL",
  "summary": "FAIL: Reference equivalence: NOT equivalent. Counterexample: on input |0001> the outputs overlap only 0.8132.",
  "checks": [
    {"name": "Transpile integrity",    "status": "PASS", "summary": "Proved equivalent after transpilation on 1 target(s)."},
    {"name": "Reference equivalence",  "status": "FAIL", "summary": "NOT equivalent. Counterexample: on input |0001> the outputs overlap only 0.8132."},
    {"name": "Statistical test (Aer)", "status": "PASS", "summary": "Consistent with expectation: TVD=0.022, chi2 p=0.64."},
    {"name": "Metrics",                "status": "PASS", "summary": "4 qubits, depth 8, 8 two-qubit gates; compiled: depth 33, 15 2q gates."}
  ],
  "counterexample": {"input_state": "|0001>", "fidelity": 0.813179,
                     "candidate_output_top": {"0000": 0.0625, "...": 0}, "reference_output_top": {"1010": 0.0625, "...": 0}},
  "metrics": {"qubits": 4, "depth": 8, "two_qubit_gates": 8, "gate_counts": {"cp": 6, "h": 4, "swap": 2}},
  "hints": ["Counterexample: on input |0001> the output overlaps the reference's by only 0.8132. Simulate that input by hand or with Statevector to find the step where they diverge."],
  "sandbox": {"isolation": "bwrap", "build_stdout": {}},
  "versions": {"veriq": "0.1.0", "qiskit": "2.6.1", "qiskit-aer": "0.18.2", "mqt.qcec": "3.11.0"}
}
```

Note that the statistical test **passes** here: on |0…0⟩ the bug does not show. Only the proof and the counterexample
catch it.

## The sandbox

Untrusted code **never runs in the server process**. Each call goes through two stages:

1. **Build**: one fresh worker per circuit (candidate and reference separately) runs the user's code and returns the
   circuit serialized as **QPY**, plus the captured stdout. Nothing else crosses the boundary.
2. **Analyze**: a *new, clean* worker loads the QPY and runs the checks. User code is never imported there, so it cannot
   patch Veriq or print a fake verdict. A test covers both attacks.

Each worker:

| limit | value |
|---|---|
| wall clock | build 30 s, analyze 120 s (configurable); on expiry the whole **process group** is SIGKILLed, including any children it spawned |
| CPU time | `RLIMIT_CPU` = 2 × wall + 5 s |
| memory | `RLIMIT_AS` = 3072 MB (configurable) → `MemoryError` or `error.kind = "memory"` |
| files | `RLIMIT_FSIZE` 50 MB, `RLIMIT_NOFILE` 256, no core dumps |
| network | **bubblewrap** (`bwrap --unshare-all`) when available, else `unshare -rn`: a fresh network namespace with no interfaces. In every case `socket` is also patched to refuse connections |
| filesystem | with bwrap: the root is mounted **read-only**, `/tmp` is a private tmpfs, `$HOME` is hidden (unless Veriq itself lives there), the only writable directory is a per-call temp workdir (removed afterwards), and `--root` dirs are mounted read-only |
| environment | scrubbed: only `PATH`, a temp `HOME`/`TMPDIR`, and single-thread BLAS/Qiskit settings. API keys and tokens in the server's env are **not** passed through |
| interpreter | `python -I` (isolated mode: ignores `PYTHON*` env vars and the user site dir) |
| input | code ≤ 200 kB; `path` must resolve (symlinks too) inside a root and end in `.py/.qasm/.qasm2/.qasm3` |
| output | ≤ 50 qubits (configurable), evidence trimmed (≤16 keys per count table, lists ≤50, strings ≤2000 chars) |
| concurrency | at most 2 tool calls run at once; the rest queue |

`veriq://limits` reports the isolation method in use: `bwrap`, `unshare`, or `socket-patch` (the weakest; it is
used when neither namespace tool works, e.g. in some containers). Force a method with `VERIQ_SANDBOX_ISOLATION`.

## Agent-loop demo

`python scripts/agent_loop_demo.py` starts the real server over stdio and drives it with a **simulated** model: a
fixed rule table, with no LLM calls and no network. Asked for a 3-qubit GHZ with gates {h, cx} on a linear 0-1-2
device, the "model":

1. submits `cx(0,1); cx(2,1)` → **FAIL** (state fidelity 0.25);
2. fans out with `cx(0,2)` → **FAIL** (coupling map: `cx(0,2)` is not an edge, hint: route or re-order);
3. chains `cx(1,2)` → **PASS**.

The transcript is deterministic, and `tests/test_mcp_server.py::test_agent_loop_demo_converges` runs it.
