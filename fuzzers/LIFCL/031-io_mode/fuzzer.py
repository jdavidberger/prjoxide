import logging
import signal
import traceback

from fuzzconfig import FuzzConfig, should_fuzz_platform
import nonrouting
import fuzzloops
import re
import database
import tiles
import lapie
import sys
import asyncio

from tqdm.asyncio import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

pio_names = ["A", "B"]


def create_config_from_pad(pad, device):
    pin = pad["pins"][0]
    pio = pad["pio"]
    ts = [t for t in tiles.get_tiles_from_edge(device, pad["side"], pad["offset"]) if "SYSIO" in t]
    all_sysio = [t for t in tiles.get_tiles_from_edge(device, pad["side"]) if "SYSIO" in t]
    if len(ts) == 0:
        logging.warning(f"Could not find tile for {pad} for {device}")
        return

    tiletype = ts[0].split(":")[1]

    return (
        f"{tiletype}-{pio}",
        (pio_names[pad["pio"]], pin,
         FuzzConfig(job=f"IO{pin}_{device}_{tiletype}", device=device,
                    tiles=ts + all_sysio))
    )


def create_device_configs(device):
    pads = [x for x in database.get_iodb(device)["pads"]]
    configs = dict(filter(None, [
        create_config_from_pad(x, device) for x in pads if x["offset"] >= 0
    ]))
    return list(configs.values())

configs = create_device_configs("LIFCL-33") + create_device_configs("LIFCL-33U") + create_device_configs("LIFCL-17") + create_device_configs("LIFCL-40")
#           [
#     ("B", "E11", # PR3B,
#         FuzzConfig(job="IO1D_17K", device="LIFCL-17", sv="../shared/empty_17.v", tiles=["CIB_R3C75:SYSIO_B1_DED_15K"])),
#     ("A","F16", # PR13A
#         FuzzConfig(job="IO1A_17K", device="LIFCL-17", sv="../shared/empty_17.v", tiles=["CIB_R13C75:SYSIO_B1_0_15K", "CIB_R14C75:SYSIO_B1_1_15K"])),
#     ("B","G15", # PR13B
#         FuzzConfig(job="IO1B_17K", device="LIFCL-17", sv="../shared/empty_17.v", tiles=["CIB_R13C75:SYSIO_B1_0_15K", "CIB_R14C75:SYSIO_B1_1_15K"])),
#     ("A","E15", # PT67A
#         FuzzConfig(job="IO0A_17K", device="LIFCL-17", sv="../shared/empty_17.v", tiles=["CIB_R0C67:SYSIO_B0_0_15K"])),
#     ("B","E16", # PT67B
#         FuzzConfig(job="IO0B_17K", device="LIFCL-17", sv="../shared/empty_17.v", tiles=["CIB_R0C67:SYSIO_B0_0_15K"])),
#
#     ("A","F16", # PR8A
#         FuzzConfig(job="IO1AO", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R8C87:SYSIO_B1_0_ODD"])),
#     ("B","F17", # PR8B
#         FuzzConfig(job="IO1BO", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R8C87:SYSIO_B1_0_ODD"])),
#     ("A","F14", # PR6A
#         FuzzConfig(job="IO1AE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R6C87:SYSIO_B1_0_EVEN"])),
#     ("B","F15", # PR6B
#         FuzzConfig(job="IO1BE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R6C87:SYSIO_B1_0_EVEN"])),
#     ("A","F18", # PR10A
#         FuzzConfig(job="IC1A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R10C87:SYSIO_B1_0_C", "CIB_R11C87:SYSIO_B1_0_REM"])),
#     ("B","F19", # PR10B
#         FuzzConfig(job="IC1B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R10C87:SYSIO_B1_0_C", "CIB_R11C87:SYSIO_B1_0_REM"])),
#     ("A","N14", # PR24A
#         FuzzConfig(job="IO2AE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R24C87:SYSIO_B2_0_EVEN"])),
#     ("B","M14", # PR24B
#         FuzzConfig(job="IO2BE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R24C87:SYSIO_B2_0_EVEN"])),
#     ("A","M17", # PR30A
#         FuzzConfig(job="IO2AO", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R30C87:SYSIO_B2_0_ODD"])),
#     ("B","M18", # PR30B
#         FuzzConfig(job="IO2BO", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R30C87:SYSIO_B2_0_ODD"])),
#     ("A","T18", # PR46A
#         FuzzConfig(job="IC2A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R46C87:SYSIO_B2_0_C", "CIB_R47C87:SYSIO_B2_0_REM"])),
#     ("B","U18", # PR46B
#         FuzzConfig(job="IC2B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R46C87:SYSIO_B2_0_C", "CIB_R47C87:SYSIO_B2_0_REM"])),
#     ("A","R3", # PL49A
#         FuzzConfig(job="IO6AO", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R49C0:SYSIO_B6_0_ODD"])),
#     ("B","R4", # PL49B
#         FuzzConfig(job="IO6BO", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R49C0:SYSIO_B6_0_ODD"])),
#     ("A","L1", # PL27A
#         FuzzConfig(job="IO6AE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R27C0:SYSIO_B6_0_EVEN"])),
#     ("B","L2", # PL27B
#         FuzzConfig(job="IO6BE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R27C0:SYSIO_B6_0_EVEN"])),
#     ("A","P5", # PL46A
#         FuzzConfig(job="IC6A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R46C0:SYSIO_B6_0_C", "CIB_R47C0:SYSIO_B6_0_REM"])),
#     ("B","P6", # PL46B
#         FuzzConfig(job="IC6B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R46C0:SYSIO_B6_0_C", "CIB_R47C0:SYSIO_B6_0_REM"])),
#     ("A","E2", # PL15A
#         FuzzConfig(job="IO7A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R15C0:SYSIO_B7_0_ODD"])),
#     ("B","F1", # PL15B
#         FuzzConfig(job="IO7B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R15C0:SYSIO_B7_0_ODD"])),
#     ("A","D6", # PL6A
#         FuzzConfig(job="IO7AE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R6C0:SYSIO_B7_0_EVEN"])),
#     ("B","D5", # PL6B
#         FuzzConfig(job="IO7BE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R6C0:SYSIO_B7_0_EVEN"])),
#     ("A","K2", # PL19A
#         FuzzConfig(job="IC7A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R19C0:SYSIO_B7_0_C", "CIB_R20C0:SYSIO_B7_0_REM"])),
#     ("B","K1", # PL19B
#         FuzzConfig(job="IC7B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R19C0:SYSIO_B7_0_C", "CIB_R20C0:SYSIO_B7_0_REM"])),
#     ("A","E18", # PT84A
#         FuzzConfig(job="IO0A", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R0C84:SYSIO_B0_0_ODD"])),
#     ("B","D17", # PT84B
#         FuzzConfig(job="IO0B", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R0C84:SYSIO_B0_0_ODD"])),
#     ("A","E13", # PT78A
#         FuzzConfig(job="IO0AE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R0C78:SYSIO_B0_0_EVEN"])),
#     ("B","D13", # PT78B
#         FuzzConfig(job="IO0BE", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R0C78:SYSIO_B0_0_EVEN"])),
#     ("B","E17", # PR3A
#         FuzzConfig(job="IO1D", device="LIFCL-40", sv="../shared/empty_40.v", tiles=["CIB_R3C87:SYSIO_B1_DED"])),
# ]

def main(executor):
    def per_config(config):
        pio, site, cfg = config
        cfg.setup()
        empty = cfg.build_design(cfg.sv, {})
        cfg.sv = "iob.v"

        # if cfg.device == "LIFCL-17":
        #     cfg.sv = "iob_17.v"
        # elif cfg.device == "LIFCL-40":
        #     cfg.sv = "iob_40.v"

        (r,c) = tiles.get_rc_from_name(cfg.device, cfg.tiles[0])

        if f"R{r}C{c}_JPADDO_SEIO33_CORE_IO{pio}" not in tiles.get_full_node_set(cfg.device):
            logging.info(f"Skipping {site} {cfg.tiles[:3]}; no SEIO33 tile")
            return

        primtype = "SEIO33_CORE"

        suffix = ""

        def get_bank_vccio(iotype):
            if iotype == "":
                return "3.3"
            iov = iotype[-2:] if iotype[-1].isdigit() else iotype[-3:-1]
            if iov == "10":
                return "1.0"
            return "{}.{}".format(iov[0], iov[1])
        def get_substs(iotype="BIDIR_LVCMOS33", kv=None, vcc=None, tmux="T"):
            iodir, iostd = iotype.split("_", 2) if iotype != "NONE" else ("","")
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
            return dict(cmt="//" if iotype == "NONE" else "",
                pintype=pintype, primtype=primtype, site=site, iotype=iostd, t=t, extra_config=extra_config, vcc=vcc)
        seio_types = [
            "NONE",
        ]

        pullmodes = ["NONE", "UP", "DOWN", "KEEPER"]

        pullmodes += [ "I3C" ]

        seio_types += [
            "INPUT_LVCMOS12","OUTPUT_LVCMOS12","BIDIR_LVCMOS12",
            "INPUT_LVCMOS15", "OUTPUT_LVCMOS15", "BIDIR_LVCMOS15",
            "INPUT_LVCMOS25", "OUTPUT_LVCMOS25", "BIDIR_LVCMOS25",
            "OUTPUT_LVCMOS25D",

            "INPUT_LVCMOS33", "OUTPUT_LVCMOS33", "BIDIR_LVCMOS33",
            "INPUT_LVCMOS18", "OUTPUT_LVCMOS18", "BIDIR_LVCMOS18",
            "OUTPUT_LVCMOS33D"
        ]

        def fuzz_enum_setting(*args, **kwargs):
            nonrouting.fuzz_enum_setting(cfg, empty, executor = executor, *args, **kwargs)

        fuzz_enum_setting(f"PIO{pio}.BASE_TYPE", seio_types,
                                     lambda x: get_substs(iotype=x), False, assume_zero_base=True, mark_relative_to = cfg.tiles[0])

        input_mode = "INPUT_LVCMOS33"
        def iotype(v, out = False):
            return ("OUTPUT_" if out else "INPUT_") + "LVCMOS" + str(v).replace(".", "") + suffix

        if primtype == "SEIO33_CORE":
            fuzz_enum_setting(f"PIO{pio}.DRIVE_3V3", ["2", "4", "8", "12", "50RS"],
                                         lambda x: get_substs(iotype="OUTPUT_LVCMOS33", kv=("DRIVE", x)), True)

            fuzz_enum_setting("PIO{}.GLITCHFILTER".format(pio), ["OFF", "ON"],
                                         lambda x: get_substs(iotype=input_mode, kv=("GLITCHFILTER", x)), False)
            fuzz_enum_setting("PIO{}.DRIVE_2V5".format(pio), ["2", "4", "8", "10", "50RS"],
                                         lambda x: get_substs(iotype=iotype(2.5, True), kv=("DRIVE", x)), True)

            fuzz_enum_setting("PIO{}.HYSTERESIS_3V3".format(pio), ["ON", "OFF"],
                                         lambda x: get_substs(iotype=iotype(3.3), kv=("HYSTERESIS", x)), True)

            fuzz_enum_setting("PIO{}.HYSTERESIS_2V5".format(pio), ["ON", "OFF"],
                                         lambda x: get_substs(iotype=iotype(2.5), kv=("HYSTERESIS", x)), True)

            fuzz_enum_setting("PIO{}.UNDERDRIVE_3V3".format(pio), ["ON", "OFF"],
                                         lambda x: get_substs(iotype=iotype(3.3) if x=="OFF" else iotype(2.5), vcc="3.3"), True)

        fuzz_enum_setting("PIO{}.DRIVE_1V8".format(pio), ["2", "4", "8", "50RS"],
                        lambda x: get_substs(iotype=iotype(1.8, True), kv=("DRIVE", x)), True)
        fuzz_enum_setting("PIO{}.DRIVE_1V5".format(pio), ["2", "4", "8", "12"],
                        lambda x: get_substs(iotype=iotype(1.5, True), kv=("DRIVE", x)), True)
        fuzz_enum_setting("PIO{}.DRIVE_1V2".format(pio), ["2", "4", "8", "12"],
                        lambda x: get_substs(iotype=iotype(1.2, True), kv=("DRIVE", x)), True)

        fuzz_enum_setting("PIO{}.PULLMODE".format(pio), pullmodes,
                        lambda x: get_substs(iotype=input_mode, kv=("PULLMODE", x)), True)

        fuzz_enum_setting("PIO{}.HYSTERESIS_1V8".format(pio), ["ON", "OFF"],
                        lambda x: get_substs(iotype=iotype(1.8), kv=("HYSTERESIS", x)), True)
        fuzz_enum_setting("PIO{}.HYSTERESIS_1V5".format(pio), ["ON", "OFF"],
                        lambda x: get_substs(iotype=iotype(1.5), kv=("HYSTERESIS", x)), True)
        fuzz_enum_setting("PIO{}.HYSTERESIS_1V2".format(pio), ["ON", "OFF"],
                        lambda x: get_substs(iotype=iotype(1.2), kv=("HYSTERESIS", x)), True)
        fuzz_enum_setting("PIO{}.UNDERDRIVE_1V8".format(pio), ["ON", "OFF"],
                        lambda x: get_substs(iotype=iotype(1.8) if x=="OFF" else iotype(1.5), vcc="1.8"), True)

        fuzz_enum_setting("PIO{}.CLAMP".format(pio), ["OFF", "ON"],
                        lambda x: get_substs(iotype=input_mode, kv=("CLAMP", x)), True)

        fuzz_enum_setting("PIO{}.DFTDO2DI".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype=iotype(1.8), kv=("DFTDO2DI", x)), False)
        fuzz_enum_setting("PIO{}.LOOPBKCD2AB".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype=iotype(1.8), kv=("LOOPBKCD2AB", x)), False)
        fuzz_enum_setting("PIO{}.OPENDRAIN".format(pio), ["OFF", "ON"],
                        lambda x: get_substs(iotype=iotype(1.8, True), kv=("OPENDRAIN", x)), False)
        fuzz_enum_setting("PIO{}.SLEEPHIGHLEAKAGE".format(pio), ["DISABLED", "ENABLED"],
                        lambda x: get_substs(iotype=iotype(1.8), kv=("SLEEPHIGHLEAKAGE", x)), False)
        fuzz_enum_setting("PIO{}.SLEWRATE".format(pio), ["FAST", "MED", "SLOW"],
                        lambda x: get_substs(iotype=iotype(1.8, True), kv=("SLEWRATE", x)), False)

        fuzz_enum_setting("PIO{}.TERMINATION_1V8".format(pio), ["OFF", "40", "50", "60", "75", "150"],
                        lambda x: get_substs(iotype=iotype(1.8), kv=("TERMINATION", x)), False)
        fuzz_enum_setting("PIO{}.TERMINATION_1V5".format(pio), ["OFF", "40", "50", "60", "75"],
                        lambda x: get_substs(iotype=iotype(1.5), kv=("TERMINATION", x)), False)
        fuzz_enum_setting("PIO{}.TERMINATION_1V2".format(pio), ["OFF", "40", "50", "60", "75"],
                        lambda x: get_substs(iotype=iotype(1.2), kv=("TERMINATION", x)), False)

        fuzz_enum_setting("PIO{}.TMUX".format(pio), ["T", "INV"],
                        lambda x: get_substs(iotype=f"BIDIR_LVCMOS18{suffix}", tmux=x), False)

    def cfg_filter(config):
        pio, site, cfg = config
        if not should_fuzz_platform(cfg.device):
            return False

        if len(sys.argv) > 1 and sys.argv[1] not in  cfg.tiles[0]:
            return False

        if len(sys.argv) > 2 and sys.argv[2] != pio:
            return False

        return True

    for config in filter(cfg_filter, configs):
        per_config(config)

if __name__ == "__main__":
    fuzzloops.FuzzerMain(main)

