import logging
import shutil
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import Future

import fuzzconfig
import fuzzloops
import interconnect
import libpyprjoxide
import nonrouting
import primitives
import radiant
import tiles
from cachier import cachier
from fuzzconfig import FuzzConfig, get_db
from interconnect import fuzz_interconnect_sinks

import database

tiletypes = set()

overlapping_tile_types = set(["CIB", "MIB_B_TAP"] +
                             [f"BANKREF{i}" for i in range(16)] +
                             [f"BK{i}_15K" for i in range(16)]
                             )

def get_site_tiles(device, site):
    site_tiles = [tile for tile in tiles.get_tiles_by_rc(device, site) if
                  tile.split(":")[1] not in overlapping_tile_types]

    return site_tiles

def site_differences(device, bitfile, baseline = None):
    if baseline is None:
        baseline = FuzzConfig.standard_empty(device)

    deltas = libpyprjoxide.Chip.from_bitstream(fuzzconfig.db, baseline).delta(fuzzconfig.db, bitfile)

    ip_values = libpyprjoxide.Chip.from_bitstream(fuzzconfig.db, bitfile).get_ip_values()
    ip_values = [(a,v) for a,v in ip_values if v != 0]

    power_tile_types = set(["PMU"] + [f"BANKREF{i}" for i in range(16)])
    pmu_tiles = [x for x in list(deltas.keys()) if x.split(":")[-1] in power_tile_types]
    driving_tiles = [x for x in list(deltas.keys()) if x.split(":")[-1] not in power_tile_types]

    tile = driving_tiles[0]

    return (driving_tiles + pmu_tiles), ip_values


@cachier(separate_files=True, cache_dir='.cachier')
def find_relevant_tiles(device, primitive_config, site, site_type):
    cfg = FuzzConfig(job=f"{site}", device=device, tiles=[])

    empty_file = FuzzConfig.standard_empty(device)

    primitive_type = cfg.build_design("./primitive.v", {
        "config": primitive_config,
        "site": site,
        "site_type": site_type,
        "extra": "",
        "signals": ""
    }, prefix=site + "/")

    deltas = libpyprjoxide.Chip.from_bitstream(fuzzconfig.db, empty_file).delta(fuzzconfig.db, primitive_type)

    ip_values = libpyprjoxide.Chip.from_bitstream(fuzzconfig.db, primitive_type).get_ip_values()
    ip_values = [(a,v) for a,v in ip_values if v != 0]

    power_tile_types = set(["PMU"] + [f"BANKREF{i}" for i in range(16)])
    pmu_tiles = [x for x in list(deltas.keys()) if x.split(":")[-1] in power_tile_types]

    delta_sorted = [x[0] for x in sorted(deltas.items(), key=lambda x: -len(x[1]))]
    driving_tiles = [x for x in delta_sorted if x.split(":")[-1] not in power_tile_types]
    print(delta_sorted)

    # single_driving_type_check = site_type in ["PCLKDIV", "ECLKDIV_CORE", "DIFFIO18_CORE"] or len(driving_tiles) == 1
    # if not single_driving_type_check:
    #     raise Exception(f"{site_type} should have single driving tile but it has {driving_tiles}. {deltas}")

    tile = driving_tiles[0]

    site_tiles = [tile for tile in tiles.get_tiles_by_rc(device, site) if
                  tile.split(":")[1] not in overlapping_tile_types]

    # This happens for DCC, DCS
    if len(site_tiles) == 0:
        site_tiles = driving_tiles

    return (driving_tiles + pmu_tiles), site_tiles, ip_values

def map_local_pips(name, device, ts, pips, local_graph, executor = None):
    cfg = FuzzConfig(job=name, sv="../shared/route.v", device=device, tiles=ts)

    external_nodes = [wire for pip in pips for wire in pip if wire not in local_graph]

    # CIB is routed separately
    cfg.tiles.extend(
        [tile for n in external_nodes for tile in tiles.get_tiles_by_rc(device, n) if tile.split(":")[-1] != "CIB"])

    return fuzz_interconnect_sinks(cfg, pips, False, executor = executor)

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
        cfg = FuzzConfig(job=f"config/{site}/{mode.mode}", device=device, sv="primitive.v", tiles= related_tiles if len(ip_values) == 0 else [f"{site}:{site_type}"])

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

def run_for_device(device, executor = None):
    if not fuzzconfig.should_fuzz_platform(device):
        return

    sites = database.get_sites(device)

    def find_relevant_tiles_for_site(site, site_info):
        site_type = site_info["type"]

        primitive = primitives.primitives[site_type][0]

        return find_relevant_tiles(device, primitive.fill_config(), site, site_type)

    def find_relevant_tiles_for_site_without_primitive(site, site_info):

        pips, local_graph = tiles.get_local_pips_for_site(device, site)
        cfg = FuzzConfig(job=f"{site}", device=device, tiles=[])

        all_wires_bit = interconnect.create_wires_file(cfg, pips, prefix = site)

        (driving_tiles, ip_delta) = site_differences(device, all_wires_bit)
        site_tiles = get_site_tiles(device, site)

        return (driving_tiles, site_tiles, ip_delta)

    def per_site(site, site_info, relevant_tile_info):
        site_type = site_info["type"]

        (driving_tiles, site_tiles, ip_values) = relevant_tile_info

        tiletype = driving_tiles[0].split(":")[1]
        if tiletype in tiletypes:
            return []

        tiletypes.add(tiletype)

        logging.info(f"====== {site} : {tiletype} ==========")
        pips, local_graph = tiles.get_local_pips_for_site(device, site)
        pips_future = map_local_pips(site, device, driving_tiles + site_tiles, pips, local_graph, executor=executor)

        # Map primitive parameter settings
        settings_future = map_primitive_settings(device, driving_tiles + site_tiles, site, site_tiles, site_type, ip_values, executor = executor)

        return [pips_future, settings_future]

    device_futures = []
    for site, site_info in sorted(sites.items()):
        site_type = site_info["type"]

        if len(sys.argv) > 1 and sys.argv[1] != site_type:
            continue

        if site_type in ["PLL_CORE"] and device in ["LIFCL-33U"]:
            logging.warning(f"Can't map out IP core f{site_type} with device {device} which is in readback mode")
            continue

        f = None
        if site_type not in primitives.primitives:
            continue
            f = executor.submit(find_relevant_tiles_for_site_without_primitive, site, site_info)

        else:
            f = executor.submit(find_relevant_tiles_for_site, site, site_info)

        f.name = "Find tiles"
        site_future = fuzzloops.chain(f, lambda fut, site=site, site_info=site_info: per_site(site, site_info, fut), "Map site")

        device_futures.extend([f, site_future])

    return device_futures

def main():
    get_db()

    families = database.get_devices()["families"]
    devices = sorted([
        device
        for family in families
        for device in families[family]["devices"]
    ])

    all_sites = set([site_info["type"]
                 for device in devices
                 for site,site_info in database.get_sites(device).items()
                 ])

    if len(sys.argv) > 1 and sys.argv[1] not in all_sites:
        logging.warning(f"Site filter doesn't match any known sites")
        print(sorted(all_sites))

        return

    fuzzloops.FuzzerMain(lambda executor: [ run_for_device(device, executor) for device in devices ])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
