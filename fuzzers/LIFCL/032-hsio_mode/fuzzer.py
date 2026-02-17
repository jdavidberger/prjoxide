import asyncio
import hashlib
import logging

from fuzzconfig import FuzzConfig, should_fuzz_platform
import nonrouting
import fuzzloops
import re
import database
import tiles
import lapie
import sys

pio_names = ["A", "B"]

def create_config_from_pad(pad, device):
    pin = pad["pins"][0]
    ts = [t for t in tiles.get_tiles_from_edge(device, pad["side"], pad["offset"]) if "SYSIO" in t]

    if len(ts) == 0:
        logging.warning(f"Could not find tile for {pad} for {device}")
        return

    all_sysio = [t for t in tiles.get_tiles_from_edge(device, pad["side"]) if "SYSIO" in t]
    tiletype = ts[0].split(":")[1]

    (r,c) = tiles.get_rc_from_name(device,ts[0])

    # Make sure we get every combination of SYSIO tile types that are next to eachother
    neighbor_tile_types = sorted(list({
        tile.split(":")[1]
        for x in [-1,0,1]
        for y in [-1,0,1]
        for tile in tiles.get_tiles_by_rc(device, ((r+x), (c+y)) ) if "SYSIO" in tile
    }))
    pio = pio_names[pad["pio"]]
    return (
        "|".join(neighbor_tile_types) + "-" + pio,
        (pio_names[pad["pio"]],
         pin,
         FuzzConfig(job=f"{pin}/{ts[0]}/{tiletype}", device=device,
                    tiles=ts + all_sysio))
    )

def create_configs_for_device(device):
    pads = [x for x in database.get_iodb(device)["pads"]]
    configs = dict(filter(None, [
        create_config_from_pad(x, device) for x in pads if x["offset"] >= 0
    ]))
    return configs

configs = (create_configs_for_device("LIFCL-33") | create_configs_for_device("LIFCL-40") ).items()
# + [
#     ("A","V1", # PB6A
#         FuzzConfig(job="IO5A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R56C6:SYSIO_B5_0", "CIB_R56C7:SYSIO_B5_1"])),
#     ("B","W1", # PB6B
#         FuzzConfig(job="IO5B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R56C6:SYSIO_B5_0", "CIB_R56C7:SYSIO_B5_1"])),
#     ("A","Y7", # PB30A
#         FuzzConfig(job="IO4A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R56C30:SYSIO_B4_0", "CIB_R56C31:SYSIO_B4_1"])),
#     ("B","Y8", # PB30B
#         FuzzConfig(job="IO4B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R56C30:SYSIO_B4_0", "CIB_R56C31:SYSIO_B4_1"])),
#     ("A","R12", # PB64A
#         FuzzConfig(job="IO3A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R56C64:SYSIO_B3_0", "CIB_R56C65:SYSIO_B3_1"])),
#     ("B","P12", # PB64A
#         FuzzConfig(job="IO3B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R56C64:SYSIO_B3_0", "CIB_R56C65:SYSIO_B3_1"])),
# ]

seio_types = [
    ("LVCMOS18H", 1.8, None),
    ("LVCMOS15H", 1.5, None),
    ("LVCMOS12H", 1.2, None),
    ("LVCMOS10H", 1.0, None),
    ("LVCMOS10R", 1.8, ["INPUT"]),
    ("SSTL135_I", 1.35, None),
    ("SSTL135_II", 1.35, None),
    ("SSTL15_I", 1.5, None),
    ("SSTL15_II", 1.5, None),
    ("HSTL15_I", 1.5, None),
    ("HSUL12", 1.2, None),
#    ("MIPI_DPHY", 1.2, None),
#    ("VREF1_DRIVER", 1.5, ["OUTPUT"]),
#    ("VREF2_DRIVER", 1.5, ["OUTPUT"]),
]

diffio_types = [
    ("LVDS", 1.8, None),
    ("SUBLVDS", 1.8, ["INPUT"]),
    ("SUBLVDSEH", 1.8, ["OUTPUT"]),
    ("SLVS", 1.2, None),
    ("MIPI_DPHY", 1.2, None),
    ("SSTL135D_I", 1.35, None),
    ("SSTL135D_II", 1.35, None),
    ("SSTL15D_I", 1.5, None),
    ("SSTL15D_II", 1.5, None),
    ("HSTL15D_I", 1.5, None),
    ("HSUL12D", 1.2, None),
]

device_empty_bitfile = {}

async def main(executor):
    async def per_config(config):
        overlay, (pio, site, cfg) = config

        overlay_suffix = hashlib.sha1(overlay.encode()).hexdigest()
        (r,c) = tiles.get_rc_from_name(cfg.device, cfg.tiles[0])

        if f"R{r}C{c}_JPADDO_SEIO18_CORE_IO{pio}" not in tiles.get_full_node_set(cfg.device) and \
           f"R{r}C{c}_JPADDO_DIFFIO18_CORE_IO{pio}" not in tiles.get_full_node_set(cfg.device):
            print(f"Skipping {site}; it's an SEIO33 site")
            return
        
        cfg.setup()
        if cfg.device not in device_empty_bitfile:
            device_empty_bitfile[cfg.device] = cfg.build_design(cfg.sv, {})
        empty = device_empty_bitfile[cfg.device]

        cfg.sv = "iob.v"
        if cfg.device == "LIFCL-40":
            cfg.sv = "iob_40.v"

        def get_bank_vccio(iotype):
            if iotype == "NONE":
                return "1.8"
            else:
                for t, v, d in (seio_types + diffio_types):
                    if t == iotype:
                        return str(v)
        def is_diff(iotype):
            for t, v, d in diffio_types:
                if t == iotype:
                    return True
            return False
        def get_substs(iotype="BIDIR_LVCMOS18H", kv=None, vcc=None, tmux="T"):
            iodir, iostd = iotype.split("_", 1) if iotype != "NONE" else ("","")
            if iodir == "INPUT":
                pintype = "input"
                t = "1"
            elif iodir == "OUTPUT":
                pintype = "output"
                t = "0"
            else:
                pintype = "inout"
                if tmux == "INV":
                    t = "#INV"
                else:
                    t = "#SIG"
            if kv is not None:
                extra_config = ",{}={}".format(kv[0], kv[1])
            else:
                extra_config = ""
            if vcc is None:
                vcc = get_bank_vccio(iostd)
            if is_diff(iostd):
                primtype = "DIFFIO18_CORE"
            else:
                primtype = "SEIO18_CORE"
            return dict(cmt="//" if iotype == "NONE" else "",
                pintype=pintype, primtype=primtype, site=site, iotype=iostd, t=t, extra_config=extra_config, vcc=vcc)
        all_se_types = ["NONE"]
        all_di_types = ["NONE"]
        for t, v, d in seio_types:
            if d is None:
                all_se_types += ["INPUT_{}".format(t), "BIDIR_{}".format(t), "OUTPUT_{}".format(t)]
            else:
                all_se_types += ["{}_{}".format(di, t) for di in d]
        for t, v, d in diffio_types:
            if d is None:
                all_di_types += ["INPUT_{}".format(t), "BIDIR_{}".format(t), "OUTPUT_{}".format(t)]
            else:
                all_di_types += ["{}_{}".format(di, t) for di in d]

        futures = []
        def fuzz_enum_setting(*args, **kwargs):
            futures.append(fuzzloops.wrap_future(nonrouting.fuzz_enum_setting(cfg, empty, executor=executor, overlay=overlay_suffix, *args, **kwargs)))

        fuzz_enum_setting("PIO{}.SEIO18.DRIVE_1V0".format(pio), ["2", "4"],
                                     lambda x: get_substs(iotype="OUTPUT_LVCMOS10H", kv=("DRIVE", x)), True)
        
        fuzz_enum_setting("PIO{}.SEIO18.BASE_TYPE".format(pio), all_se_types,
                                     lambda x: get_substs(iotype=x), False, assume_zero_base=True, mark_relative_to = cfg.tiles[0])

        fuzz_enum_setting("PIO{}.SEIO18.DRIVE_1V8".format(pio), ["2", "4", "8", "12", "50RS"],
                lambda x: get_substs(iotype="OUTPUT_LVCMOS18H", kv=("DRIVE", x)), True)
        fuzz_enum_setting("PIO{}.SEIO18.DRIVE_1V5".format(pio), ["2", "4", "8"],
                lambda x: get_substs(iotype="OUTPUT_LVCMOS15H", kv=("DRIVE", x)), True)
        fuzz_enum_setting("PIO{}.SEIO18.DRIVE_1V2".format(pio), ["2", "4", "8"],
                lambda x: get_substs(iotype="OUTPUT_LVCMOS12H", kv=("DRIVE", x)), True)
        fuzz_enum_setting("PIO{}.SEIO18.DRIVE_HSUL12".format(pio), ["4", "6", "8"],
                lambda x: get_substs(iotype="OUTPUT_HSUL12", kv=("DRIVE", x)), True)

        fuzz_enum_setting("PIO{}.SEIO18.PULLMODE".format(pio), ["NONE", "UP", "DOWN", "KEEPER"],
                lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("PULLMODE", x)), True)

        fuzz_enum_setting("PIO{}.SEIO18.UNDERDRIVE_1V8".format(pio), ["ON", "OFF"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS18H" if x=="OFF" else "INPUT_LVCMOS15H", vcc="1.8"), True)

        fuzz_enum_setting("PIO{}.SEIO18.SLEWRATE".format(pio), ["SLOW", "MED", "FAST"],
                lambda x: get_substs(iotype="OUTPUT_LVCMOS18H", kv=("SLEWRATE", x)), True)

        fuzz_enum_setting("PIO{}.SEIO18.TERMINATION_1V8".format(pio), ["OFF", "40", "50", "60", "75", "150"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("TERMINATION", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.TERMINATION_1V5".format(pio), ["OFF", "40", "50", "60", "75"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS15H", kv=("TERMINATION", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.TERMINATION_1V35".format(pio), ["OFF", "40", "50", "60", "75"],
                        lambda x: get_substs(iotype="INPUT_SSTL135_I", kv=("TERMINATION", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.TERMINATION_1V2".format(pio), ["OFF", "40", "50", "60", "75"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS12H", kv=("TERMINATION", x)), False)


        fuzz_enum_setting("PIO{}.SEIO18.DFTDO2DI".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("DFTDO2DI", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.LOOPBKCD2AB".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("LOOPBKCD2AB", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.OPENDRAIN".format(pio), ["OFF", "ON"],
                        lambda x: get_substs(iotype="OUTPUT_LVCMOS18H", kv=("OPENDRAIN", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.SLEEPHIGHLEAKAGE".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("SLEEPHIGHLEAKAGE", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.ENADC_IN".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("ENADC_IN", x)), False)
        fuzz_enum_setting("PIO{}.SEIO18.INT_LPBK".format(pio), ["DISABLED", "ENABLED"],
                    lambda x: get_substs(iotype="INPUT_LVCMOS18H", kv=("INT_LPBK", x)), False)

        fuzz_enum_setting("PIO{}.SEIO18.VREF".format(pio), ["OFF", "VREF1_LOAD", "VREF2_LOAD"],
            lambda x: get_substs(iotype="INPUT_SSTL135_I", kv=("VREF", x)), False)

        fuzz_enum_setting("PIO{}.TMUX".format(pio), ["T", "INV"],
                    lambda x: get_substs(iotype="BIDIR_LVCMOS18H", tmux=x), False)

        if pio == "A":
            fuzz_enum_setting("PIO{}.DIFFIO18.BASE_TYPE".format(pio), all_di_types,
                            lambda x: get_substs(iotype=x), False)
            fuzz_enum_setting("PIO{}.DIFFIO18.PULLMODE".format(pio), ["NONE", "FAILSAFE"],
                            lambda x: get_substs(iotype="INPUT_LVDS", kv=("PULLMODE", x)), True)
            fuzz_enum_setting("PIO{}.DIFFIO18.DIFFRESISTOR".format(pio), ["OFF", "100"],
                            lambda x: get_substs(iotype="INPUT_LVDS", kv=("DIFFRESISTOR", x)), True)
            fuzz_enum_setting("PIO{}.DIFFIO18.DIFFDRIVE_MIPI_DPHY".format(pio), ["NA", "2P0"],
                            lambda x: get_substs(iotype="OUTPUT_MIPI_DPHY", kv=("DIFFDRIVE", x.replace("P", "."))), False)
            fuzz_enum_setting("PIO{}.DIFFIO18.DIFFDRIVE_SLVS".format(pio), ["NA", "2P0"],
                            lambda x: get_substs(iotype="OUTPUT_SLVS", kv=("DIFFDRIVE", x.replace("P", "."))), False)
            fuzz_enum_setting("PIO{}.DIFFIO18.DIFFDRIVE_LVDS".format(pio), ["NA", "3P5"],
                            lambda x: get_substs(iotype="OUTPUT_LVDS", kv=("DIFFDRIVE", x.replace("P", "."))), False)
            fuzz_enum_setting("PIO{}.DIFFIO18.DIFFRX_INV".format(pio), ["NORMAL", "INVERT"],
                            lambda x: get_substs(iotype="INPUT_LVDS", kv=("DIFFRX_INV", x)), False)
            fuzz_enum_setting("PIO{}.DIFFIO18.DIFFTX_INV".format(pio), ["NORMAL", "INVERT"],
                            lambda x: get_substs(iotype="OUTPUT_LVDS", kv=("DIFFTX_INV", x)), False)

        await asyncio.gather(*futures)

    def cfg_filter(config):
        _, (pio, site, cfg) = config
        if not should_fuzz_platform(cfg.device):
            return False

        if len(sys.argv) > 1 and sys.argv[1] not in cfg.tiles[0]:
            return False

        if len(sys.argv) > 2 and sys.argv[2] != pio:
            return False
        
        return True

    await asyncio.gather(*[per_config(config) for config in filter(cfg_filter, configs)])

if __name__ == "__main__":
    fuzzloops.FuzzerAsyncMain(main)
