module top(
	 input clk, a,
 	output q0);
	
	wire a_buf, a_del;
	IDDRX1 oddr_i (.SCLK(clk), .Q0(q0), .Q1(), .D(a_del));

	DELAYB #(.DEL_MODE("USER_DEFINED"), .DEL_VALUE(63)) simple_delay(.A(a_buf), .Z(a_del));



	(* LOC="P10", IO_TYPE="LVCMOS18H" *)
	IB ob_y(.I(a), .O(a_buf));
endmodule
