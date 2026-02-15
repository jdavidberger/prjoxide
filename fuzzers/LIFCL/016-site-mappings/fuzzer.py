import asyncio
import logging
import re
import sys
import lapie

import cachecontrol
import fuzzconfig
import fuzzloops
import interconnect
import libpyprjoxide
import nonrouting
import primitives
import radiant
import tiles
from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect_sinks

import database

###
# This fuzzer pulls up each site, figures out its relationship to tiletypes, and then find the routeing and primitive
# mappings for those representative tile(s).
###

mapped_sites = set()

# These tiles overlap many sites and are not the main site tiles
overlapping_tile_types = set(["CIB", "MIB_B_TAP", "TAP_CIB"] +
                             [f"BANKREF{i}" for i in range(16)] +
                             [f"BK{i}_15K" for i in range(16)]
                             )

def get_site_tiles(device, site):
    site_tiles = [tile for tile in tiles.get_tiles_by_rc(device, site) if
                  tile.split(":")[1] not in overlapping_tile_types]

    return site_tiles

# Pull from a bitstream baseline delta the main tile and IP changes
def find_relevant_tiles_from_bitstream(device, site, active_bitstream):
    deltas, ip_values = fuzzconfig.find_baseline_differences(device, active_bitstream)

    power_tile_types = set(["PMU"] + [f"BANKREF{i}" for i in range(16)])
    pmu_tiles = [x for x in list(deltas.keys()) if x.split(":")[-1] in power_tile_types]

    delta_sorted = [x[0] for x in sorted(deltas.items(), key=lambda x: -len(x[1]))]
    driving_tiles = [x for x in delta_sorted if x.split(":")[-1] not in power_tile_types]
    site_tiles = [tile for tile in tiles.get_tiles_by_rc(device, site) if
                  tile.split(":")[1] not in overlapping_tile_types]

    # This happens for DCC, DCS
    if len(site_tiles) == 0:
        site_tiles = driving_tiles

    return (driving_tiles + pmu_tiles), site_tiles, ip_values

# Look at the site pins and map out the nodes on those pins. Find the deltas that enable those pips.
async def find_relevant_tiles(device, site, site_type, site_info, executor):
    cfg = FuzzConfig(job=f"{site}:{site_type}", device=device, tiles=[])

    nodes = [p["pin_node"] for p in site_info["pins"]]
    logging.info(f"Getting relevant wire tiles for {device} {site}:{site_type}")
    pips, _ = tiles.get_local_pips_for_nodes(device, nodes, include_interface_pips=True,
                                       should_expand=lambda p: p[0] in nodes or p[1] in nodes)

    wires_bitstream = await asyncio.wrap_future(interconnect.create_wires_file(cfg, pips, prefix=f"find-relevant-tiles/", executor = executor))

    driving_tiles, site_tiles, ip_values = find_relevant_tiles_from_bitstream(device, site, wires_bitstream)

    return ([t for t in driving_tiles if t.split(":")[-1] != "PLC"],
            [t for t in site_tiles if t.split(":")[-1] != "PLC"],
            ip_values
            )

# If we have a primitive definition, use it to generate a bitstream and compare it to baseline. This delta shows which
# tiles the site belongs to.
async def find_relevant_tiles_from_primitive(device, primitive, site, site_info, executor):
    site_type = site_info["type"]

    cfg = FuzzConfig(job=f"{site}:{site_type}", device=device, tiles=[])

    primitive_bitstream = await asyncio.wrap_future(cfg.build_design_future(executor, "./primitive.v", {
        "config": primitive.fill_config(),
        "site": site,
        "site_type": site_type,
        "extra": "",
        "signals": ""
    }, prefix=f"find-relevant-tiles/{primitive.mode}/"))
    logging.info(f"Getting relevant tiles for {device} {site}:{site_type} for {primitive.mode}")

    driving_tiles, site_tiles, ip_values = find_relevant_tiles_from_bitstream(device, site, primitive_bitstream)

    # Also get the tiling from just the wiring
    pin_driving_tiles, pin_site_tiles, pin_ip_values = await find_relevant_tiles(device, site, site_type, site_info, executor = executor)

    # Note: We do this to keep ordering but removing dups
    def uniq(x):
        return list(dict.fromkeys(x))

    return uniq(driving_tiles + pin_driving_tiles), uniq(site_tiles + pin_site_tiles), uniq(ip_values + pin_ip_values)

mux_re = re.compile("MUX[0-9]*$")

# Take all a given sites local graph and pips, and solve for all of it
def map_local_pips(site, site_type, device, ts, pips, local_graph, executor=None):
    cfg = FuzzConfig(job=f"{site}:{site_type}", sv="../shared/route.v", device=device, tiles=ts)

    logging.debug(f"PIPs for {site}:")
    for p in pips:
        logging.debug(f" - {p[0]} -> {p[1]}")

    external_nodes = [wire for pip in pips for wire in pip if wire not in local_graph]

    # CIB is routed separately
    cfg.tiles.extend(
        [tile for n in external_nodes for tile in tiles.get_tiles_by_rc(device, n) if tile.split(":")[-1] != "CIB"])
    cfg.tiles = [t for t in cfg.tiles if not t.split(":")[-1].startswith("CIB")]

    if len(cfg.tiles) == 0:
        logging.warning(f"Local pips for {site} only corresponded to CIB tiles")
        return

    mux_pips = [p for p in pips if mux_re.search(p[0]) and mux_re.search(p[1])]
    non_mux_pips = [p for p in pips if not p in mux_pips]
    if len(non_mux_pips):
        yield from fuzz_interconnect_sinks(cfg, non_mux_pips, False, executor = executor)

    if len(mux_pips):
        mux_cfg = FuzzConfig(job=f"{site}:{site_type}-MUX", sv="../shared/route.v", device=device, tiles=cfg.tiles)
        yield from fuzz_interconnect_sinks(mux_cfg, mux_pips, True, executor = executor)

# Use the primitive definitions to map out each mode's options. Works for IP and non IP settings
def map_primitive_settings(device, ts, site, site_tiles, site_type, ip_values, executor = None):
    if site_type not in primitives.primitives:
        return []

    empty_file = FuzzConfig.standard_empty(device)

    base_addrs = database.get_base_addrs(device)

    if site not in base_addrs:
        ip_values = []

    is_ip_config = len(ip_values) > 0
    if len(ip_values):
        fuzz_enum_setting = nonrouting.fuzz_ip_enum_setting
        fuzz_word_setting = nonrouting.fuzz_ip_word_setting
    else:
        fuzz_enum_setting = nonrouting.fuzz_enum_setting
        fuzz_word_setting = nonrouting.fuzz_word_setting

    def map_mode(mode):
        logging.info(f"====== {mode.mode} : {site_type} IP: {len(ip_values)} ==========")
        related_tiles = (ts + site_tiles)
        cfg = FuzzConfig(job=f"config/{site_type}/{site}/{mode.mode}", device=device, sv="primitive.v", tiles= related_tiles if len(ip_values) == 0 else [f"{site}:{site_type}"])

        slice_sites = tiles.get_tiles_by_tiletype(device, "PLC")
        slice_iter = iter([x for x in slice_sites if tiles.get_rc_from_name(device, x) not in related_tiles])

        extra_lines = []
        signals = []

        avail_in_pins = []
        for p in mode.pins:
            if p.dir == "in" or p.dir == "inout":
                for r in range(0, p.bits if p.bits is not None else 1):
                    suffix = str(r) if p.bits != None else ""
                    avail_in_pins.append(f"{p.name}{suffix}")
        q_driver = None
        def get_sink_pin():
            if len(avail_in_pins):
                in_pin = avail_in_pins.pop()
                extra_lines.append(f"wire q_{in_pin};")
                signals.append(f".{in_pin}(q_{in_pin})")
                return f"q_{in_pin}"

            idx = len(extra_lines)
            extra_lines.append(f"""
            wire q_{idx};            
            (* \\dm:cellmodel_primitives ="REG0=reg", \\dm:primitive ="SLICE", \\dm:programming ="MODE:LOGIC Q0:Q0 ", \\dm:site ="{next(slice_iter).split(":")[0]}A" *) 
            SLICE SLICE_I_{idx} ( .A0(q_{idx}) );
                        """)
            return f"q_{idx}"

        for p in mode.pins:
            for r in range(0, p.bits if p.bits is not None else 1):
                suffix = str(r) if p.bits != None else ""
                if p.dir == "out":
                    q = get_sink_pin()
                    q_driver = q
                    signals.append(f".{p.name}{suffix}({q})")

        if len(avail_in_pins) and q_driver is None:
            extra_lines.append(f"""
                    wire q_driver;            
                    (* \\dm:cellmodel_primitives ="REG0=reg", \\dm:primitive ="SLICE", \\dm:programming ="MODE:LOGIC Q0:Q0 ", \\dm:site ="{next(slice_iter).split(":")[0]}A" *) 
                    SLICE SLICE_I_driver ( .A0(q_driver), .Q0(q_driver) );
                """)
            q_driver = "q_driver"

        for undriven_pin in avail_in_pins:
            signals.append(f".{undriven_pin}({q_driver})")

        subs = {
            "site": site,
            "site_type": site_type,
            "extra": "\n".join(extra_lines),
            "signals": ", ".join(signals)
        }

        def map_mode_setting(setting):
            mark_relative_to = None
            if site_tiles[0] != ts[0]:
                mark_relative_to = site_tiles[0]

            args = {
                "config": cfg,
                "name": f"{mode.mode}.{setting.name}",
                "desc": setting.desc,
                "executor": executor
            }

            if isinstance(setting, primitives.EnumSetting):
                def subs_fn(val):
                    return subs | {"config": mode.configuration([(setting, val)])}

                if len(ip_values) == 0:
                    args["mark_relative_to"] = mark_relative_to

                if isinstance(setting, primitives.ProgrammablePin) and not is_ip_config:
                    args["include_zeros"] = True

                return fuzz_enum_setting(empty_bitfile = empty_file, values = setting.values, get_sv_substs = subs_fn, **args)
            elif isinstance(setting, primitives.WordSetting):
                def subs_fn(val):
                    return subs | {"config": mode.configuration([(setting, nonrouting.fuzz_intval(val))])}

                return fuzz_word_setting(length=setting.bits, get_sv_substs=subs_fn, **args)
            else:
                raise Exception(f"Unknown setting type: {setting}")

        return [map_mode_setting(s) for s in mode.settings]

    return [f for mode in primitives.primitives[site_type] for f in map_mode(mode)]

async def run_for_device(device, executor = None):
    if not fuzzconfig.should_fuzz_platform(device):
        return

    async def find_relevant_tiles_for_site(site, site_info, executor):
        if should_skip_site(site, site_info):
            return None

        site_type = site_info["type"]

        if site_type in primitives.primitives:
            primitive = primitives.primitives[site_type][0]

            return await find_relevant_tiles_from_primitive(device, primitive, site, site_info, executor=executor)

        return await find_relevant_tiles(device, site, site_type, site_info, executor=executor)

    def should_skip_site(site, site_info):
        site_type = site_info["type"]
        if len(sys.argv) > 1 and sys.argv[1] != site_type:
            return True

        if site_type in ["PLL_CORE"] and device in ["LIFCL-33U"]:
            logging.warning(f"Can't map out IP core {site_type} with device {device} which is in readback mode")
            return True

        if site_type in ["CIBTEST", "SLICE"]:
            return True

        return False

    async def per_site(site, site_info, driving_tiles, executor):
        (driving_tiles, site_tiles, ip_values) = driving_tiles

        site_type = site_info["type"]

        logging.info(f"====== {site} : {driving_tiles} ==========")
        tiletype = driving_tiles[0].split(":")[1]

        logging.info(f"====== {site} : {tiletype} ==========")
        pips, local_graph = tiles.get_local_pips_for_site(device, site)

        pips_future = list(map_local_pips(site, site_type, device, driving_tiles + site_tiles, pips, local_graph, executor=executor))

        # Map primitive parameter settings
        settings_future = map_primitive_settings(device, driving_tiles + site_tiles, site, site_tiles, site_type, ip_values, executor = executor)

        return [pips_future, settings_future]

    sites = database.get_sites(device)
    sites_items = [(k,v) for k,v in sorted(sites.items()) if v["type"] not in ["CIBTEST", "SLICE"]]

    driving_tiles_futures = []
    async with asyncio.TaskGroup() as tg:
        for site, site_info in sites_items:
            driving_tiles_futures.append(find_relevant_tiles_for_site(site, site_info, executor=executor))

    all_driving_tiles = await asyncio.gather(*driving_tiles_futures)

    async with (asyncio.TaskGroup() as tg):
        for (site, site_info), driving_tiles_rtn in zip(sites_items, all_driving_tiles):
            if driving_tiles_rtn is None: continue

            driving_tiles, site_tiles, ip_values = driving_tiles_rtn

            driving_tiles = [t for t in driving_tiles if t.split(":")[1] not in ["PLC", "TAB_CIB", "CIB"]]

            if len(driving_tiles) == 0:
                continue

            logging.debug(f"Driving sites for {site}:")
            for t in set(driving_tiles + site_tiles):
                logging.debug(f"   - {t}")

            # Certain sites present different even with the same site_type and tile_type surrounding it. Specifically
            # IO types have A and B suffixes. The IP and configuration is the same, but the pins map to differently
            # named wires and it is the wire name that matters for the DB. So we key on the wire names too
            site_key = (
                site_info["type"],
                tuple(sorted(t.split(":")[-1] for t in driving_tiles)),
                tuple(sorted(f"{p["pin_name"]}:{"_".join(p["pin_node"].split("_")[1:])}" for p in site_info["pins"]))
            )

            logging.debug(f"Site key: {site_key}")
            if mapped_sites in site_key:
                continue

            mapped_sites.add(site_key)
            tg.create_task(per_site(site, site_info, (driving_tiles, site_tiles, ip_values), executor))

async def FuzzAsync(executor):
    families = database.get_devices()["families"]
    devices = sorted([
        device
        for family in families
        for device in families[family]["devices"]
        if fuzzconfig.should_fuzz_platform(device)
    ])

    all_sites = set([site_info["type"]
                     for device in devices
                     if device.startswith("LIFCL")
                     for site, site_info in database.get_sites(device).items()
                     ])

    if len(sys.argv) > 1 and sys.argv[1] not in all_sites:
        logging.warning(f"Site filter doesn't match any known sites")
        logging.info(sorted(all_sites))

        return []

    return await asyncio.gather(*[ run_for_device(device, executor) for device in devices ])

if __name__ == "__main__":
    fuzzloops.FuzzerAsyncMain(FuzzAsync)
