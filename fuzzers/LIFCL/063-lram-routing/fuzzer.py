from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect

import database
import re

lifcl33_sites = {
    'R4C50':["CIB_R4C51:LRAM_0_33K", "CIB_R4C1:CIB_LR"],
    'R20C50':["CIB_R20C51:LRAM_1_33K", "CIB_R20C1:CIB_LR"],    
    'R34C50':["CIB_R34C51:LRAM_2_33K", "CIB_R34C1:CIB_LR"] ,
    'R47C50':["CIB_R47C51:LRAM_3_33K", "CIB_R47C1:CIB_LR"],
    'R65C50':["CIB_R65C51:LRAM_4_33K", "CIB_R65C1:CIB_LR"]    
}


def create_config(site, tiles, device):
    lram = tiles[0].split(":")[1].replace("_", "")
    rc = site[1:].split("C")
    return { "cfg": FuzzConfig(job=f"{lram}_{device}", device=f"LIFCL-{device}", sv=f"../shared/route_{device}.v", tiles=tiles), "rc": rc }


configs = [ create_config(site, tiles, "33") for (site, tiles) in lifcl33_sites.items() ] +\
[    
    {
        "cfg": FuzzConfig(job="LRAMROUTE0", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R23C87:LRAM_0"]),
        "rc": (18, 86),
    },
    {
        "cfg": FuzzConfig(job="LRAMROUTE1", device="LIFCL-40", sv="../shared/route_40.v", tiles=["CIB_R41C87:LRAM_1"]),
        "rc": (40, 86),
    },

    {
        "cfg": FuzzConfig(job="LRAMROUTE17_0", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R15C75:LRAM_0_15K"]),
        "rc": (15, 74),
    },
    {
        "cfg": FuzzConfig(job="LRAMROUTE17_1", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R16C75:LRAM_1_15K"]),
        "rc": (16, 74),
    },
    {
        "cfg": FuzzConfig(job="LRAMROUTE17_2", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R3C0:LRAM_2_15K"]),
        "rc": (2, 0),
    },
    {
        "cfg": FuzzConfig(job="LRAMROUTE17_3", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R12C0:LRAM_3_15K"]),
        "rc": (11, 0),
    },
    {
        "cfg": FuzzConfig(job="LRAMROUTE17_4", device="LIFCL-17", sv="../shared/route_17.v", tiles=["CIB_R21C0:LRAM_4_15K"]),
        "rc": (20, 0),
    },
]

ignore_tiles_40 = set([
    "CIB_R{}C86:CIB_LR".format(c) for c in range(2, 55)
] + [
    "CIB_R19C86:CIB_LR_A",
    "CIB_R20C86:CIB_LR_B",
    "CIB_R28C86:CIB_LR_A",
    "CIB_R37C86:CIB_LR_A",
    "CIB_R46C86:CIB_LR_A",
])

ignore_tiles_17 = set([
    "CIB_R{}C74:CIB_LR".format(c) for c in range(2, 29)
] + [
    "CIB_R{}C1:CIB_LR".format(c) for c in range(2, 29)
] + [
    "CIB_R1C1:CIB_T",
    "CIB_R10C1:CIB_LR_A",
    "CIB_R19C1:CIB_LR_A",
    "CIB_R19C74:CIB_LR_A",
    "CIB_R10C74:CIB_LR_A"
])

def main():
    for config in configs:
        cfg = config["cfg"]
        cfg.setup()
        r, c = config["rc"]
        nodes = ["R{}C{}_*".format(r, c)]
        def nodename_filter(x, nodes):
            return ("R{}C{}_".format(r, c) in x) and ("LRAM_CORE" in x)

        tg = database.get_tilegrid(cfg.device)["tiles"]
        ignore_tiles = [tile for tile in tg if "CIB_LR" in tile or "CIB_T" in tile]
        if cfg.device == "LIFCL-17":
            ignore_tiles = ignore_tiles_17
        elif cfg.device == "LIFCL-40":
            ignore_tiles = ignore_tiles_40
            
        fuzz_interconnect(config=cfg, nodenames=nodes, nodename_predicate=nodename_filter, regex=True, bidir=True, ignore_tiles=ignore_tiles)

if __name__ == "__main__":
    main()
