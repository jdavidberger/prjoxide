import asyncio
import logging

from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect
import re
import tiles
import fuzzloops
import database
import lapie

configs = [
    ([(11, 7), (11, 19)], [], FuzzConfig(job="TAPROUTE", device="LIFCL-40", sv="../shared/route_40.v", tiles=["TAP_PLC_R11C14:TAP_PLC"])),
    ([(10, 7), (10, 19)], [], FuzzConfig(job="TAPROUTECIB", device="LIFCL-40", sv="../shared/route_40.v", tiles=["TAP_CIB_R10C14:TAP_CIB"])),
    ([(1, 7), (1, 19)], [], FuzzConfig(job="TAPROUTECIBT", device="LIFCL-40", sv="../shared/route_40.v", tiles=["TAP_CIBT_R1C14:TAP_CIBT"])),

    ([(11, 80)], [], FuzzConfig(job="TAPROUTE_1S", device="LIFCL-40", sv="../shared/route_40.v", tiles=["TAP_PLC_1S_R11C74:TAP_PLC_1S"])),
    ([(10, 80)], [], FuzzConfig(job="TAPROUTECIB_1S", device="LIFCL-40", sv="../shared/route_40.v", tiles=["TAP_CIB_1S_R10C74:TAP_CIB_1S"])),
    ([(1, 80)], [], FuzzConfig(job="TAPROUTECIBT_1S", device="LIFCL-40", sv="../shared/route_40.v", tiles=["TAP_CIBT_1S_R1C74:TAP_CIBT_1S"])),

    ([(11, 7), ], [(11, 13), ], FuzzConfig(job="TAPROUTE_1SL", device="LIFCL-17", sv="../shared/route_17.v", tiles=["TAP_PLC_1S_L_R11C14:TAP_PLC_1S_L"])),
    ([(10, 7), ], [(10, 13), ], FuzzConfig(job="TAPROUTECIB_1SL", device="LIFCL-17", sv="../shared/route_17.v", tiles=["TAP_CIB_1S_L_R10C14:TAP_CIB_1S_L"])),
    ([(1, 7), ], [(1, 13), ], FuzzConfig(job="TAPROUTECIBT_1SL", device="LIFCL-17", sv="../shared/route_17.v", tiles=["TAP_CIBT_1S_L_R1C14:TAP_CIBT_1S_L"])),
]

async def resolve_all_tiles_for_device(device,executor):
    tg = database.get_tilegrid(device)["tiles"]

    tap_tiletypes = {i["tiletype"] for k,i in tg.items() if i['tiletype'].startswith("TAP_")}

    for tiletype in tap_tiletypes:
        ts = {k for k,i in tg.items() if tiletype == i['tiletype']}

        sorted_tiles = sorted(ts, key=lambda t: tuple(reversed(tiles.get_rc_from_name(device, t))))
        tile = sorted_tiles[0]

        r = tiles.get_rc_from_name(device, tile)[0]

        tile_columns = sorted({tiles.get_rc_from_name(device, n)[1] for n in ts})

        nodenames = [f"R{r}C..?_R?HPBX..00"]
        nodes = lapie.get_node_data(device, nodenames, True)

        node_columns = sorted({tiles.get_rc_from_name(device, n.name)[1] for n in nodes})
        nodes_per_tile = len(node_columns) // len(tile_columns)
        relevant_nodes = [n.name for n in nodes if tiles.get_rc_from_name(device, n.name)[1] in node_columns[:nodes_per_tile]]

        print(relevant_nodes, tile)
        cfg = FuzzConfig(job=f"TAPROUTE-{tile}", device=device, sv="../shared/route.v", tiles=[tile])
        for f in fuzz_interconnect(config=cfg, nodenames=relevant_nodes, regex=False, bidir=False, full_mux_style=True,
                                   executor=executor):
            yield f

async def main(executor):
    for locs, rlocs, cfg in configs:
        cfg.setup()
        nodes = []
        for r, c in locs:
            nodes += ["R{}C{}_HPBX{:02}00".format(r, c, i) for i in range(8)]
        for r, c in rlocs:
            nodes += ["R{}C{}_RHPBX{:02}00".format(r, c, i) for i in range(8)]

        for f in fuzz_interconnect(config=cfg, nodenames=nodes, regex=False, bidir=False, full_mux_style=True, executor=executor):
            yield f

    for device in ["LIFCL-33", "LIFCL-33U"]:
        async for f in resolve_all_tiles_for_device(device, executor=executor):
            yield f

if __name__ == "__main__":
    async def async_main(executor):
        await asyncio.gather(*[asyncio.wrap_future(f) async for f in main(executor)])

    fuzzloops.FuzzerAsyncMain(async_main)


