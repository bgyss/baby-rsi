// Fixed, read-only design with redundant logic. A good synthesis recipe
// (e.g. opt -full; abc) collapses the duplicated/subsumed terms to far fewer cells;
// a weak recipe leaves them in place. The function is y = a & (b | c | d).
module top(input a, input b, input c, input d, output y);
  wire t1, t2, t3, t4, t5;
  assign t1 = a & b;
  assign t2 = a & b;          // redundant duplicate of t1
  assign t3 = a & c;
  assign t4 = a & d;
  assign t5 = (t1 | t2) | t3; // (a&b) | (a&c)
  assign y  = (t5 | t4) | (a & b & c); // last term is subsumed by t5
endmodule
