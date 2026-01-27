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

processed_tiletypes = set("PLC")

exclusion_list = {
    # I think this particular pip needs other things in SYSIO_B3 to trigger, but when SYSIO_B3_1 is
    # driving SYSIO_B3_0_ECLK_L, the pip seems active. Just blacklist this one and accept the bit flip.
    ("SYSIO_B3_0", "JECLKIN1_I218", "JECLKOUT_I218")
}

# Cache this so we only do it once. Could also probably read the ron file and check it
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

async def get_tiletype_pips(device, tiletype, executor = None):
    wires = tiles.get_representative_nodes_for_tiletype(device, tiletype)

    if len(wires) == 0:
        logging.debug(f"{tiletype} has no consistent internal wires")
        return tiletype, [], []

    arcs = lapie.get_list_arc(device)

    ts = sorted(list(tiles.get_tiles_by_tiletype(device, tiletype).keys()))
    (r, c) = tiles.get_rc_from_name(device, ts[0])
    nodes = set([f"R{r}C{c}_{w}" for w in wires])

    internal_and_external_pips, tiletype_graph = await asyncio.wrap_future(tiles.get_local_pips_for_nodes(device, nodes, include_interface_pips=True,
                                                                                             should_expand=lambda p: p[0] in nodes and p[1] in nodes,
                                                                                             executor = executor))
    pips = {p for p in internal_and_external_pips if p[0] in tiletype_graph and p[1] in tiletype_graph}

    connected_arcs = set([
        (frm_wire, to_wire)
        for (frm_wire, to_wire) in arcs
        if frm_wire in nodes
    ])

    conn_pips = set(pips) & connected_arcs
    actual_pips = set(pips) - conn_pips
    pips = sorted(actual_pips)

    register_tile_connections(device, tiletype, ts[0], sorted(conn_pips))

    anon_pips = sorted(set([tuple(["_".join(w.split("_")[1:]) for w in p]) for p in pips]))

    baseline = FuzzConfig.standard_empty(device)
    cfg = FuzzConfig(job=f"find-tile-set-{device}-{tiletype}", device=device)
    baseline_pips = []
    baseline_nodes = set()
    for p in pips:
        if not p[0] in baseline_nodes and not p[1] in baseline_nodes:
            for w in p:
                baseline_nodes.add(w)
            baseline_pips.append(p)

    bitstream = await asyncio.wrap_future(interconnect.create_wires_file(cfg, pips, executor=executor))
    deltas = libpyprjoxide.Chip.from_bitstream(fuzzconfig.db, baseline).delta(fuzzconfig.db, bitstream)
    filtered_deltas = {k:v for k,v in deltas.items() if k.split(":")[1] != "PLC"}

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
    rcs = sorted([(tile,tiles.get_rc_from_name(device, tile)) for tile in ts])

    extra_rcs = set([((r+rd), (c+cd), tt)
                 for (_, (r,c)) in rcs
                 for (rd,cd,tt) in modified_tiles_rcs_anon])

    while len(anon_pips):
        design_set = {}
        for rc in extra_rcs:
            for tile in tiles.get_tiles_by_rc(device, rc):
                design_set[tile] = None
        for (tile, (r,c)) in rcs:
            pip = anon_pips.pop()
            pip = [f"R{r}C{c}_{w}" for w in pip]
            design_set[tile] = pip
            #
            # design_sets.append(design_set)
            # design_set = {}

            if len(anon_pips) == 0:
                break

        if len(design_set):
            design_sets.append(design_set)

    return tiletype, design_sets, modified_tiles_rcs_anon

def diff_designs(bitstream, baseline):
    deltas = libpyprjoxide.Chip.from_bitstream(fuzzconfig.db, baseline).delta(fuzzconfig.db, bitstream)
    deltas = {k:v for (k,v) in deltas.items() if k.split(":")[1] != "PLC"}
    return deltas

async def run_for_device(device, executor = None):
    if not fuzzconfig.should_fuzz_platform(device):
        logging.warning(f"Ignoring device {device}")
        return []

    logging.info("Fuzzing device: " + device)

    lapie.get_list_arc(device)

    tiletypes = tiles.get_tiletypes(device)

    device_futures = []

    for tiletype, ts in sorted(tiletypes.items()):

        if tiletype in ["PLC", "TAP_PLC"]:
            continue

        if len(sys.argv) > 1 and re.compile(sys.argv[1]).search(tiletype) is None:
            continue

        if tiletype in processed_tiletypes:
            continue
        processed_tiletypes.add(tiletype)

        device_futures.append(get_tiletype_pips(device, tiletype, executor=executor))

    # list of list of dicts
    logging.info(f"Gathering {len(device_futures)} tiletypes")
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
        diff_designs_futures.append(fuzzloops.chain(create_bitstream_future, diff_designs, "solve_design", empty_file))

    all_design_diffs = await asyncio.gather(*[asyncio.wrap_future(f) for f in diff_designs_futures])

    def anon_pip(p):
        return ["_".join(w.split("_")[1:]) for w in p]

    # for (i, (deltas, (owners, design_set))) in enumerate(zip(all_design_diffs, design_sets)):
    #     with open(f"delta_raw{i}.json", "w") as f:
    #         json.dump(deltas, f, indent=4)
    #     with open(f"design{i}.json", "w") as f:
    #         json.dump(design_set, f, indent=4)

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
