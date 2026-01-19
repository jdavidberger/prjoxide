"""
Utilities for fuzzing non-routing configuration. This is the counterpart to interconnect.py
"""
import threading
import tiles
import libpyprjoxide

import fuzzconfig
import fuzzloops
import os

from primitives import EnumSetting


def fuzz_word_setting(config, name, length, get_sv_substs, desc=""):
    """
    Fuzz a multi-bit setting, such as LUT initialisation

    :param config: FuzzConfig instance containing target device and tile of interest
    :param name: name of the setting to store in the database
    :param length: number of bits in the setting
    :param get_sv_substs: a callback function, that is called with an array of bits to create a design with that setting
    """
    if not fuzzconfig.should_fuzz_platform(config.device):
        return
    
    prefix = "thread{}_".format(threading.get_ident())
    baseline = config.build_design(config.sv, get_sv_substs([False for _ in range(length)]), prefix)
    fz = libpyprjoxide.Fuzzer.word_fuzzer(fuzzconfig.db, baseline, set(config.tiles), name, desc, length, baseline)
    for i in range(length):
        i_bit = config.build_design(config.sv, get_sv_substs([(_ == i) for _ in range(length)]), prefix)
        fz.add_word_sample(fuzzconfig.db, i, i_bit)

    config.solve(fz)

def fuzz_enum_setting(config, empty_bitfile, name, values, get_sv_substs, include_zeros=True,
                      assume_zero_base=False, min_cover={}, desc="", mark_relative_to=None):
    """
    Fuzz a setting with multiple possible values

    :param config: FuzzConfig instance containing target device and tile of interest
    :param empty_bitfile: a baseline empty bitstream to diff against
    :param name: name of the setting to store in the database
    :param values: list of values taken by the enum
    :param get_sv_substs: a callback function, 
    :param include_zeros: if set, bits set to zero are not included in db. Needed for settings such as CEMUX which share
    bits with routing muxes to prevent conflicts.
    :param assume_zero_base: if set, the baseline bitstream is considered the all-zero bitstream
    :param min_cover: for each setting in this, run with each value in the array that setting points to, to get a minimal
    bit set
    """
    if not fuzzconfig.should_fuzz_platform(config.device):
        return

    if config.check_deltas(name):
        return

    prefix = "thread{}_{}_{}_{}_".format(threading.get_ident(), config.job, config.device, name)
    try:
        fz = libpyprjoxide.Fuzzer.enum_fuzzer(fuzzconfig.db, empty_bitfile, set(config.tiles), name, desc, include_zeros, assume_zero_base, mark_relative_to = mark_relative_to)
    except:
        print(f"ERROR: from {empty_bitfile}")
        raise

    for opt in values:
        opt_name = opt
        if opt == "#SIG" and name.endswith("MUX"):
            opt_name = name[:-3].split(".")[1]
        if opt == "#INV":
            opt_name = "INV"
            
        if opt in min_cover:
            for c in min_cover[opt]:
                opt_bit = config.build_design(config.sv, get_sv_substs((opt, c)), prefix)
                fz.add_enum_sample(fuzzconfig.db, opt_name, opt_bit)
        else:
            opt_bit = config.build_design(config.sv, get_sv_substs(opt), "{}{}_".format(prefix, opt))
            fz.add_enum_sample(fuzzconfig.db, opt_name, opt_bit)

    config.solve(fz)

def fuzz_ip_word_setting(config, name, length, get_sv_substs, desc="", default=None):
    """
    Fuzz a multi-bit IP setting with an optimum number of bitstreams

    :param config: FuzzConfig instance containing target device and tile of interest
    :param name: name of the setting to store in the database
    :param length: number of bits in the setting
    :param get_sv_substs: a callback function, that is called with an array of bits to create a design with that setting
    """
    if not fuzzconfig.should_fuzz_platform(config.device):
        return

    prefix = "thread{}_".format(threading.get_ident())

    inverted_mode = False
    if default is not None:
        for i in range(0, length.bit_length()):
            bits = [(j >> i) & 0x1 == 0 for j in range(length)]
            if default == bits:
                inverted_mode = True
                break

    baseline = config.build_design(config.sv, get_sv_substs([inverted_mode for _ in range(length)]), prefix)
    ipcore, iptype = config.tiles[0].split(":")
    fz = libpyprjoxide.IPFuzzer.word_fuzzer(fuzzconfig.db, baseline, ipcore, iptype, name, desc, length, inverted_mode)
    for i in range(0, length.bit_length()):
        bits = [(j >> i) & 0x1 == (1 if inverted_mode else 0) for j in range(length)]
        i_bit = config.build_design(config.sv, get_sv_substs(bits), prefix)
        fz.add_word_sample(fuzzconfig.db, bits, i_bit)

    config.solve(fz)

def fuzz_ip_enum_setting(config, empty_bitfile, name, values, get_sv_substs, desc=""):
    """
    Fuzz a multi-bit IP enum with an optimum number of bitstreams

    :param config: FuzzConfig instance containing target device and tile of interest
    :param empty_bitfile: a baseline empty bitstream to diff against
    :param name: name of the setting to store in the database
    :param values: list of values taken by the enum
    :param get_sv_substs: a callback function, 
    """
    if not fuzzconfig.should_fuzz_platform(config.device):
        return
    
    prefix = "thread{}_".format(threading.get_ident())
    ipcore, iptype = config.tiles[0].split(":")
    fz = libpyprjoxide.IPFuzzer.enum_fuzzer(fuzzconfig.db, empty_bitfile, ipcore, iptype, name, desc)
    for opt in values:
        opt_bit = config.build_design(config.sv, get_sv_substs(opt), prefix)
        fz.add_enum_sample(fuzzconfig.db, opt, opt_bit)

    config.solve(fz)


def fuzz_primitive_definition(cfg, empty, site, primitive, mark_relative_to = None, mode_name = None, get_substs=None):
    def default_get_substs(mode="NONE", kv=None):
        if kv is None:
            config = ""
        else:
            key = kv[0]
            if key.endswith("MUX"):
                key = ":" + key[:-3]
            config = f"{mode}:::{key}={kv[1]}"
        return dict(cmt="//" if mode == "NONE" else "",
                    config=config,
                    site=site)
    if get_substs is None:
        get_substs = default_get_substs

    if mode_name is None:
        mode_name = primitive.name

    for setting in primitive.settings:
        subs_fn = lambda x, name=setting.name: get_substs(mode=mode_name, kv=(name, x))
        if setting.name == "MODE":
            subs_fn = lambda x: get_substs(mode=x)

        if isinstance(setting, EnumSetting):
            fuzz_enum_setting(cfg, empty, f"{mode_name}.{setting.name}", setting.values, subs_fn,False,
            desc=setting.desc, mark_relative_to=mark_relative_to)


