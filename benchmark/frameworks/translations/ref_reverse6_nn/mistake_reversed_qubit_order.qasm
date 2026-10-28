OPENQASM 3.0;
include "stdgates.inc";
qubit[6] q;
swap q[5], q[0];
swap q[4], q[1];
swap q[3], q[2];
