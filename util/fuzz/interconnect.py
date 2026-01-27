"""
Utilities for fuzzing interconect
"""
import logging
import threading
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path

import tiles
import libpyprjoxide
import fuzzconfig
import fuzzloops
import lapie
import database
import os
import math
import tempfile
from os import path
import heapq
import bisect
import re

from collections import defaultdict

workdir = tempfile.mkdtemp()

def create_wires_file(config, wires, prefix = "", empty_version = False, executor = None):
    if empty_version:
        prefix = prefix + "_empty"
    if isinstance(wires, set):
        wires = sorted(wires)

    if isinstance(wires, list):
        
        touched_tiles = set([tiles.get_rc_from_name(config.device, n) for w in wires for n in w])
        
        slice_sites = tiles.get_tiles_by_tiletype(config.device, "PLC")
        slice_iter = iter([x for x in slice_sites if tiles.get_rc_from_name(config.device, x) not in touched_tiles])


        if empty_version:
            wires = "\n".join([f"""
wire q_{idx};            
(* \\dm:cellmodel_primitives ="REG0=reg", \\dm:primitive ="SLICE", \\dm:programming ="MODE:LOGIC Q0:Q0 ", \\dm:site ="{next(slice_iter).split(":")[0]}A" *) 
SLICE SLICE_I_{idx} ( .A0(q_{idx}), .Q0(q_{idx}) );
            """ for idx, (frm, to) in enumerate(sorted(wires))])            
        else:                
            wires = "\n".join([f"""
(*  keep = "true", dont_touch = "true", keep, dont_touch,\\xref:LOG ="q_c@0@0", \\dm:arcs ="{to}.{frm}" *)
wire q_{idx};

(* \\dm:cellmodel_primitives ="REG0=reg", \\dm:primitive ="SLICE", \\dm:programming ="MODE:LOGIC Q0:Q0 ", \\dm:site ="{next(slice_iter).split(":")[0]}A" *) 
SLICE SLICE_I_{idx} ( .A0(q_{idx}), .Q0(q_{idx}) );
        
            """ for idx, (frm, to) in enumerate(sorted(wires))])
    
    subst = config.subst_defaults()
    arch = config.device.split("-")[0]
    device = config.device
    package = subst["package"]
    speed_grade = subst["speed_grade"]
        
    source = f"""\
(* \\db:architecture ="{arch}", \\db:device ="{device}", \\db:package ="{package}", \\db:speed ="{speed_grade}_High-Performance_1.0V", \\db:timestamp = 0, \\db:view ="physical" *)
module top (
);
{wires}
    	(* \\xref:LOG ="q_c@0@0" *)
	VHI vhi_i();        
endmodule        
        """
    
    vfile = path.join(workdir, f"{prefix}{config.job}.v")
    Path(vfile).parent.mkdir(parents=True, exist_ok=True)

    with open(vfile, 'w') as f:
        f.write(source)

    if executor is not None:
        return config.build_design_future(executor, vfile, prefix=prefix)
    return config.build_design(vfile, prefix=prefix)

def pips_to_sinks(pips):
    sinks = {}

    for from_wire, to_wire in pips:
        if to_wire not in sinks:
            sinks[to_wire] = []
        sinks[to_wire].append(from_wire)

    for k in sinks:
        sinks[k] = sorted(sinks[k])

    return sinks

def collect_sinks(config, nodenames, regex = False,
                 nodename_predicate=lambda x, nets: True,
                 pip_predicate=lambda x, nets: True,
                 bidir=False,
                 nodename_filter_union=False,
                 ):
    if regex:
        all_nodes = lapie.get_full_node_list(config.device)
        regex = [re.compile(n) for n in nodenames]
        nodenames = [n for n in all_nodes if any([r for r in regex if r.search(n) is not None])]
        regex = False

    nodes = lapie.get_node_data(config.device, nodenames, regex)

    all_wirenames = set([n.name for n in nodes])
    all_pips = set()
    for node in nodes:
        for p in node.uphill_pips:
            all_pips.add((p.from_wire, p.to_wire))
        if bidir:
            for p in node.downhill_pips:
                all_pips.add((p.from_wire, p.to_wire))
    per_sink = list(sorted(all_pips))
    
    # First filter using netname predicate
    if nodename_filter_union:
        all_pips = filter(lambda x: nodename_predicate(x[0], all_wirenames) and nodename_predicate(x[1], all_wirenames),
                            all_pips)
    else:
        all_pips = filter(lambda x: nodename_predicate(x[0], all_wirenames) or nodename_predicate(x[1], all_wirenames),
                            all_pips)
    # Then filter using the pip predicate
    fuzz_pips = list(filter(lambda x: pip_predicate(x, all_wirenames), all_pips))
    if len(fuzz_pips) == 0:
        logging.warning(f"No fuzz_pips defined for job {config}. Nodes: {nodes} {all_pips}")
        return {}
    logging.debug(f"Fuzz pips {len(fuzz_pips)}")

    return pips_to_sinks(fuzz_pips)

def fuzz_interconnect_sinks(
        config,
        sinks,
        full_mux_style=False,
        ignore_tiles=set(),
        extra_substs={},
        fc_filter=lambda x: True,
        executor = None
    ):
    if sinks is None:
        return []


    if not isinstance(sinks, dict):
        sinks = pips_to_sinks(sinks)

    base_bitf_future = config.build_design_future(executor, config.sv, extra_substs, "base_")

    logging.info(f"Processing {len(sinks)} sinks for {sum([len(v) for k,v in sinks.items()])} designs for {config.job} {config.device}")

    assert(len(config.tiles) > 0)

    def process_bits(bitstreams, from_wires, to_wire):
        base_bitf = bitstreams[0]
        bitstreams = bitstreams[1:]
        db = fuzzconfig.get_db()

        fz = libpyprjoxide.Fuzzer.pip_fuzzer(db, base_bitf, set(config.tiles), to_wire,
                                             config.tiles[0],
                                             set(ignore_tiles), full_mux_style, not (fc_filter(to_wire)))

        for (from_wire, arc_bit) in zip(from_wires, bitstreams):
            fz.add_pip_sample(db, from_wire, arc_bit if arc_bit is not None else base_bitf)

        logging.debug(f"Solving for {to_wire}")
        config.solve(fz)

    conns = tiles.get_connections_for_device(config.device)

    futures = []
    with fuzzloops.Executor(executor) as executor:
        for to_wire in sinks:
            if config.check_deltas(to_wire):
                continue

            bitstream_futures = [base_bitf_future]
            for from_wire in sinks[to_wire]:
                arcs_attr = r', \dm:arcs ="{}.{}"'.format(to_wire, from_wire)
                substs = extra_substs.copy()
                substs["arcs_attr"] = arcs_attr

                arc_bit = None
                if to_wire in conns.get(from_wire, {}):
                    logging.debug(f"{from_wire} -> {to_wire} is in arc list; not building file")
                else:
                    logging.debug(f"Building design for ({config.job} {config.device}) {to_wire} to {from_wire}")
                    arc_bit = config.build_design_future(executor, config.sv, substs, f"{from_wire}/{to_wire}/")
                    futures.append(arc_bit)

                bitstream_futures.append(arc_bit)

            futures.append(fuzzloops.chain(bitstream_futures, "Interconnect sink", process_bits, sinks[to_wire], to_wire))

        return futures

def fuzz_interconnect(
        config,
        nodenames,
        regex=False,
        nodename_predicate=lambda x, nets: True,
        pip_predicate=lambda x, nets: True,
        bidir=False,
        nodename_filter_union=False,
        full_mux_style=False,
        ignore_tiles=set(),
        extra_substs={},
        fc_filter=lambda x: True,
        executor = None
    ):
    """
    Fuzz interconnect given a list of nodenames to analyse. Pips associated these nodenames will be found using the Tcl
    API and bits identified as described above.

    :param config: FuzzConfig instance containing target device and tile(s) of interest
    :param nodenames: A list of nodes or node regexes in Lattice (un-normalised) format to analyse
    :param regex: enable regex names
    :param nodename_predicate: a predicate function which should return True if a netname is of interest, given
    the netname and the set of all nets
    :param pip_predicate: a predicate function which should return True if an arc, given the arc as a (source, sink)
    tuple and the set of all nodenames, is of interest
    :param bidir: if True, pips driven by as well as driving the given nodenames will be considered during analysis
    :param nodename_filter_union: if True, pips will be included if either net passes nodename_predicate, if False both
    nets much pass the predicate.
    :param full_mux_style: if True, is a full mux, and all 0s is considered a valid config bit possibility
    on certain families.
    :param ignore_tiles: don't reject pips that touch these tils
	:param extra_substs: extra SV substitutions
    :param fc_filter: skip fixed connections if this returns false for a sink wire name
    """
    if not fuzzconfig.should_fuzz_platform(config.device):
        return []

    sinks = collect_sinks(config, nodenames, regex = regex,
                          nodename_predicate = nodename_predicate,
                          pip_predicate = pip_predicate,
                          bidir=bidir,
                          nodename_filter_union=False)

    return fuzz_interconnect_sinks(config, sinks, full_mux_style, ignore_tiles, extra_substs, fc_filter, executor=executor)

def fuzz_interconnect_for_tiletype(device, tiletype):
    prototype = list(tiles.get_tiles_by_tiletype(device, tiletype).keys())[0]

    nodes = tiles.get_connected_nodes(device, prototype)
    
    connected_tiles = tiles.get_connected_tiles(device, prototype)
    
    cfg = fuzzconfig.FuzzConfig(job=f"interconnect_{tiletype}", device=device, tiles=[prototype])    
    #fuzz_interconnect(config=cfg, nodenames=nodes, bidir=True)
    return collect_sinks(cfg, nodes, bidir=True)

def fuzz_interconnect_pins(config, site_name, extra_substs = {}, full_mux_style = False, fc_filter=lambda x: True):    
    pins = tiles.get_pins_for_site(config.device, site_name)

    family = config.device.split("-")[0]
    suffix = config.device.split("-")[1]    
    empty_sv = database.get_db_root() + f"/../fuzzers/{family}/shared/empty_{suffix}.v"
    base_bitf = config.build_design(empty_sv, extra_substs, "base_")
    
    def per_pip(pin_info, pin_pip):
        # Get a unique prefix from the thread ID

        print(pin_info, pin_pip)
        pin_name = pin_info['pin_name']
        to_wire = pin_pip.to_wire
        from_wire = pin_pip.from_wire
        is_output = pin_info['pin_node'] == pin_pip.from_wire
    
        prefix = "{}_{}_{}_".format(config.job, config.device, to_wire)
        db = fuzzconfig.get_db()
        fz = libpyprjoxide.Fuzzer.pip_fuzzer(db, base_bitf,
                                             set(config.tiles),
                                             to_wire,
                                             config.tiles[0], set(), full_mux_style, not (fc_filter(to_wire)))

        arcs_attr = r', \dm:arcs ="{}.{}"'.format(to_wire, from_wire)
        substs = extra_substs.copy()
        substs["pin_name"] = pin_name
        substs["target"] = ".A0(q)" if is_output else ".Q0(q),.A0(q)"
        substs["arcs_attr"] = arcs_attr
        
        print(f"Building design for ({config.job} {config.device}) {to_wire} to {from_wire}")            
        arc_bit = config.build_design(config.sv, substs, prefix)
        fz.add_pip_sample(db, from_wire, arc_bit)

        config.solve(fz)

    for p, pnode in pins:
        assert(len(pnode.pips()) == 1)        
        per_pip(p, pnode.pips()[0])

        
