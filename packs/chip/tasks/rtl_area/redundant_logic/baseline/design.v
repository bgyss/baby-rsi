// Redundant combinational implementation of y = a & (b | c).
// Written as (a & b) | (a & c): duplicates the AND with `a`, so it synthesizes to
// more generic cells than the factored form.
module top(input a, input b, input c, output y);
  wire t1, t2;
  assign t1 = a & b;
  assign t2 = a & c;
  assign y = t1 | t2;
endmodule
