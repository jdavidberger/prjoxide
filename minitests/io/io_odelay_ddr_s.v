module top(
	 input clk,
 	output y);
	
	wire a_buf, a_del;
	ODDRX1 oddr_i (.SCLK(clk), .D0(1'b0), .D1(1'b1), .Q(a_buf));

	DELAYB #(.DEL_MODE("USER_DEFINED"), .DEL_VALUE(63)) simple_delay(.A(a_buf), .Z(a_del));



	(* LOC="D10", IO_TYPE="LVCMOS33" *)
	OB ob_y(.I(a_del), .O(y));
endmodule
