import asyncio
import logging

from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect, fuzz_interconnect_sinks_across_span
import re
import tiles
import database
import fuzzconfig
import fuzzloops

async def run_cfg(executor, device):
    all_of_type = list(tiles.get_tiles_by_tiletype(device, "PLC").keys())
    def not_on_edge(rc):
        return rc[0] > 5 and rc[1] > 5
    sorted_tiles = [tile for tile in sorted(all_of_type, key=lambda t: tiles.get_rc_from_name(device, t)) if not_on_edge(tiles.get_rc_from_name(device, tile))]
    tile = sorted_tiles[len(sorted_tiles)//2]

    logging.info(f"Total PLC count {len(all_of_type)}")
    (r, c) = tiles.get_rc_from_name(device, tile)

    tap_plcs = list(tiles.get_tiles_by_tiletype(device, "TAP_PLC"))

    cfg = FuzzConfig(job=f"PLCROUTE-{device}-{tile}", device=device, sv=f"../shared/route.v", tiles=[tile])

    nodes = [f"R{r}C{c}_J.*", f"R{r}C{c}_H00.0.00", f"R{r}C{c}_HFIE0000"] + \
            [f"R{r}C{c}_{o}01{d}{i:02}00" for i in range(4) for o in "HV" for d in "SW"] + \
            [f"R{r}C{c}_V00{s}{i:02}00" for i in range(4) for s in "TB"]

    extra_sources = []
    extra_sources += ["R{}C{}_H02E{:02}01".format(r, c+1, i) for i in range(8)]
    extra_sources += ["R{}C{}_H06E{:02}03".format(r, c+3, i) for i in range(4)]
    extra_sources += ["R{}C{}_V02N{:02}01".format(r-1, c, i) for i in range(8)]	
    extra_sources += ["R{}C{}_V06N{:02}03".format(r-3, c, i) for i in range(4)]	
    extra_sources += ["R{}C{}_V02S{:02}01".format(r+1, c, i) for i in range(8)]	
    extra_sources += ["R{}C{}_V06S{:02}03".format(r+3, c, i) for i in range(4)]	
    extra_sources += ["R{}C{}_H02W{:02}01".format(r, c-1, i) for i in range(8)]
    extra_sources += ["R{}C{}_H06W{:02}03".format(r, c - 3, i) for i in range(4)]


    extra_cfg = FuzzConfig(job=f"PLCROUTE-{device}-{tile}-extra", device=device, sv=f"../shared/route.v", tiles=[tile])
    await asyncio.gather(
        fuzz_interconnect_sinks_across_span(config=cfg, tile_span = all_of_type, nodenames=nodes, regex=True, bidir=True, ignore_tiles=tap_plcs, executor=executor, max_per_design=len(all_of_type) / 2),
        fuzz_interconnect_sinks_across_span(config=extra_cfg, tile_span = all_of_type, nodenames=extra_sources, regex=False, bidir=False, ignore_tiles=tap_plcs, executor=executor, max_per_design=len(all_of_type) / 2),
    )

async def FuzzAsync(executor):
    await run_cfg(executor, fuzzconfig.devices_to_fuzz()[0])

if __name__ == "__main__":
    fuzzloops.FuzzerAsyncMain(FuzzAsync)
