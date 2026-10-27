# Hard-round prompt (verbatim, sent 2026-10-27 to ChatGPT, Claude, Gemini, Perplexity in new chats)

```
Write a single Python file using Qiskit 2.x (qiskit only) that defines exactly these 7 functions. Each returns a qiskit.QuantumCircuit with NO measurements and NO classical bits. Use Qiskit's little-endian convention (qubit 0 is the least significant bit). Do NOT use library algorithm circuits (no QFT/QFTGate, PhaseEstimation, GroverOperator, arithmetic library circuits, UnitaryGate, Isometry, StatePreparation, initialize, or Permutation gates) — build from standard gates. Correctness is checked exactly (up to global phase), so be precise.

1. build_maj5_oracle(): 6 qubits. q5 ^= MAJ(q0,q1,q2,q3,q4), where MAJ is 1 iff at least 3 of the 5 inputs are 1. q0..q4 unchanged. No extra qubits. Any standard gates allowed (x, cx, ccx, mcx, h, t, etc.).
2. build_cmul7_mod15(): 5 qubits. Control q4; work register x = q0..q3 (q0 = LSB). If q4=1: |x> -> |7x mod 15> for x in 0..14, and |15> -> |15>. If q4=0: identity. No extra qubits.
3. build_qpe_t(): 4 qubits. Quantum phase estimation of the T gate (eigenphase 1/8 on |1>) with a 3-qubit counting register q0..q2 (q0 = LSB) and the eigenstate qubit q3. Start from |0000>, prepare q3 in |1>, run QPE (including your own inverse QFT) so that the final state is exactly |q3=1>|counting = 1> (i.e. the counting register holds the integer 1 = 8 * 1/8).
4. build_c3x_linear(): 4 qubits. Exact 3-controlled X with controls q0,q1,q2 and target q3. Allowed gates ONLY: cx, h, x, s, sdg, t, tdg, rz, p. Every cx must act on adjacent qubits only (q0-q1, q1-q2, q2-q3), either direction. No extra qubits.
5. build_reverse6_nn(): 6 qubits. Reverse qubit order (qubit i <-> qubit 5-i, i.e. the permutation that maps |b5 b4 b3 b2 b1 b0> to |b0 b1 b2 b3 b4 b5>). Allowed gates ONLY: cx, and every cx must act on adjacent qubits only (qi, q(i+1)).
6. build_bv22(): 6 qubits. Bernstein–Vazirani for the secret s = 22 on a 5-qubit input register q0..q4 (q0 = LSB of s), oracle f(x) = s·x mod 2 written into ancilla q5. Start from |000000>; the ancilla must end back in |0>. The final state must be exactly |q5=0>|q4..q0 = 22>.
7. build_add3(): 6 qubits. a = q0..q2 (q0 = LSB), b = q3..q5 (q3 = LSB). |a>|b> -> |a>|(a+b) mod 8>, a unchanged, no extra qubits. Gates x, cx, ccx, mcx allowed.

Return only one code block with the full file.
```

Models: ChatGPT (free, Think on), Claude (free default), Gemini (Pro), Perplexity (free default). All answered first try.
