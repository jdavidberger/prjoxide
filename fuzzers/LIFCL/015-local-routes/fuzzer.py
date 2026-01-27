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
from fuzzconfig import FuzzConfig, get_db
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

processed_tiletypes = set("PLC")

exclusion_list = {
    # I think this particular pip needs other things in SYSIO_B3 to trigger, but when SYSIO_B3_1 is
    # driving SYSIO_B3_0_ECLK_L, the pip seems active. Just blacklist this one and accept the bit flip.
    ("SYSIO_B3_0", "JECLKIN1_I218", "JECLKOUT_I218")
}

# Cache this so we only do it once. Could also probably read the ron file and check it.
@cachecontrol.cache_fn()
def register_tile_connections(device, tiletype, tile, conn_pips):
    connection_sinks = defaultdict(list)
    for (frm, to) in conn_pips:
        connection_sinks[to].append(frm)

    db = libpyprjoxide.Database(database.get_db_root())
    family = device.split("-")[0]
    for (to_wire, froms) in connection_sinks.items():
        for from_wire in froms:
            db.add_conn(family, tiletype, to_wire, from_wire)
    db.flush()

### Gather up all the consistent internal pips for a tiletype, then use however many tiles of that tiletype exist
### to create design sets for each PIP. This also tracks and manages tiles that configure the tiletype but are positioned
### relative to it and have different tiles types
async def get_tiletype_design_sets(device, tiletype, executor = None):

    # representative nodes is all wires that are common to all instances of that tiletype for the device
    wires = tiles.get_representative_nodes_for_tiletype(device, tiletype)

    if len(wires) == 0:
        logging.debug(f"{tiletype} has no consistent internal wires")
        return tiletype, [], []

    ts = sorted(list(tiles.get_tiles_by_tiletype(device, tiletype).keys()))

    # Treat this as an exemplar node to gather the pips from
    (r, c) = tiles.get_rc_from_name(device, ts[0])
    nodes = set([f"R{r}C{c}_{w}" for w in wires])
    pips, tiletype_graph = await asyncio.wrap_future(tiles.get_local_pips_for_nodes(device, nodes, include_interface_pips=False,
                                                                                             should_expand=lambda p: p[0] in nodes and p[1] in nodes,
                                                                                             executor = executor))

    # Jump wires are what lattice tools refer to as connections -- basically PIPs that are always on
    connected_arcs = lapie.get_jump_wires_by_nodes(device, nodes)

    # Remove the jump wires -- no point in including them in our designs, we already know they are connections
    conn_pips = set(pips) & connected_arcs
    actual_pips = set(pips) - conn_pips
    pips = sorted(actual_pips)

    # While we have the list, we might as well mark down that they are connections
    register_tile_connections(device, tiletype, ts[0], sorted(conn_pips))

    anon_pips = sorted(set([tuple(["_".join(w.split("_")[1:]) for w in p]) for p in pips]))

    baseline = FuzzConfig.standard_empty(device)
    cfg = FuzzConfig(job=f"find-tile-set-{device}-{tiletype}", device=device)

    bitstream = await asyncio.wrap_future(interconnect.create_wires_file(cfg, pips, executor=executor))

    deltas, _  =fuzzconfig.find_baseline_differences(device, bitstream)

    # PLC is used to affix the wires, strip those from the delta
    filtered_deltas = {k:v for k,v in deltas.items() if k.split(":")[1] != "PLC"}

    # PIPs are often controlled by nearby tiles. Convert those to relative positioned tiles. Since sometimes two tiles
    # will share an RC, we grab the tiletype too.
    modified_tiles_rcs = set([(tiles.get_rc_from_name(device, n),n.split(":")[-1]) for n in filtered_deltas.keys()])
    modified_tiles_rcs_anon = [((r0-r),(c0-c),tt) for ((r0,c0),tt) in modified_tiles_rcs]

    logging.info(f"{tiletype} has {len(anon_pips)} PIPs for {len(ts)} tiles {len(conn_pips)} connections and {len(nodes)} nodes with {modified_tiles_rcs_anon} modified tiles")

    logging.debug(f"{tiletype} Connections:")
    for c in conn_pips:
        logging.debug(f"    - {c}")

    logging.debug(f"{tiletype} pips:")
    for c in anon_pips:
        logging.debug(f"    - {c}")

    # Either there are no pips or a primitive enables them
    if len(modified_tiles_rcs_anon) == 0:
        return tiletype, [], []

    # TAP_PLC's are weird and need to be mapped separately.
    if "TAP_PLC" in [tt for (_,_,tt) in modified_tiles_rcs_anon]:
        logging.warning(f"Ignoring {tiletype}; {modified_tiles_rcs_anon}")
        return tiletype, [], []

    design_sets = []
    rcs_for_tiles_of_tiletype = sorted([(tile,tiles.get_rc_from_name(device, tile)) for tile in ts])

    extra_rcs = [((r+rd), (c+cd), tt)
                 for (_, (r,c)) in rcs_for_tiles_of_tiletype
                 for (rd,cd,tt) in modified_tiles_rcs_anon]

    # Make sure there isn't overlap between modified tiles for all the tiles of the type.
    assert(len(extra_rcs) == len(set(extra_rcs)))
    extra_rcs = set(extra_rcs)

    # Generate design sets by continuously iterating through tile locations and putting a random PIP there.
    while len(anon_pips):
        design_set = {}

        # Just place all the extra tiles. We dont have pips for these tiles but this marks it as used.
        for rc in extra_rcs:
            for tile in tiles.get_tiles_by_rc(device, rc):
                design_set[tile] = None
        for (tile, (r,c)) in rcs_for_tiles_of_tiletype:
            pip = anon_pips.pop()
            pip = [f"R{r}C{c}_{w}" for w in pip]
            design_set[tile] = pip

            if len(anon_pips) == 0:
                break

        if len(design_set):
            design_sets.append(design_set)

    return tiletype, design_sets, modified_tiles_rcs_anon

def get_filtered_typetypes(device):
    tiletypes = tiles.get_tiletypes(device)
    for tiletype, ts in sorted(tiletypes.items()):

        if tiletype in ["PLC", "TAP_PLC"]:
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

    device_futures = [
        get_tiletype_design_sets(device, tiletype, executor=executor)
        for tiletype in get_filtered_typetypes(device)
    ]

    # list of list of dicts
    logging.info(f"Gathering {len(device_futures)} tile type pips")
    all_design_sets = await asyncio.gather(*device_futures)

    owned_rcs = {tt:e for (tt,d,e) in all_design_sets}

    design_sets = []
    while True:
        design_set = {}
        owners = defaultdict(list)
        for (tiletype, designs, extra_rcs) in all_design_sets:
            if len(designs) and len(designs[-1].keys() & design_set.keys()) == 0:
                owners[tiletype].extend(designs[-1].keys())
                design_set.update(designs.pop())

                # The original idea here was that the tile types could be combined. However, this
                # does seem to trigger some bit changes
                break
        if len(design_set) == 0:
            break
        design_sets.append((owners, design_set))

    logging.info(f"Building {len(design_sets)} designs")
    cfg = FuzzConfig(job="all-routing", device=device, tiles=[])

    diff_designs_futures = []
    empty_file = FuzzConfig.standard_empty(device)
    for idx, (owners, design_set) in enumerate(design_sets):
        pips = [pip for tile, pip in design_set.items() if pip is not None]
        create_bitstream_future = interconnect.create_wires_file(cfg, pips, executor=executor, prefix=f"{idx}/")
        diff_designs_futures.append(fuzzloops.chain(create_bitstream_future, "solve_design", lambda x,device=device: fuzzconfig.find_baseline_differences(device, x)[0]))

    all_design_diffs = await asyncio.gather(*[asyncio.wrap_future(f) for f in diff_designs_futures])

    def anon_pip(p):
        return ["_".join(w.split("_")[1:]) for w in p]

    pip_deltas = defaultdict(list)
    for (deltas, (owners, design_set)) in zip(all_design_diffs, design_sets):
        rc_deltas = {(*tiles.get_rc_from_name(device, k), k.split(":")[-1]):v for k,v in deltas.items()}

        owned_by = {}
        for k,ts in owners.items():
            for tile in ts:
                owned_by[tile] = k
        for tile, pip in design_set.items():
            tiletype = tile.split(":")[1]
            if pip is not None:
                rc = tiles.get_rc_from_name(device, pip[0])
                tile_owned_rcs = set([
                    (orc[0]+rc[0], orc[1]+rc[1], orc[2])
                    for orc in owned_rcs[tiletype]
                ])

                owned_tiles_for_tiletype = {
                    k:rc_deltas.get(k, [])
                    for k in tile_owned_rcs
                }

                rc_tiles_for_tiletype = {(r-rc[0], c-rc[1], tiletype):d for (r,c,tiletype),d in owned_tiles_for_tiletype.items()}

                apip = anon_pip(pip)
                pip_deltas[tiletype].append((apip, rc_tiles_for_tiletype))

    for tiletype, pips_with_deltas in pip_deltas.items():
        sinks = defaultdict(list)
        for (pip, deltas) in pips_with_deltas:
            sinks[pip[1]].append((pip[0], deltas))

        all_ts = sorted(list(tiles.get_tiles_by_tiletype(device, tiletype).keys()))
        tile = all_ts[0]
        ts = [tile]

        logging.debug(f"Solving for {len(sinks)} sinks on {tiletype}; ref tile {tile}")
        for to_wire, full_deltas in sinks.items():

            rc = tiles.get_rc_from_name(device, tile)
            rc_prefix = f"R{rc[0]}C{rc[1]}_"
            tile_lookup = {}
            for from_wire, deltas in full_deltas:
                for (r1, c1, tiletype), d in deltas.items():
                    for t in tiles.get_tiles_by_rc(device, (r1+rc[0],c1+rc[1])):
                        if t.split(":")[-1] == tiletype:
                            tile_lookup[(r1,c1,tiletype)] = t
                            ts.append(t)

            cfg = FuzzConfig(job=f"{tiletype}/{to_wire}", device=device, tiles=ts)
            fz = libpyprjoxide.Fuzzer.pip_fuzzer(fuzzconfig.db, empty_file, set(ts), rc_prefix + to_wire, tile,
                                             set(), "MUX" in to_wire, False)
            for from_wire, deltas in full_deltas:
                if (tiletype, from_wire, to_wire) in exclusion_list:
                    continue

                concrete_deltas = {tile_lookup[k]: v for k, v in deltas.items() if len(v)}
                logging.debug(f"{tiletype} {from_wire} -> {to_wire} has {len(concrete_deltas)} delta tiles")
                fz.add_pip_sample_delta(rc_prefix + from_wire, concrete_deltas)
            cfg.solve(fz)

    return []

async def run_for_devices(executor):
    get_db()
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
    fuzzloops.FuzzerAsyncMain(run_for_devices)
