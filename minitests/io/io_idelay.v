module top(
	 input a,
 	output y);

	wire a_buf, a_del;
	(* LOC="P11", IO_TYPE="LVCMOS18H" *)
	IB ib_a(.I(a), .O(a_buf));

	DELAYB #(.DEL_MODE("USER_DEFINED"), .DEL_VALUE(63)) simple_delay(.A(a_buf), .Z(a_del));

	(* LOC="P10", IO_TYPE="LVCMOS18H" *)
	OB ob_y(.I(~a_del), .O(y));
endmodule
