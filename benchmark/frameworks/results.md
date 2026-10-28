# Cross-framework translations (Stage 5)

Generated 2026-10-28T18:51:40+02:00; 21 circuits (7 hard-round references + chatgpt, claude submissions), 40.1 s total.
Versions: qiskit 2.6.1, qiskit-qasm3-import 0.6.0, cirq-core 1.7.0, pytket 2.18.5, pytket-qiskit 0.79.0, mqt.qcec 3.11.0.

Each circuit is translated with the framework's own tool (qiskit.qasm3.dumps; qasm2 -> cirq.contrib.qasm_import -> cirq JSON; pytket qiskit_to_tk -> TKET JSON), loaded back through veriq's frontend, and checked against the Qiskit original with `decide_equivalence` in unitary mode (up to global phase). Ground truth comes from dense operators (all circuits <= 6 qubits).

## Faithful translations

| framework | translations | loaded | proven equivalent | exact incl. global phase | opaque ops |
|---|---|---|---|---|---|
| qasm3 | 21 | 21 | 21 | 21 | 0 |
| cirq | 21 | 21 | 21 | 21 | 0 |
| tket | 21 | 21 | 21 | 21 | 0 |

## Deliberate mis-translations

| framework / mistake | applicable | actually wrong | caught (NOT_EQUIVALENT) | missed | harmless for that circuit | false alarms |
|---|---|---|---|---|---|---|
| qasm3/reversed_qubit_order | 21 | 18 | 18 | 0 | 3 | 0 |
| qasm3/dropped_controlled_phase | 8 | 8 | 8 | 0 | 0 | 0 |
| cirq/reversed_qubit_order | 21 | 18 | 18 | 0 | 3 | 0 |
| cirq/dropped_controlled_phase | 8 | 8 | 8 | 0 | 0 | 0 |
| cirq/radians_as_exponent | 9 | 9 | 9 | 0 | 0 | 0 |
| tket/reversed_qubit_order | 21 | 18 | 18 | 0 | 3 | 0 |
| tket/dropped_controlled_phase | 3 | 3 | 3 | 0 | 0 | 0 |
| tket/radians_as_halfturns | 5 | 5 | 5 | 0 | 0 | 0 |

**Total: 87/87 actually-wrong translations caught, 0 missed, 0 false alarms.** 9 mistakes did not change the unitary of that particular circuit (e.g. reversing the qubits of a palindromic circuit such as reverse6_nn) and were correctly reported equivalent.

## Controls

| control | total | proven equivalent |
|---|---|---|
| tket/extra_global_phase_control | 21 | 21 |

An extra whole-circuit global phase is unobservable, so it must not be flagged; a *controlled* phase is observable and dropping it is caught (table above).

## Per circuit

| subject | framework | variant | status | truth | seconds |
|---|---|---|---|---|---|
| ref_maj5 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.202 |
| ref_maj5 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.713 |
| ref_maj5 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.118 |
| ref_maj5 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 1.292 |
| ref_maj5 | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.978 |
| ref_maj5 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 2.118 |
| ref_maj5 | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 1.026 |
| ref_maj5 | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 1.229 |
| ref_maj5 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 1.265 |
| ref_maj5 | tket | dropped_controlled_phase | n/a | n/a | |
| ref_maj5 | tket | radians_as_halfturns | n/a | n/a | |
| ref_maj5 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.127 |
| ref_cmul7 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.026 |
| ref_cmul7 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.014 |
| ref_cmul7 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.012 |
| ref_cmul7 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.055 |
| ref_cmul7 | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.039 |
| ref_cmul7 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.049 |
| ref_cmul7 | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.031 |
| ref_cmul7 | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.031 |
| ref_cmul7 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.047 |
| ref_cmul7 | tket | dropped_controlled_phase | n/a | n/a | |
| ref_cmul7 | tket | radians_as_halfturns | n/a | n/a | |
| ref_cmul7 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.012 |
| ref_qpe_t | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.007 |
| ref_qpe_t | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.007 |
| ref_qpe_t | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| ref_qpe_t | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.016 |
| ref_qpe_t | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.012 |
| ref_qpe_t | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.018 |
| ref_qpe_t | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.011 |
| ref_qpe_t | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.012 |
| ref_qpe_t | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.012 |
| ref_qpe_t | tket | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.01 |
| ref_qpe_t | tket | radians_as_halfturns | NOT_EQUIVALENT | differs | 0.01 |
| ref_qpe_t | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.004 |
| ref_c3x_linear | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.009 |
| ref_c3x_linear | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.017 |
| ref_c3x_linear | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.005 |
| ref_c3x_linear | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.023 |
| ref_c3x_linear | qasm3 | dropped_controlled_phase | n/a | n/a | |
| ref_c3x_linear | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.035 |
| ref_c3x_linear | cirq | dropped_controlled_phase | n/a | n/a | |
| ref_c3x_linear | cirq | radians_as_exponent | n/a | n/a | |
| ref_c3x_linear | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.019 |
| ref_c3x_linear | tket | dropped_controlled_phase | n/a | n/a | |
| ref_c3x_linear | tket | radians_as_halfturns | n/a | n/a | |
| ref_c3x_linear | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.005 |
| ref_reverse6_nn | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.003 |
| ref_reverse6_nn | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_reverse6_nn | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_reverse6_nn | qasm3 | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.003 |
| ref_reverse6_nn | qasm3 | dropped_controlled_phase | n/a | n/a | |
| ref_reverse6_nn | cirq | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_reverse6_nn | cirq | dropped_controlled_phase | n/a | n/a | |
| ref_reverse6_nn | cirq | radians_as_exponent | n/a | n/a | |
| ref_reverse6_nn | tket | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_reverse6_nn | tket | dropped_controlled_phase | n/a | n/a | |
| ref_reverse6_nn | tket | radians_as_halfturns | n/a | n/a | |
| ref_reverse6_nn | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_bv22 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.003 |
| ref_bv22 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_bv22 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_bv22 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.026 |
| ref_bv22 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| ref_bv22 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.002 |
| ref_bv22 | cirq | dropped_controlled_phase | n/a | n/a | |
| ref_bv22 | cirq | radians_as_exponent | n/a | n/a | |
| ref_bv22 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.002 |
| ref_bv22 | tket | dropped_controlled_phase | n/a | n/a | |
| ref_bv22 | tket | radians_as_halfturns | n/a | n/a | |
| ref_bv22 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.002 |
| ref_add3 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.012 |
| ref_add3 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.018 |
| ref_add3 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.007 |
| ref_add3 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.024 |
| ref_add3 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| ref_add3 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.032 |
| ref_add3 | cirq | dropped_controlled_phase | n/a | n/a | |
| ref_add3 | cirq | radians_as_exponent | n/a | n/a | |
| ref_add3 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.02 |
| ref_add3 | tket | dropped_controlled_phase | n/a | n/a | |
| ref_add3 | tket | radians_as_halfturns | n/a | n/a | |
| ref_add3 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.008 |
| chatgpt_maj5 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.117 |
| chatgpt_maj5 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.197 |
| chatgpt_maj5 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.075 |
| chatgpt_maj5 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.386 |
| chatgpt_maj5 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| chatgpt_maj5 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.464 |
| chatgpt_maj5 | cirq | dropped_controlled_phase | n/a | n/a | |
| chatgpt_maj5 | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.241 |
| chatgpt_maj5 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.174 |
| chatgpt_maj5 | tket | dropped_controlled_phase | n/a | n/a | |
| chatgpt_maj5 | tket | radians_as_halfturns | n/a | n/a | |
| chatgpt_maj5 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.077 |
| chatgpt_cmul7 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.407 |
| chatgpt_cmul7 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.293 |
| chatgpt_cmul7 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.167 |
| chatgpt_cmul7 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.863 |
| chatgpt_cmul7 | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.78 |
| chatgpt_cmul7 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.95 |
| chatgpt_cmul7 | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.828 |
| chatgpt_cmul7 | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.561 |
| chatgpt_cmul7 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.832 |
| chatgpt_cmul7 | tket | dropped_controlled_phase | n/a | n/a | |
| chatgpt_cmul7 | tket | radians_as_halfturns | n/a | n/a | |
| chatgpt_cmul7 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.175 |
| chatgpt_qpe_t | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.008 |
| chatgpt_qpe_t | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.007 |
| chatgpt_qpe_t | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_qpe_t | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.015 |
| chatgpt_qpe_t | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.013 |
| chatgpt_qpe_t | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.014 |
| chatgpt_qpe_t | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.011 |
| chatgpt_qpe_t | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.012 |
| chatgpt_qpe_t | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.012 |
| chatgpt_qpe_t | tket | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.015 |
| chatgpt_qpe_t | tket | radians_as_halfturns | NOT_EQUIVALENT | differs | 0.01 |
| chatgpt_qpe_t | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_c3x_linear | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.052 |
| chatgpt_c3x_linear | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.036 |
| chatgpt_c3x_linear | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.024 |
| chatgpt_c3x_linear | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.112 |
| chatgpt_c3x_linear | qasm3 | dropped_controlled_phase | n/a | n/a | |
| chatgpt_c3x_linear | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.102 |
| chatgpt_c3x_linear | cirq | dropped_controlled_phase | n/a | n/a | |
| chatgpt_c3x_linear | cirq | radians_as_exponent | n/a | n/a | |
| chatgpt_c3x_linear | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.081 |
| chatgpt_c3x_linear | tket | dropped_controlled_phase | n/a | n/a | |
| chatgpt_c3x_linear | tket | radians_as_halfturns | NOT_EQUIVALENT | differs | 0.031 |
| chatgpt_c3x_linear | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.021 |
| chatgpt_reverse6_nn | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.011 |
| chatgpt_reverse6_nn | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_reverse6_nn | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_reverse6_nn | qasm3 | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.011 |
| chatgpt_reverse6_nn | qasm3 | dropped_controlled_phase | n/a | n/a | |
| chatgpt_reverse6_nn | cirq | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_reverse6_nn | cirq | dropped_controlled_phase | n/a | n/a | |
| chatgpt_reverse6_nn | cirq | radians_as_exponent | n/a | n/a | |
| chatgpt_reverse6_nn | tket | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_reverse6_nn | tket | dropped_controlled_phase | n/a | n/a | |
| chatgpt_reverse6_nn | tket | radians_as_halfturns | n/a | n/a | |
| chatgpt_reverse6_nn | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.004 |
| chatgpt_bv22 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.005 |
| chatgpt_bv22 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.003 |
| chatgpt_bv22 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.003 |
| chatgpt_bv22 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.007 |
| chatgpt_bv22 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| chatgpt_bv22 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.004 |
| chatgpt_bv22 | cirq | dropped_controlled_phase | n/a | n/a | |
| chatgpt_bv22 | cirq | radians_as_exponent | n/a | n/a | |
| chatgpt_bv22 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.004 |
| chatgpt_bv22 | tket | dropped_controlled_phase | n/a | n/a | |
| chatgpt_bv22 | tket | radians_as_halfturns | n/a | n/a | |
| chatgpt_bv22 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.003 |
| chatgpt_add3 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.012 |
| chatgpt_add3 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.018 |
| chatgpt_add3 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.007 |
| chatgpt_add3 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.024 |
| chatgpt_add3 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| chatgpt_add3 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.032 |
| chatgpt_add3 | cirq | dropped_controlled_phase | n/a | n/a | |
| chatgpt_add3 | cirq | radians_as_exponent | n/a | n/a | |
| chatgpt_add3 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.019 |
| chatgpt_add3 | tket | dropped_controlled_phase | n/a | n/a | |
| chatgpt_add3 | tket | radians_as_halfturns | n/a | n/a | |
| chatgpt_add3 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.007 |
| claude_maj5 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.138 |
| claude_maj5 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.702 |
| claude_maj5 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.127 |
| claude_maj5 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 1.279 |
| claude_maj5 | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 1.032 |
| claude_maj5 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 2.157 |
| claude_maj5 | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 1.008 |
| claude_maj5 | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 1.212 |
| claude_maj5 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 1.244 |
| claude_maj5 | tket | dropped_controlled_phase | n/a | n/a | |
| claude_maj5 | tket | radians_as_halfturns | n/a | n/a | |
| claude_maj5 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.116 |
| claude_cmul7 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.07 |
| claude_cmul7 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.087 |
| claude_cmul7 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.053 |
| claude_cmul7 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.26 |
| claude_cmul7 | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.793 |
| claude_cmul7 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.278 |
| claude_cmul7 | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.741 |
| claude_cmul7 | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.745 |
| claude_cmul7 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.241 |
| claude_cmul7 | tket | dropped_controlled_phase | n/a | n/a | |
| claude_cmul7 | tket | radians_as_halfturns | n/a | n/a | |
| claude_cmul7 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.055 |
| claude_qpe_t | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.006 |
| claude_qpe_t | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.006 |
| claude_qpe_t | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| claude_qpe_t | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.014 |
| claude_qpe_t | qasm3 | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.012 |
| claude_qpe_t | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.014 |
| claude_qpe_t | cirq | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.012 |
| claude_qpe_t | cirq | radians_as_exponent | NOT_EQUIVALENT | differs | 0.011 |
| claude_qpe_t | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.011 |
| claude_qpe_t | tket | dropped_controlled_phase | NOT_EQUIVALENT | differs | 0.01 |
| claude_qpe_t | tket | radians_as_halfturns | NOT_EQUIVALENT | differs | 0.01 |
| claude_qpe_t | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.004 |
| claude_c3x_linear | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.012 |
| claude_c3x_linear | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.016 |
| claude_c3x_linear | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.006 |
| claude_c3x_linear | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.029 |
| claude_c3x_linear | qasm3 | dropped_controlled_phase | n/a | n/a | |
| claude_c3x_linear | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.039 |
| claude_c3x_linear | cirq | dropped_controlled_phase | n/a | n/a | |
| claude_c3x_linear | cirq | radians_as_exponent | n/a | n/a | |
| claude_c3x_linear | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.023 |
| claude_c3x_linear | tket | dropped_controlled_phase | n/a | n/a | |
| claude_c3x_linear | tket | radians_as_halfturns | NOT_EQUIVALENT | differs | 0.01 |
| claude_c3x_linear | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.006 |
| claude_reverse6_nn | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.011 |
| claude_reverse6_nn | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| claude_reverse6_nn | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.004 |
| claude_reverse6_nn | qasm3 | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.011 |
| claude_reverse6_nn | qasm3 | dropped_controlled_phase | n/a | n/a | |
| claude_reverse6_nn | cirq | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.004 |
| claude_reverse6_nn | cirq | dropped_controlled_phase | n/a | n/a | |
| claude_reverse6_nn | cirq | radians_as_exponent | n/a | n/a | |
| claude_reverse6_nn | tket | reversed_qubit_order | PROVEN_EQUIVALENT | equiv | 0.009 |
| claude_reverse6_nn | tket | dropped_controlled_phase | n/a | n/a | |
| claude_reverse6_nn | tket | radians_as_halfturns | n/a | n/a | |
| claude_reverse6_nn | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.004 |
| claude_bv22 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.005 |
| claude_bv22 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.003 |
| claude_bv22 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.003 |
| claude_bv22 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.006 |
| claude_bv22 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| claude_bv22 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.004 |
| claude_bv22 | cirq | dropped_controlled_phase | n/a | n/a | |
| claude_bv22 | cirq | radians_as_exponent | n/a | n/a | |
| claude_bv22 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.004 |
| claude_bv22 | tket | dropped_controlled_phase | n/a | n/a | |
| claude_bv22 | tket | radians_as_halfturns | n/a | n/a | |
| claude_bv22 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.003 |
| claude_add3 | qasm3 | faithful | PROVEN_EQUIVALENT | equiv | 0.015 |
| claude_add3 | cirq | faithful | PROVEN_EQUIVALENT | equiv | 0.04 |
| claude_add3 | tket | faithful | PROVEN_EQUIVALENT | equiv | 0.011 |
| claude_add3 | qasm3 | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.033 |
| claude_add3 | qasm3 | dropped_controlled_phase | n/a | n/a | |
| claude_add3 | cirq | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.06 |
| claude_add3 | cirq | dropped_controlled_phase | n/a | n/a | |
| claude_add3 | cirq | radians_as_exponent | n/a | n/a | |
| claude_add3 | tket | reversed_qubit_order | NOT_EQUIVALENT | differs | 0.028 |
| claude_add3 | tket | dropped_controlled_phase | n/a | n/a | |
| claude_add3 | tket | radians_as_halfturns | n/a | n/a | |
| claude_add3 | tket | extra_global_phase_control | PROVEN_EQUIVALENT | equiv | 0.011 |

## Finding: flattening for Cirq's QASM importer

Unrolling with Qiskit's default `transpile(..., optimization_level=0)` (qubits_initially_zero=True) changed the unitary of 3/21 circuits (ref_add3, chatgpt_maj5, chatgpt_add3): mcx synthesis may assume |0> helper qubits. The harness flattens with qubits_initially_zero=False; an unchecked converter pipeline would have shipped a wrong translation. Cirq circuits also drop qubits no gate touches, so the harness pads idle register qubits with `cirq.I`.

## Limitations

- OpenQASM 2 (the Cirq route) has no global phase; the proofs are up to global phase and the 'exact' column reports the dense-operator check including phase.
- Files over 64 kB are stored gzipped (`*.gz`); `stored_as`/`sha256` in results.json identify them.
- Equivalence is checked in unitary mode for every circuit, including the state-mode tasks (qpe_t, bv22): a translation must preserve the whole unitary.
- Mistakes are single, targeted edits of the first applicable gate; they are illustrations, not a random mutation study.
