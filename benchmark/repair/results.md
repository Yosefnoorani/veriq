# Repair report: localization accuracy + repair-loop demo

Generated 2026-10-28T16:57:14+02:00 by `benchmark/repair/run_repair.py` (166.1s).

Mutants of the hard-round study: 1036 (70 proved equivalent -> skipped).

**Localization accuracy (single-gate mutants): 847/958 = 88.4%**. On average 3.53 region(s) covering 18.1 gaps in total are flagged, in circuits of 79.36 gates.

Of the 111 misses, 97 still come with an exact single-gate fix inside a flagged region (proven: applying it makes the circuit equal to the reference), i.e. the bug can equally be fixed there (e.g. a CX deleted in one SWAP of a swap network). Counting those, the flagged region is a valid fix location in **98.5%** of single-gate mutants.

A hit means the reported region contains the injected mutation (deletion: the gap where the gate is missing; other operators: the changed gate or the gap right next to it). Regions can be wide when the bug commutes with its neighbours: then every position in the region is an equally valid place to fix it.

| operator | localized | single-gate hits | mean region (gaps) | with exact single-gate fix |
|---|---:|---:|---:|---:|
| delete_gate | 574 | 515/574 | 20.0 | 356 |
| negate_angle | 76 | 68/76 | 19.2 | 60 |
| pi_as_3.14 | 8 | n/a (multi-gate) | 83.2 | 0 |
| flip_cx | 296 | 252/296 | 14.4 | 278 |
| cp_to_crz | 12 | 12/12 | 12.9 | 0 |

| task | localized | single-gate hits | mean region (gaps) | with exact fix |
|---|---:|---:|---:|---:|
| maj5 | 75 | 75/75 | 17.9 | 21 |
| cmul7 | 142 | 139/142 | 23.7 | 118 |
| qpe_t | 93 | 88/89 | 12.1 | 0 |
| c3x_linear | 298 | 245/294 | 13.7 | 291 |
| reverse6_nn | 240 | 194/240 | 28.8 | 240 |
| bv22 | 80 | 68/80 | 13.2 | 0 |
| add3 | 38 | 38/38 | 3.6 | 24 |

## Repair-loop demo (offline demo fixer)

152/188 sampled mutants repaired to a PASS verdict; stop reasons: {'fixer_gave_up': 36, 'PASS': 152}.

The demo fixer applies the report's exact single-gate fixes, else tries small edits (delete, negate, flip cx, crz->cp, rz->p, 3.14->pi) inside the localized region. It knows this mutation vocabulary, so this measures the plumbing (report -> fixer -> re-verify -> stop), not LLM repair skill.

| assistant | task | mutation | verdict | stop | fixes |
|---|---|---|---|---|---|
| chatgpt | maj5 | delete #0 mcx(0, 1, 2, 5) | FAIL | fixer_gave_up |  |
| chatgpt | maj5 | delete #1 mcx(0, 1, 3, 5) | FAIL | fixer_gave_up |  |
| chatgpt | maj5 | delete #2 mcx(0, 2, 3, 5) | FAIL | fixer_gave_up |  |
| chatgpt | cmul7 | delete #0 x(2,) | PASS | PASS | insert x(2) before gate #0 |
| chatgpt | cmul7 | delete #2 mcx(4, 0, 2, 3, 1) | FAIL | fixer_gave_up |  |
| chatgpt | cmul7 | delete #20 x(0,) | PASS | PASS | insert x(0) before gate #11 |
| chatgpt | qpe_t | delete #0 x(3,) | FAIL | fixer_gave_up |  |
| chatgpt | qpe_t | delete #1 h(0,) | PASS | PASS | delete gate #11 h(0,) |
| chatgpt | qpe_t | delete #2 h(1,) | PASS | PASS | delete gate #8 h(1,) |
| chatgpt | qpe_t | negate #4 cp(0.7854)(0, 3) | PASS | PASS | negate the angle of gate #4 cp |
| chatgpt | qpe_t | negate #5 cp(1.5708)(1, 3) | PASS | PASS | negate the angle of gate #5 cp |
| chatgpt | qpe_t | negate #8 cp(-1.5708)(2, 1) | PASS | PASS | negate the angle of gate #5 cp |
| chatgpt | qpe_t | pi written as 3.14 in all 6 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| chatgpt | qpe_t | flip #13 cx(0, 2) -> cx(2, 0) | PASS | PASS | delete gate #13 cx(2, 0) |
| chatgpt | qpe_t | flip #14 cx(2, 0) -> cx(0, 2) | PASS | PASS | flip gate #14 cx(0, 2) -> cx(2, 0) |
| chatgpt | qpe_t | flip #15 cx(0, 2) -> cx(2, 0) | PASS | PASS | flip gate #15 cx(2, 0) -> cx(0, 2) |
| chatgpt | qpe_t | #4 cp(0.7854) -> crz (same angle)(0, 3) | PASS | PASS | gate #4: crz -> cp |
| chatgpt | qpe_t | #5 cp(1.5708) -> crz (same angle)(1, 3) | PASS | PASS | gate #5: crz -> cp |
| chatgpt | qpe_t | #6 cp(3.1416) -> crz (same angle)(2, 3) | PASS | PASS | gate #6: crz -> cp |
| chatgpt | c3x_linear | delete #6 p(2,) | PASS | PASS | insert p(pi/8)(2) before gate #0 |
| chatgpt | c3x_linear | delete #19 cx(0, 1) | PASS | PASS | delete gate #25 cx(0, 1) |
| chatgpt | c3x_linear | delete #22 cx(1, 2) | PASS | PASS | insert cx(0, 2) before gate #17 |
| chatgpt | c3x_linear | negate #1 p(0.3927)(0,) | PASS | PASS | replace gate #0 p(-pi/8)(0) by p(pi/8)(0) |
| chatgpt | c3x_linear | negate #2 p(0.3927)(1,) | PASS | PASS | replace gate #1 p(-pi/8)(1) by p(pi/8)(1) |
| chatgpt | c3x_linear | negate #4 p(-0.3927)(1,) | PASS | PASS | replace gate #3 p(pi/8)(1) by p(-pi/8)(1) |
| chatgpt | c3x_linear | pi written as 3.14 in all 15 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| chatgpt | c3x_linear | flip #11 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #10 cx(1, 0) by cx(0, 1) |
| chatgpt | c3x_linear | flip #18 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #17 cx(2, 1) by cx(1, 2) |
| chatgpt | c3x_linear | flip #34 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #33 cx(2, 1) by cx(1, 2) |
| chatgpt | reverse6_nn | delete #0 cx(0, 1) | PASS | PASS | insert cx(0, 1) before gate #0 |
| chatgpt | reverse6_nn | delete #1 cx(1, 0) | PASS | PASS | insert swap(0, 1) before gate #0 |
| chatgpt | reverse6_nn | delete #4 cx(2, 1) | PASS | PASS | insert swap(0, 2) before gate #0 |
| chatgpt | reverse6_nn | flip #2 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(0, 1) by swap(0, 1) |
| chatgpt | reverse6_nn | flip #3 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #3 cx(2, 1) by cx(1, 2) |
| chatgpt | reverse6_nn | flip #4 cx(2, 1) -> cx(1, 2) | PASS | PASS | replace gate #3 cx(1, 2) by swap(1, 2) |
| chatgpt | bv22 | delete #0 x(5,) | FAIL | fixer_gave_up |  |
| chatgpt | bv22 | delete #1 h(0,) | PASS | PASS | delete gate #0 h(0,) |
| chatgpt | bv22 | delete #2 h(1,) | FAIL | fixer_gave_up |  |
| chatgpt | bv22 | flip #7 cx(1, 5) -> cx(5, 1) | PASS | PASS | flip gate #9 cx(5, 1) -> cx(1, 5) |
| chatgpt | bv22 | flip #8 cx(2, 5) -> cx(5, 2) | PASS | PASS | flip gate #11 cx(5, 2) -> cx(2, 5) |
| chatgpt | bv22 | flip #9 cx(4, 5) -> cx(5, 4) | PASS | PASS | flip gate #13 cx(5, 4) -> cx(4, 5) |
| chatgpt | add3 | delete #0 mcx(0, 3, 4, 5) | FAIL | fixer_gave_up |  |
| chatgpt | add3 | delete #1 ccx(0, 3, 4) | FAIL | fixer_gave_up |  |
| chatgpt | add3 | delete #2 cx(0, 3) | PASS | PASS | insert cx(0, 3) before gate #2 |
| chatgpt | add3 | flip #2 cx(0, 3) -> cx(3, 0) | PASS | PASS | replace gate #5 cx(3, 0) by cx(0, 3) |
| chatgpt | add3 | flip #4 cx(1, 4) -> cx(4, 1) | PASS | PASS | replace gate #5 cx(4, 1) by cx(1, 4) |
| chatgpt | add3 | flip #5 cx(2, 5) -> cx(5, 2) | PASS | PASS | replace gate #5 cx(5, 2) by cx(2, 5) |
| claude | maj5 | delete #0 x(3,) | PASS | PASS | insert x(3) before gate #0 |
| claude | maj5 | delete #1 x(4,) | PASS | PASS | insert x(4) before gate #0 |
| claude | maj5 | delete #2 mcx(0, 1, 2, 3, 4, 5) | FAIL | fixer_gave_up |  |
| claude | cmul7 | delete #0 cx(1, 2) | PASS | PASS | insert cx(1, 2) before gate #0 |
| claude | cmul7 | delete #1 x(2,) | PASS | PASS | insert x(2) before gate #0 |
| claude | cmul7 | delete #3 mcx(0, 2, 3, 4, 1) | FAIL | fixer_gave_up |  |
| claude | cmul7 | flip #0 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #0 cx(2, 1) by cx(1, 2) |
| claude | cmul7 | flip #6 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #5 cx(2, 1) by cx(1, 2) |
| claude | cmul7 | flip #7 cx(0, 2) -> cx(2, 0) | PASS | PASS | replace gate #7 cx(2, 0) by cx(0, 2) |
| claude | qpe_t | delete #0 x(3,) | FAIL | fixer_gave_up |  |
| claude | qpe_t | delete #1 h(0,) | PASS | PASS | delete gate #12 h(2,) |
| claude | qpe_t | delete #2 h(1,) | PASS | PASS | delete gate #10 h(1,) |
| claude | qpe_t | negate #4 cp(0.7854)(0, 3) | PASS | PASS | negate the angle of gate #4 cp |
| claude | qpe_t | negate #5 cp(1.5708)(1, 3) | PASS | PASS | negate the angle of gate #5 cp |
| claude | qpe_t | negate #9 cp(-1.5708)(0, 1) | PASS | PASS | negate the angle of gate #5 cp |
| claude | qpe_t | pi written as 3.14 in all 6 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| claude | qpe_t | #4 cp(0.7854) -> crz (same angle)(0, 3) | PASS | PASS | gate #4: crz -> cp |
| claude | qpe_t | #5 cp(1.5708) -> crz (same angle)(1, 3) | PASS | PASS | gate #5: crz -> cp |
| claude | qpe_t | #6 cp(3.1416) -> crz (same angle)(2, 3) | PASS | PASS | gate #6: crz -> cp |
| claude | c3x_linear | delete #0 h(3,) | PASS | PASS | insert h(3) before gate #0 |
| claude | c3x_linear | delete #1 p(0,) | PASS | PASS | insert p(pi/8)(0) before gate #0 |
| claude | c3x_linear | delete #2 p(1,) | PASS | PASS | insert p(pi/8)(1) before gate #0 |
| claude | c3x_linear | negate #1 p(0.3927)(0,) | PASS | PASS | replace gate #0 p(-pi/8)(0) by p(pi/8)(0) |
| claude | c3x_linear | negate #2 p(0.3927)(1,) | PASS | PASS | replace gate #1 p(-pi/8)(1) by p(pi/8)(1) |
| claude | c3x_linear | negate #3 p(0.3927)(2,) | PASS | PASS | replace gate #4 p(-pi/8)(2) by p(pi/8)(2) |
| claude | c3x_linear | pi written as 3.14 in all 15 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| claude | c3x_linear | flip #5 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #2 cx(1, 0) by cx(0, 1) |
| claude | c3x_linear | flip #7 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #5 cx(2, 1) by cx(1, 2) |
| claude | c3x_linear | flip #9 cx(2, 3) -> cx(3, 2) | PASS | PASS | replace gate #10 cx(3, 2) by cx(2, 3) |
| claude | reverse6_nn | delete #1 cx(1, 0) | PASS | PASS | insert swap(0, 1) before gate #0 |
| claude | reverse6_nn | delete #2 cx(0, 1) | PASS | PASS | insert cx(1, 0) before gate #0 |
| claude | reverse6_nn | delete #3 cx(2, 3) | PASS | PASS | insert cx(2, 3) before gate #0 |
| claude | reverse6_nn | flip #0 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(1, 0) by cx(0, 1) |
| claude | reverse6_nn | flip #2 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(0, 1) by swap(0, 1) |
| claude | reverse6_nn | flip #3 cx(2, 3) -> cx(3, 2) | PASS | PASS | replace gate #3 cx(3, 2) by cx(2, 3) |
| claude | bv22 | delete #0 h(0,) | PASS | PASS | delete gate #0 h(0,) |
| claude | bv22 | delete #1 h(1,) | FAIL | fixer_gave_up |  |
| claude | bv22 | delete #2 h(2,) | FAIL | fixer_gave_up |  |
| claude | bv22 | flip #7 cx(1, 5) -> cx(5, 1) | PASS | PASS | flip gate #9 cx(5, 1) -> cx(1, 5) |
| claude | bv22 | flip #8 cx(2, 5) -> cx(5, 2) | PASS | PASS | flip gate #11 cx(5, 2) -> cx(2, 5) |
| claude | bv22 | flip #9 cx(4, 5) -> cx(5, 4) | PASS | PASS | flip gate #13 cx(5, 4) -> cx(4, 5) |
| claude | add3 | delete #0 cx(2, 5) | PASS | PASS | insert cx(2, 5) before gate #0 |
| claude | add3 | delete #1 ccx(1, 4, 5) | FAIL | fixer_gave_up |  |
| claude | add3 | delete #2 mcx(0, 3, 1, 5) | FAIL | fixer_gave_up |  |
| claude | add3 | flip #0 cx(2, 5) -> cx(5, 2) | PASS | PASS | replace gate #0 cx(5, 2) by cx(2, 5) |
| claude | add3 | flip #4 cx(1, 4) -> cx(4, 1) | PASS | PASS | replace gate #4 cx(4, 1) by cx(1, 4) |
| claude | add3 | flip #6 cx(0, 3) -> cx(3, 0) | PASS | PASS | replace gate #6 cx(3, 0) by cx(0, 3) |
| gemini | maj5 | delete #0 mcx(0, 1, 2, 5) | FAIL | fixer_gave_up |  |
| gemini | maj5 | delete #1 mcx(0, 1, 3, 5) | FAIL | fixer_gave_up |  |
| gemini | maj5 | delete #2 mcx(0, 1, 4, 5) | FAIL | fixer_gave_up |  |
| gemini | cmul7 | delete #0 cswap(4, 0, 1) | FAIL | fixer_gave_up |  |
| gemini | cmul7 | delete #1 cswap(4, 1, 2) | FAIL | fixer_gave_up |  |
| gemini | cmul7 | delete #2 cswap(4, 2, 3) | FAIL | fixer_gave_up |  |
| gemini | cmul7 | flip #3 cx(4, 0) -> cx(0, 4) | PASS | PASS | replace gate #3 cx(0, 4) by cx(4, 0) |
| gemini | cmul7 | flip #4 cx(4, 1) -> cx(1, 4) | PASS | PASS | replace gate #4 cx(1, 4) by cx(4, 1) |
| gemini | cmul7 | flip #5 cx(4, 2) -> cx(2, 4) | PASS | PASS | replace gate #7 cx(2, 4) by cx(4, 2) |
| gemini | qpe_t | delete #0 x(3,) | FAIL | fixer_gave_up |  |
| gemini | qpe_t | delete #1 h(0,) | PASS | PASS | delete gate #12 h(2,) |
| gemini | qpe_t | delete #2 h(1,) | PASS | PASS | delete gate #10 h(1,) |
| gemini | qpe_t | negate #4 cp(0.7854)(0, 3) | PASS | PASS | negate the angle of gate #4 cp |
| gemini | qpe_t | negate #5 cp(1.5708)(1, 3) | PASS | PASS | negate the angle of gate #5 cp |
| gemini | qpe_t | negate #9 cp(-1.5708)(0, 1) | PASS | PASS | negate the angle of gate #5 cp |
| gemini | qpe_t | pi written as 3.14 in all 6 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| gemini | qpe_t | #4 cp(0.7854) -> crz (same angle)(0, 3) | PASS | PASS | gate #4: crz -> cp |
| gemini | qpe_t | #5 cp(1.5708) -> crz (same angle)(1, 3) | PASS | PASS | gate #5: crz -> cp |
| gemini | qpe_t | #6 cp(3.1416) -> crz (same angle)(2, 3) | PASS | PASS | gate #6: crz -> cp |
| gemini | c3x_linear | delete #15 cx(0, 1) | PASS | PASS | delete gate #4 cx(0, 1) |
| gemini | c3x_linear | delete #24 cx(1, 2) | PASS | PASS | delete gate #30 cx(1, 2) |
| gemini | c3x_linear | delete #25 cx(0, 1) | PASS | PASS | delete gate #29 cx(0, 1) |
| gemini | c3x_linear | negate #1 rz(0.3927)(0,) | PASS | PASS | replace gate #0 rz(-pi/8)(0) by p(pi/8)(0) |
| gemini | c3x_linear | negate #2 rz(0.3927)(1,) | PASS | PASS | replace gate #1 rz(-pi/8)(1) by p(pi/8)(1) |
| gemini | c3x_linear | negate #4 rz(-0.3927)(1,) | PASS | PASS | replace gate #3 rz(pi/8)(1) by p(-pi/8)(1) |
| gemini | c3x_linear | pi written as 3.14 in all 15 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| gemini | c3x_linear | flip #8 cx(1, 0) -> cx(0, 1) | PASS | PASS | replace gate #4 cx(0, 1) by cx(1, 0) |
| gemini | c3x_linear | flip #10 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #9 cx(2, 1) by cx(1, 2) |
| gemini | c3x_linear | flip #20 cx(1, 0) -> cx(0, 1) | PASS | PASS | replace gate #18 cx(0, 1) by swap(0, 1) |
| gemini | reverse6_nn | delete #0 cx(0, 1) | PASS | PASS | insert cx(0, 1) before gate #0 |
| gemini | reverse6_nn | delete #1 cx(1, 0) | PASS | PASS | insert swap(0, 1) before gate #0 |
| gemini | reverse6_nn | delete #2 cx(0, 1) | PASS | PASS | insert cx(1, 0) before gate #0 |
| gemini | reverse6_nn | flip #0 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(1, 0) by cx(0, 1) |
| gemini | reverse6_nn | flip #1 cx(1, 0) -> cx(0, 1) | PASS | PASS | replace gate #0 cx(0, 1) by swap(0, 1) |
| gemini | reverse6_nn | flip #2 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(0, 1) by swap(0, 1) |
| gemini | bv22 | delete #0 x(5,) | FAIL | fixer_gave_up |  |
| gemini | bv22 | delete #1 h(5,) | FAIL | fixer_gave_up |  |
| gemini | bv22 | delete #2 h(0,) | PASS | PASS | delete gate #0 h(0,) |
| gemini | bv22 | flip #7 cx(1, 5) -> cx(5, 1) | PASS | PASS | flip gate #9 cx(5, 1) -> cx(1, 5) |
| gemini | bv22 | flip #8 cx(2, 5) -> cx(5, 2) | PASS | PASS | flip gate #11 cx(5, 2) -> cx(2, 5) |
| gemini | bv22 | flip #9 cx(4, 5) -> cx(5, 4) | PASS | PASS | flip gate #13 cx(5, 4) -> cx(4, 5) |
| gemini | add3 | delete #0 cx(2, 5) | PASS | PASS | insert cx(2, 5) before gate #0 |
| gemini | add3 | delete #1 ccx(1, 4, 5) | FAIL | fixer_gave_up |  |
| gemini | add3 | delete #2 mcx(1, 0, 3, 5) | FAIL | fixer_gave_up |  |
| gemini | add3 | flip #0 cx(2, 5) -> cx(5, 2) | PASS | PASS | replace gate #0 cx(5, 2) by cx(2, 5) |
| gemini | add3 | flip #4 cx(1, 4) -> cx(4, 1) | PASS | PASS | replace gate #4 cx(4, 1) by cx(1, 4) |
| gemini | add3 | flip #6 cx(0, 3) -> cx(3, 0) | PASS | PASS | replace gate #6 cx(3, 0) by cx(0, 3) |
| perplexity | maj5 | delete #0 mcx(0, 1, 2, 5) | FAIL | fixer_gave_up |  |
| perplexity | maj5 | delete #1 mcx(0, 1, 3, 5) | FAIL | fixer_gave_up |  |
| perplexity | maj5 | delete #2 mcx(0, 1, 4, 5) | FAIL | fixer_gave_up |  |
| perplexity | cmul7 | delete #2 mcx(4, 0, 2, 3, 1) | FAIL | fixer_gave_up |  |
| perplexity | cmul7 | delete #4 x(2,) | PASS | PASS | delete gate #6 x(2) |
| perplexity | cmul7 | delete #5 x(3,) | PASS | PASS | delete gate #4 x(3) |
| perplexity | qpe_t | delete #0 x(3,) | FAIL | fixer_gave_up |  |
| perplexity | qpe_t | delete #1 h(0,) | PASS | PASS | delete gate #14 h(2,) |
| perplexity | qpe_t | delete #2 h(1,) | PASS | PASS | delete gate #12 h(1,) |
| perplexity | qpe_t | negate #4 cp(0.7854)(0, 3) | PASS | PASS | negate the angle of gate #4 cp |
| perplexity | qpe_t | negate #5 cp(1.5708)(1, 3) | PASS | PASS | negate the angle of gate #5 cp |
| perplexity | qpe_t | negate #11 cp(-1.5708)(0, 1) | PASS | PASS | negate the angle of gate #5 cp |
| perplexity | qpe_t | pi written as 3.14 in all 6 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| perplexity | qpe_t | flip #7 cx(0, 2) -> cx(2, 0) | PASS | PASS | flip gate #7 cx(2, 0) -> cx(0, 2) |
| perplexity | qpe_t | flip #8 cx(2, 0) -> cx(0, 2) | PASS | PASS | flip gate #8 cx(0, 2) -> cx(2, 0) |
| perplexity | qpe_t | flip #9 cx(0, 2) -> cx(2, 0) | PASS | PASS | flip gate #9 cx(2, 0) -> cx(0, 2) |
| perplexity | qpe_t | #4 cp(0.7854) -> crz (same angle)(0, 3) | PASS | PASS | gate #4: crz -> cp |
| perplexity | qpe_t | #5 cp(1.5708) -> crz (same angle)(1, 3) | PASS | PASS | gate #5: crz -> cp |
| perplexity | qpe_t | #6 cp(3.1416) -> crz (same angle)(2, 3) | PASS | PASS | gate #6: crz -> cp |
| perplexity | c3x_linear | delete #0 h(3,) | PASS | PASS | insert h(3) before gate #0 |
| perplexity | c3x_linear | delete #14 cx(1, 2) | PASS | PASS | delete gate #15 cx(1, 2) |
| perplexity | c3x_linear | delete #19 cx(2, 3) | PASS | PASS | insert cx(2, 3) before gate #26 |
| perplexity | c3x_linear | negate #1 p(0.3927)(0,) | PASS | PASS | replace gate #0 p(-pi/8)(0) by p(pi/8)(0) |
| perplexity | c3x_linear | negate #2 p(0.3927)(1,) | PASS | PASS | replace gate #1 p(-pi/8)(1) by p(pi/8)(1) |
| perplexity | c3x_linear | negate #3 p(0.3927)(2,) | PASS | PASS | replace gate #6 p(-pi/8)(2) by p(pi/8)(2) |
| perplexity | c3x_linear | pi written as 3.14 in all 15 angles | PASS | PASS | rescale every angle by pi/3.14 (pi written as 3.14) |
| perplexity | c3x_linear | flip #8 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #4 cx(0, 1) by cx(1, 0) |
| perplexity | c3x_linear | flip #10 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #8 cx(1, 0) by cx(0, 1) |
| perplexity | c3x_linear | flip #11 cx(1, 2) -> cx(2, 1) | PASS | PASS | replace gate #9 cx(2, 1) by cx(1, 2) |
| perplexity | reverse6_nn | delete #0 cx(0, 1) | PASS | PASS | insert cx(0, 1) before gate #0 |
| perplexity | reverse6_nn | delete #2 cx(0, 1) | PASS | PASS | insert cx(1, 0) before gate #0 |
| perplexity | reverse6_nn | delete #4 cx(2, 1) | PASS | PASS | insert swap(0, 2) before gate #0 |
| perplexity | reverse6_nn | flip #0 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(1, 0) by cx(0, 1) |
| perplexity | reverse6_nn | flip #1 cx(1, 0) -> cx(0, 1) | PASS | PASS | replace gate #0 cx(0, 1) by swap(0, 1) |
| perplexity | reverse6_nn | flip #2 cx(0, 1) -> cx(1, 0) | PASS | PASS | replace gate #0 cx(0, 1) by swap(0, 1) |
| perplexity | bv22 | delete #0 x(5,) | FAIL | fixer_gave_up |  |
| perplexity | bv22 | delete #1 h(5,) | FAIL | fixer_gave_up |  |
| perplexity | bv22 | delete #2 h(0,) | PASS | PASS | delete gate #0 h(0,) |
| perplexity | bv22 | flip #7 cx(1, 5) -> cx(5, 1) | PASS | PASS | flip gate #9 cx(5, 1) -> cx(1, 5) |
| perplexity | bv22 | flip #8 cx(2, 5) -> cx(5, 2) | PASS | PASS | flip gate #11 cx(5, 2) -> cx(2, 5) |
| perplexity | bv22 | flip #9 cx(4, 5) -> cx(5, 4) | PASS | PASS | flip gate #13 cx(5, 4) -> cx(4, 5) |
| perplexity | add3 | delete #0 mcx(0, 3, 4, 5) | FAIL | fixer_gave_up |  |
| perplexity | add3 | delete #1 ccx(0, 3, 4) | FAIL | fixer_gave_up |  |
| perplexity | add3 | delete #2 cx(0, 3) | PASS | PASS | insert cx(0, 3) before gate #2 |
| perplexity | add3 | flip #2 cx(0, 3) -> cx(3, 0) | PASS | PASS | replace gate #5 cx(3, 0) by cx(0, 3) |
| perplexity | add3 | flip #4 cx(1, 4) -> cx(4, 1) | PASS | PASS | replace gate #5 cx(4, 1) by cx(1, 4) |
| perplexity | add3 | flip #5 cx(2, 5) -> cx(5, 2) | PASS | PASS | replace gate #5 cx(5, 2) by cx(2, 5) |
