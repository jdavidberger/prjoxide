from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect
import re
import tiles

tiles_33 = [
    [(0, 30)],# "B0"),
    [(0,  2)],# "B5"),
    [(0, 38)],# "B1_DED"),
    [(0, 40)],# "B1"),
    [(83, 12), (83, 11)],# B3_0, B3_1
    [(83, 14), (83, 15)],# B3_0_ECLK_L, B3_1
    [(83, 18), (83, 19)], # B3_0, B3_1_V18_32
    [(83, 32), (83, 33)], # B2_0, B2_1_V18_21
    [(83, 34), (83, 35)], # B2_0, B2_1
    [(83, 46), (83, 47)], # B2_0, B2_1_1_V18_22
    [(83, 4), (83, 5)],# B4_0 B4_1_V18_41
    [(83, 6), (83, 7)],# B4_0 B4_1_V18_42
    [(83, 8), (83, 9)],# B3_0, B3_1_V18_31
    [(0, 10)], # SYSIO_b5
    ]

def create_io_config(device, rcs):
    ts = [ tile for rc in rcs for tile in tiles.get_tiles_by_rc(device, rc) ]
    job_name = "IOROUTE_" + "_".join([f"R{rc[0]}C{rc[1]}" for rc in rcs])
    return {
        "cfg": FuzzConfig(job=job_name, device="LIFCL-33", sv="../shared/route_33.v",
                          tiles=ts),
        "rcs": rcs
    }

configs_33 = [create_io_config("LIFCL-33", x) for x in tiles_33]

configs = configs_33 + [
    {
        "cfg": FuzzConfig(job="IOROUTE0_17K", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R0C59:SYSIO_B0_0_15K"]),
        "rc": (0, 59),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE1_17K", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R5C75:SYSIO_B1_0_15K"]),
        "rc": (5, 75),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE1D_17K", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R3C75:SYSIO_B1_DED_15K"]),
        "rc": (3, 75),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE5", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R56C8:SYSIO_B5_0", "CIB_R56C9:SYSIO_B5_1"]),
        "rc": (56, 8),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE4", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R56C16:SYSIO_B4_0", "CIB_R56C17:SYSIO_B4_1"]),
        "rc": (56, 16),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE3", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R56C56:SYSIO_B3_0", "CIB_R56C57:SYSIO_B3_1"]),
        "rc": (56, 56),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE2E", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R44C87:SYSIO_B2_0_EVEN"]),
        "rc": (44, 87),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE2O", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R42C87:SYSIO_B2_0_ODD"]),
        "rc": (42, 87),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE1O", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R8C87:SYSIO_B1_0_ODD"]),
        "rc": (8, 87),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE1E", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R6C87:SYSIO_B1_0_EVEN"]),
        "rc": (6, 87),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE0O", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R0C84:SYSIO_B0_0_ODD"]),
        "rc": (0, 84),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE0E", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R0C78:SYSIO_B0_0_EVEN"]),
        "rc": (0, 78),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE7E", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R3C0:SYSIO_B7_0_EVEN"]),
        "rc": (3, 0),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE7O", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R4C0:SYSIO_B7_0_ODD"]),
        "rc": (4, 0),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE6O", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R49C0:SYSIO_B6_0_ODD"]),
        "rc": (49, 0),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE6E", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R44C0:SYSIO_B6_0_EVEN"]),
        "rc": (44, 0),
    },
    {
        "cfg": FuzzConfig(job="IOROUTE1D", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R3C87:SYSIO_B1_DED"]),
        "rc": (3, 87),
    },
]

ignore_tiles_40k = set([
    "CIB_R55C8:CIB",
    "CIB_R55C9:CIB",
    "CIB_R55C16:CIB",
    "CIB_R55C17:CIB",
    "CIB_R55C56:CIB",
    "CIB_R55C57:CIB",
    "CIB_R42C86:CIB_LR",
    "CIB_R43C86:CIB_LR",
    "CIB_R44C86:CIB_LR",
    "CIB_R45C86:CIB_LR",
    "CIB_R3C86:CIB_LR",
    "CIB_R6C86:CIB_LR",
    "CIB_R7C86:CIB_LR",
    "CIB_R8C86:CIB_LR",
    "CIB_R9C86:CIB_LR",
    "CIB_R1C84:CIB_T",
    "CIB_R1C85:CIB_T",
    "CIB_R1C78:CIB_T",
    "CIB_R1C79:CIB_T",
    "CIB_R3C1:CIB_LR",
    "CIB_R4C1:CIB_LR",
    "CIB_R5C1:CIB_LR",
    "CIB_R43C1:CIB_LR",
    "CIB_R44C1:CIB_LR",
    "CIB_R45C1:CIB_LR",
    "CIB_R49C1:CIB_LR",
    "CIB_R50C1:CIB_LR",
])

ignore_tiles_17k = set([
    "CIB_R1C74:CIB_LR",
    "CIB_R2C74:CIB_LR",
    "CIB_R3C74:CIB_LR",
    "CIB_R4C74:CIB_LR",
    "CIB_R5C74:CIB_LR",
    "CIB_R6C74:CIB_LR",
    "CIB_R7C74:CIB_LR",
    "CIB_R8C74:CIB_LR",
    "CIB_R9C74:CIB_LR",
    "CIB_R10C74:CIB_LR_A",
    "CIB_R11C74:CIB_LR",
    "CIB_R11C74:CIB_LR_B",
    "CIB_R12C74:CIB_LR",
    "CIB_R1C58:CIB_T",
    "CIB_R1C59:CIB_T",
    "CIB_R1C60:CIB_T",
    "CIB_R1C61:CIB_T",
])

def main():
    for config in configs:
        cfg = config["cfg"]
        cfg.setup()

        rcs = set([])
        if "rc" in config:
            rcs = set([ config["rc"] ])
        else:
            rcs = set(config["rcs"])
            
        nodes = [f"R{r}C{c}_.*" for (r,c) in rcs]
        def nodename_filter(x, nodes):
            node_in_tiles = tiles.get_rc_from_name(cfg.device, x) in rcs
            return ("_GEARING_PIC_TOP_" in x or "SEIO18_CORE" in x or "DIFFIO18_CORE" in x or "I217" in x or "I218" in x or "SEIO33_CORE" in x or "SIOLOGIC_CORE" in x)
        def pip_filter(pip, nodes):
            from_wire, to_wire = pip
            return not ("ADC_CORE" in to_wire or "ECLKBANK_CORE" in to_wire or "MID_CORE" in to_wire
                or "REFMUX_CORE" in to_wire or "CONFIG_JTAG_CORE" in to_wire or "CONFIG_JTAG_CORE" in from_wire
                or "REFCLOCK_MUX_CORE" in to_wire)

        ignore_tiles = [tile
                        for (r,c) in rcs
                        for ro in [r+1,r-1,r]
                        for co in [c+1,c-1,c]
                        for tile in tiles.get_tiles_by_rc(cfg.device, (ro,co))
                        ]
        if cfg.device == "LIFCL-17":
            ignore_tiles = ignore_tiles_17k
        elif cfg.device == "LIFCL-40":
            ignore_tiles = ignore_tiles_40k

        print("Ignore tiles: ", ignore_tiles)
        fuzz_interconnect(config=cfg, nodenames=nodes, nodename_predicate=nodename_filter, pip_predicate=pip_filter, regex=True, bidir=True,
            ignore_tiles=ignore_tiles)

if __name__ == "__main__":
    main()
