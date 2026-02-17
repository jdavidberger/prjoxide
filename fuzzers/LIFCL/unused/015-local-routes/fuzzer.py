import asyncio
import logging
import re
import sys
from collections import defaultdict

import cachecontrol
import fuzzconfig
import fuzzloops
import interconnect
import lapie
import libpyprjoxide
import nonrouting
import primitives
import radiant
import tiles
from fuzzconfig import FuzzConfig, db_lock
from interconnect import fuzz_interconnect_sinks

import database

###
# The idea for this fuzzer is that we can map out the internal pips and connections for a given tiletype in relatively
# short order without knowing much about them by using the introspection from the radiant tools. The basic process is:
# - Generate a list of wires and pips a given tile type has
# - Figure out which tiles configure these pips
# - Use all the tiles of that tiletype on the board to test. So if there are 16 tiles with that tiletype, we can solve
#   for 16 PIP configurations at a time.
###

processed_tiletypes = set()

exclusion_list = {
    # I think this particular pip needs other things in SYSIO_B3 to trigger, but when SYSIO_B3_1 is
    # driving SYSIO_B3_0_ECLK_L, the pip seems active. Just blacklist this one and accept the bit flip.
    ("SYSIO_B3_0", "JECLKIN1_I218", "JECLKOUT_I218")
}

### Gather up all the consistent internal pips for a tiletype, then use however many tiles of that tiletype exist
### to create design sets for each PIP. This also tracks and manages tiles that configure the tiletype but are positioned
### relative to it and have different tiles types
async def tiletype_interconnect_job(device, tiletype, executor = None):

    # representative nodes is all wires that are common to all instances of that tiletype for the device
    wires = tiles.get_representative_nodes_for_tiletype(device, tiletype)

    logging.info(f"Tiletype {tiletype} has {len(wires)} representative nodes; coincides with {tiles.get_coincidental_tiletypes_for_tiletype(device, tiletype)}")

    if len(wires) == 0:
        logging.debug(f"{tiletype} has no consistent internal wires")
        return tiletype, [], []

    ts = sorted(list(tiles.get_tiles_by_tiletype(device, tiletype).keys()))

    # Treat this as an exemplar node to gather the pips from
    (r, c) = tiles.get_rc_from_name(device, ts[0])
    nodes = set([tiles.resolve_actual_node(device, w, (r,c)) for w in wires])

    if None in nodes:
        nodes.remove(None)

    # These are almost 100% consistent EXCEPT for the center of the chip where the lines have to make a longer jump.
    special_nodes = ["HFIE", "HFOE"]

    pips = sorted([
        (p.from_wire, p.to_wire)
        for n in lapie.get_node_data(device, nodes)
        for p in n.uphill_pips
        if not any([special_node in n
            for special_node in special_nodes
            for n in [p.from_wire, p.to_wire]
        ])
    ])

    cfg = FuzzConfig(job=f"{tiletype}-routes", device=device, tiles=[ts[0]])

    await asyncio.create_task(interconnect.fuzz_interconnect_sinks_across_span(
        config = cfg,
        tile_span = ts,
        pips = pips,
        exclusion_list=exclusion_list,
        executor = executor
    ))

def get_filtered_typetypes(device):
    tiletypes = tiles.get_tiletypes(device)
    for tiletype, ts in sorted(tiletypes.items()):

        if tiletype in ["TAP_PLC"]:
            continue

        if len(sys.argv) > 1 and re.compile(sys.argv[1]).search(tiletype) is None:
            continue

        if tiletype in processed_tiletypes:
            continue
        processed_tiletypes.add(tiletype)
        yield tiletype

async def run_for_device(device, executor = None):
    if not fuzzconfig.should_fuzz_platform(device):
        logging.warning(f"Ignoring device {device}")
        return []

    logging.info("Fuzzing device: " + device)

    await asyncio.gather(*[tiletype_interconnect_job(device, tiletype, executor=executor)
                           for tiletype in get_filtered_typetypes(device)])

    return []

async def FuzzAsync(executor):

    families = database.get_devices()["families"]
    devices = sorted([
        device
        for family in families
        for device in families[family]["devices"]
        if fuzzconfig.should_fuzz_platform(device)
    ])

    all_tiletypes = sorted(set([tile.split(":")[-1]
                                for device in devices
                                for tile in database.get_tilegrid(device)["tiles"]
                                ]))

    if len(sys.argv) > 1 and not any(map(lambda tt: re.compile(sys.argv[1]).search(tt), all_tiletypes)):
        logging.warning(f"Tiletype filter doesn't match any known tiles")
        logging.warning(sorted(all_tiletypes))
        return []

    return await asyncio.gather(*[run_for_device(device, executor) for device in devices])

if __name__ == "__main__":
    fuzzloops.FuzzerAsyncMain(FuzzAsync)
