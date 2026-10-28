"""Sandbox worker: `python -I -m veriq._sandbox_worker` reads one JSON job on stdin, prints one JSON line.

Jobs:
  {"op": "build", "source": {"code"|"path", "function", "language", "framework"}, "workdir": ...}
      Runs UNTRUSTED code; returns the circuit as base64 QPY (or a build/load error).
  {"op": "analyze", "tool": "...", "circuits": {"candidate": qpy, "reference": qpy?}, "options": {...}}
      Runs only Veriq code on deserialized circuits.
Never imported by the server process.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys


def _block_network() -> None:
    import socket

    class _NoNet(socket.socket):
        def __init__(self, *a, **k):
            raise PermissionError("network access is disabled in the Veriq sandbox")

    def _deny(*a, **k):
        raise PermissionError("network access is disabled in the Veriq sandbox")

    socket.socket = _NoNet  # type: ignore[misc]
    socket.create_connection = _deny  # type: ignore[assignment]
    socket.getaddrinfo = _deny  # type: ignore[assignment]


def _qpy_dump(qc) -> str:
    from qiskit import qpy

    buf = io.BytesIO()
    qpy.dump(qc, buf)
    return base64.b64encode(buf.getvalue()).decode()


def _qpy_load(s: str):
    from qiskit import qpy

    return qpy.load(io.BytesIO(base64.b64decode(s)))[0]


def _build(job: dict) -> dict:
    from veriq.loader import BuildError, LoadError, load_circuit

    src = job["source"]
    workdir = job["workdir"]
    if "code" in src:
        lang = src.get("language") or "auto"
        code = src["code"]
        if lang == "auto":
            head = code.lstrip()
            lang = ("qasm" if head.upper().startswith("OPENQASM") else "json" if head.startswith("{")
                    else "python")
        fname = {"python": "candidate.py", "qasm": "candidate.qasm", "json": "candidate.json"}[lang]
        path = os.path.join(workdir, src.get("filename") or fname)
        with open(path, "w") as fh:
            fh.write(code)
    else:
        path = src["path"]
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured  # user prints must not corrupt the protocol line
    try:
        qc = load_circuit(path, src.get("function"), src.get("framework"))
    except BuildError as exc:
        return {"status": "build_error", "error_type": exc.error_type, "exception": exc.exc_type,
                "message": str(exc)[:2000], "stdout": captured.getvalue()[-2000:]}
    except LoadError as exc:
        return {"status": "load_error", "message": str(exc)[:2000]}
    finally:
        sys.stdout = real_stdout
    try:
        blob = _qpy_dump(qc)
    except Exception as exc:
        return {"status": "build_error", "error_type": "not serializable", "exception": type(exc).__name__,
                "message": f"circuit cannot be serialized to QPY: {exc!r}"[:2000]}
    return {"status": "ok", "qpy": blob, "name": qc.name, "num_qubits": qc.num_qubits,
            "frontend": (qc.metadata or {}).get("veriq_frontend", {}).get("framework", "qiskit"),
            "stdout": captured.getvalue()[-2000:]}


def _analyze(job: dict) -> dict:
    from veriq import tools

    circs = {k: (_qpy_load(v) if v else None) for k, v in job["circuits"].items()}
    max_q = int(job.get("max_qubits", 50))
    for k, qc in circs.items():
        if qc is not None and qc.num_qubits > max_q:
            return {"status": "limit", "message": f"{k} has {qc.num_qubits} qubits; this server allows {max_q}"}
    fn = getattr(tools, job["tool"])
    return {"status": "ok", "result": fn(**circs, **job.get("options", {}))}


def main() -> None:
    job = json.loads(sys.stdin.read())
    out_fd = os.dup(1)
    os.dup2(2, 1)  # anything written to fd 1 by native code or user code goes to stderr
    _block_network()
    if job["op"] == "build":
        res = _build(job)
    elif job["op"] == "analyze":
        res = _analyze(job)
    else:
        res = {"status": "protocol", "message": f"unknown op {job['op']!r}"}
    with os.fdopen(out_fd, "w") as fh:
        fh.write("\n" + json.dumps(res, default=str) + "\n")


if __name__ == "__main__":
    main()
