OPENQASM 3.0;
include "stdgates.inc";
gate qft_dg _gate_q_0, _gate_q_1, _gate_q_2 {
  swap _gate_q_0, _gate_q_2;
  h _gate_q_0;
  cp(-pi/2) _gate_q_1, _gate_q_0;
  h _gate_q_1;
  cp(-pi/4) _gate_q_2, _gate_q_0;
  cp(-pi/2) _gate_q_2, _gate_q_1;
  h _gate_q_2;
}
qubit[4] q;
x q[0];
h q[3];
h q[2];
h q[1];
cp(pi/4) q[3], q[0];
cp(pi/2) q[2], q[0];
cp(pi) q[1], q[0];
qft_dg q[3], q[2], q[1];
