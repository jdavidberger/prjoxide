import asyncio
import logging

from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect, fuzz_interconnect_sinks_across_span
from fuzzloops import FuzzerAsyncMain
import fuzzconfig
import tiles
import re

async def per_config(rc, device, tile, all_of_type, ignore, executor):
    tiletype = all_of_type[0].split(":")[-1]

    r, c = rc
    nodes = ["R{}C{}_J*".format(r, c)]
    extra_sources = []
    extra_sources += ["R{}C{}_H02E{:02}01".format(r, c+1, i) for i in range(8)]
    extra_sources += ["R{}C{}_H06E{:02}03".format(r, c+3, i) for i in range(4)]
    if r != 1:
        extra_sources += ["R{}C{}_V02N{:02}01".format(r-1, c, i) for i in range(8)]
        extra_sources += ["R{}C{}_V06N{:02}03".format(r-3, c, i) for i in range(4)]
    else:
        extra_sources += ["R{}C{}_V02N{:02}00".format(r, c, i) for i in range(8)]
        extra_sources += ["R{}C{}_V06N{:02}00".format(r, c, i) for i in range(4)]
    extra_sources += ["R{}C{}_V02S{:02}01".format(r+1, c, i) for i in range(8)]
    extra_sources += ["R{}C{}_V06S{:02}03".format(r+3, c, i) for i in range(4)]
    if c != 1:
        extra_sources += ["R{}C{}_H02W{:02}01".format(r, c-1, i) for i in range(8)]
        extra_sources += ["R{}C{}_H06W{:02}03".format(r, c-3, i) for i in range(4)]
    else:
        extra_sources += ["R{}C{}_H02W{:02}00".format(r, c, i) for i in range(8)]
        extra_sources += ["R{}C{}_H06W{:02}00".format(r, c, i) for i in range(4)]
    def pip_filter(pip, nodes):
        from_wire, to_wire = pip
        return not ("_CORE" in from_wire or "_CORE" in to_wire or "JCIBMUXOUT" in to_wire)
    def fc_filter(to_wire):
        return "CIBMUX" in to_wire or "CIBTEST" in to_wire or to_wire.startswith("R{}C{}_J".format(r, c))

    kwargs = {
        "ignore_tiles": ignore,
        "pip_predicate": pip_filter,
        "fc_filter": fc_filter,
        "executor": executor
    }

    unspanable_types = []#["CIB_LR_A", "CIB_LR", "CIB_LR_B", "CIB_T"]


    main_cfg = FuzzConfig(job=f"{tiletype}-ROUTE", device=device, tiles=[tile])
    extra_cfg = FuzzConfig(job=f"{tiletype}-ROUTE-EXTRAS", device=device, tiles=[tile])

    if tiletype in unspanable_types:
        fuzz_jobs = [executor.submit(fuzz_interconnect, config =main_cfg, nodenames=nodes, regex=True, bidir=True, **kwargs),
                     executor.submit(fuzz_interconnect, config=extra_cfg, nodenames=extra_sources, regex=False,
                                     bidir=False, **kwargs),
                     ]
        await asyncio.gather(*[asyncio.wrap_future(f) for future_lists in await asyncio.gather(*fuzz_jobs) for f in future_lists])
    else:
        await asyncio.gather(asyncio.create_task(fuzz_interconnect_sinks_across_span(config=main_cfg, tile_span=all_of_type, nodenames=nodes, regex=True,bidir=True, **kwargs)),
                             asyncio.create_task(fuzz_interconnect_sinks_across_span(config = extra_cfg, tile_span=all_of_type, nodenames=extra_sources, regex=False, bidir=False, **kwargs)))


async def per_tiletype(device, tiletype, executor):
    all_of_type = list(tiles.get_tiles_by_tiletype(device, tiletype).keys())

    all_taps = {
        tile
        for tile in tiles.get_tiles_by_tiletype(device, tiletype)
        for tiletype in tiles.get_tiletypes(device)
        if tiletype.startswith("TAP")
    }

    #tiles.draw_rc(device, {tiles.get_rc_from_name(device, t) for t in all_of_type})

    logging.info(f"Total tiles for {tiletype} count {len(all_of_type)}")
    def is_not_edge(tile):
        (r, c) = tiles.get_rc_from_name(device, tile)
        return r > 15 and c > 15

    sorted_tiles = [tile for tile in sorted(all_of_type, key=lambda t: tiles.get_rc_from_name(device, t))]
    tile = sorted_tiles[len(sorted_tiles)//2]

    (r, c) = tiles.get_rc_from_name(device, tile)


    await per_config((r,c), device, tile, all_of_type, all_taps, executor)

async def FuzzAsync(executor):
    cib_tile_types = {t:device
                      for device in fuzzconfig.devices_to_fuzz()
                      for t in tiles.get_tiletypes(device) if t.startswith("CIB")}

    await asyncio.gather(*[
        per_tiletype(device, cib_tile_type, executor)
        for cib_tile_type,device in cib_tile_types.items()
    ])

def main():
    FuzzerAsyncMain(FuzzAsync)

if __name__ == "__main__":
    main()
