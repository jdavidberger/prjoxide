import hashlib
import itertools
import json
import logging
import pprint
import traceback
from functools import cache

from fuzzconfig import FuzzConfig
import interconnect
import re
import database
import tiles
import random
import fuzzloops
import fuzzconfig
import lapie
import libpyprjoxide
import asyncio
from collections import defaultdict

from DesignFileBuilder import UnexpectedDeltaException, DesignFileBuilder, BitConflictException

def stablehash(x):
    def set_default(obj):
        if isinstance(obj, set):
            return sorted(obj)
        raise TypeError

    bytes_data = json.dumps(x, sort_keys=True, default=set_default).encode('utf-8')

    hasher = hashlib.new("sha1")
    hasher.update(bytes_data)

    return hasher.hexdigest()

def make_dict_of_lists(lst, key):
    rtn = defaultdict(list)
    for item in lst:
        rtn[key(item)].append(item)
    return rtn


async def FuzzAsync(executor):
    families = database.get_devices()["families"]
    devices = [
        device
        for family in families
        for device in families[family]["devices"]
        if fuzzconfig.should_fuzz_platform(device)
    ]

    for device in devices:
        logging.info(device)

        tiletype = "PLC"

        tilegrid = database.get_tilegrid(device)['tiles']

        all_tiles = sorted({k for k in tilegrid})

        # Map of tiles group -> pip grouping
        rel_pip_groups = await tiles.get_pip_tile_groupings(device, all_tiles)

        pips_to_tiles = defaultdict(list)
        for ts, pips in rel_pip_groups.items():
            for pip in pips:
                for t in ts:
                    pips_to_tiles[pip].append(t)

        rel_pip_groups_by_tiletype = defaultdict(set)

        for pip,ts in pips_to_tiles.items():
            for tile_type, tt_ts in make_dict_of_lists(ts, lambda x: x.split(":")[-1]).items():

                rel_pip_groups_by_tiletype[tuple(sorted(tt_ts))].add(pip)


        sorted_groups = sorted(rel_pip_groups.items(), key=lambda x: len(x[0]), reverse=True)

        json_groups = [
            (k, sorted([[", ".join(map(str, w)) for w in p] for p in v]))
            for k, v in sorted_groups
        ]
        def set_default(obj):
            if isinstance(obj, set):
                return sorted(obj)
            raise TypeError

        def pip_is_tiletype_dependent(p):
            return True
            return any([(w[0].split(":")[0] in ["C"] or w[0].startswith("G:VCC"))
                        for w in p])

        dll_core_wire = re.compile(r"^J(CODEI(\d+)_I_DQS_TOP_DLL_CODE_ROUTING_MUX|D[01]_I4_\d)$")

        overlays = {}
        for ts, anon_pips in rel_pip_groups_by_tiletype.items():
            assert (len(ts) == len(set(ts)))
            assert (len(anon_pips) == len(set(anon_pips)))
            for needs_tt, split_anon_pips in make_dict_of_lists(sorted(set(anon_pips)), pip_is_tiletype_dependent).items():
                split_anon_pips = sorted(split_anon_pips)

                if needs_tt:
                    for tt, grp in make_dict_of_lists(ts, lambda x: x.split(":")[-1]).items():
                        grp = sorted(grp)

                        overlay_args = [tt]
                        if tt == "TAP_CIB":
                            overlay_args.append(device)

                        overlays[(tuple(sorted(split_anon_pips)), *overlay_args)] = grp
                else:
                    overlays[(tuple(sorted(split_anon_pips)), )] = sorted(ts)


        def make_overlay_name(k):
            (anon_pips, *args) = k
            return "-".join([*args, stablehash(anon_pips)])

        tiles_to_overlays = {}
        for k,lst in overlays.items():
            for item in lst:
                if item not in tiles_to_overlays:
                    tiles_to_overlays[item] = {item.split(":")[-1]}
                tiles_to_overlays[item].add("overlay/" + make_overlay_name(k))

        overlays_to_tiles = defaultdict(set)
        for tile,tile_overlays in tiles_to_overlays.items():
            overlays_to_tiles[tuple(sorted(tile_overlays))].add(tile)

        db_sub_dir = database.get_db_subdir(device = device)
        with open(f"{db_sub_dir}/overlays.json", "w") as f:
            overlay_doc = {
                #"overlay_membership": {make_overlay_name(k):sorted(v) for k,v in overlays.items()},
                "overlays": {
                    stablehash(k): sorted(k) for k in overlays_to_tiles
                },
                "tiletypes": {
                    stablehash(k): sorted(v) for k,v in overlays_to_tiles.items()
                }
            }

            json.dump(overlay_doc, f, default=set_default, indent=4, sort_keys=True)

        builder = DesignFileBuilder(device, executor)

        async def interconnect_group(overlay_key, ts):
            (anon_pips, *args) = overlay_key
            overlay = make_overlay_name(overlay_key)

            config = FuzzConfig(job=f"{tiletype}-routes", device=device, tiles=ts)
            return await interconnect.fuzz_interconnect_sinks_across_span(config, ts, anon_pips, executor=executor, overlay=overlay, check_pip_placement=False, builder=builder)

        logging.info(f"Overlay count: {len(overlays)}")

        try:
            async with asyncio.TaskGroup() as tg:
                for k, v in sorted(overlays.items()):
                    tg.create_task(interconnect_group(k, v), name=f"interconnect_group_{make_overlay_name(k)}")
                tg.create_task(builder.build_task())
        except* UnexpectedDeltaException as egrp:
            logging.error(f"Caught an exception group for unexpected deltas: {egrp} {egrp.exceptions}")
            for e in egrp.exceptions:
                await e.find_bad_design(executor)
            raise
        except* BitConflictException as egrp:
            logging.error(f"Caught an exception group for bit conflicts: {egrp} {egrp.exceptions}")
            for e in egrp.exceptions:
                await e.solve_standalone()
            raise
        except* BaseException as eg:
            logging.error(f"Caught an exception group for base: {eg} {eg.exceptions}")
            for e in eg.exceptions:
                traceback.print_exception(e)
            raise

if __name__ == "__main__":
    fuzzloops.FuzzerAsyncMain(FuzzAsync)

