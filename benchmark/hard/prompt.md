# Hard-round prompt (RECONSTRUCTED)

> **Note:** the verbatim prompt sent to the four assistants on 2026-10-27 was not saved to disk.
> This text is a faithful reconstruction from the task specification used to build
> `references.py` and to check the answers. Function names, qubit counts and constraints
> match what all four assistants returned in `raw/*.py`. Wording may differ from the original.

---

Write Python (Qiskit 2.x) code with one function per task below. Each function takes no
arguments and returns a `QuantumCircuit`.

**Common rules**
- Qiskit little-endian convention: qubit 0 is the least-significant bit.
- Do **not** use `UnitaryGate`, `initialize`, `StatePreparation`, `PermutationGate` or library
  algorithm circuits (QFT/QFTGate, adders, etc.). Build everything from elementary gates
  (`mcx` is allowed).
- No measurements.

1. `build_maj5_oracle()` — 6 qubits. Phase-free reversible oracle: `q5 ^= MAJ(q0..q4)`
   (flip q5 iff at least 3 of q0..q4 are 1). q0..q4 unchanged.
2. `build_cmul7_mod15()` — 5 qubits. Controlled multiplication by 7 mod 15 on the 4-bit
   register x = q0..q3, control q4: if q4 = 1, x -> 7x mod 15 for x < 15, and 15 -> 15;
   if q4 = 0, identity.
3. `build_qpe_t()` — 4 qubits. Quantum phase estimation of the T gate with a 3-qubit counting
   register q0..q2 (q0 = least significant) and the eigenstate |1> on q3. Implement the inverse
   QFT by hand (with the correct qubit ordering). Final state must be |9> (counting register = 1, q3 = 1).
4. `build_c3x_linear()` — 4 qubits. Exact C3X (controls q0,q1,q2, target q3) using only
   `cx, h, x, s, sdg, t, tdg, rz, p`, with every `cx` between adjacent qubits only (linear chain
   0-1-2-3). No `ccx`/`mcx`/`swap`.
5. `build_reverse6_nn()` — 6 qubits. Reverse the qubit order (q0<->q5, q1<->q4, q2<->q3) using
   only `cx` between adjacent qubits.
6. `build_bv22()` — 6 qubits. Bernstein–Vazirani for the secret s = 22 (binary 10110) on the
   input register q0..q4, with the phase-kickback ancilla q5 returned to |0>. Final state must be |22>.
7. `build_add3()` — 6 qubits. a = q0..q2, b = q3..q5 (LSB first). In place: b <- (a + b) mod 8,
   a unchanged. Only `x, cx, ccx, mcx`.

Return only the code.
