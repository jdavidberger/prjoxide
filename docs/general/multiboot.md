# Dynamic Multiboot and Configuration Access

The Nexus devices support multibooting from an arbitrary SPI address, similar to the iCE40 WARMBOOT functionality, although this isn't well documented by Lattice.

You will need three primitives for this: `MULTIBOOT`, `CONFIG_LMMI` and `CONFIG_CLKRST_CORE`

The `MULTIBOOT` primitive is used to set the new boot address. It should be instantiated thus:

```verilog
MULTIBOOT #(
	.SOURCESEL("EN")
) mb_i (
	.AUTOREBOOT(1'b0),
	.MSPIMADDR(next_addr)
);
```

Setting `SOURCESEL` to `"EN"` enables setting the next address dynamically from the `MSPIMADDR` input, rather than the `MSPIADDR` config parameter. `AUTOREBOOT` cannot (at least on ES devices) actually trigger a reboot - tie it to zero and use `CONFIG_LMMI` for this...

Wen generating the bitstream pass the `-multiboot` flag to `prjoxide pack`. This will set the necessary bit in CR0 to enable picking up the next address from fabric.

`CONFIG_LMMI` should be instantiated as follows, to get arbitrary access to the configuration logic from fabric. It could also be used for things like partial reconfiguration or reading the device unique ID, but to trigger a reboot, all you need to send is an `REFRESH` command.

```verilog
CONFIG_CLKRST_CORE clkrst_i (
	.LMMI_CLK(clk),
	.LMMI_LRST_N(1'b1),
	.LMMI_CLK_O(lmmi_clk),
	.LMMI_RST(lmmi_rstn)
);
CONFIG_LMMI #(
	.LMMI_EN("EN")
) lmmi_i (
	.LMMICLK(lmmi_clk),
	.LMMIRESETN(lmmi_rstn),
	.LMMIREQUEST(lmmi_req),
	.LMMIWRRD_N(1'b1),
	.LMMIOFFSET(8'h01),
	.LMMIWDATA(lmmi_wdata),
	.LMMIRDATA(),
	.LMMIRDATAVALID(),
);
```

You can't connect to the `LMMICLK` or `LMMIRESETN` pins of `CONFIG_LMMI` directly - they are only routeable through the `CONFIG_CLKRST_CORE`.

To restart the FPGA, i.e. at the new address specified by `MULTIBOOT`, assert `lmmi_req` for 4 cycles and send `0x79 0x00 0x00 0x00` on `LMMIWDATA` during those 4 cycles.
