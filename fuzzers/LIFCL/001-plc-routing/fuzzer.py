from fuzzconfig import FuzzConfig
from interconnect import fuzz_interconnect
import re
import tiles

def run_cfg(device):
    tile = list(tiles.get_tiles_by_tiletype(device, "PLC").keys())[0]
    (r,c) = tiles.get_rc_from_name(device, tile)

    cfg = FuzzConfig(job=f"PLCROUTE-{device}-{tile}", device=device, sv=f"../shared/route_{device.split('-')[-1]}.v", tiles=[tile])
    
    cfg.setup()

    nodes = ["R{}C{}_J.*".format(r, c)]
    extra_sources = []
    extra_sources += ["R{}C{}_H02E{:02}01".format(r, c+1, i) for i in range(8)]
    extra_sources += ["R{}C{}_H06E{:02}03".format(r, c+3, i) for i in range(4)]
    extra_sources += ["R{}C{}_V02N{:02}01".format(r-1, c, i) for i in range(8)]	
    extra_sources += ["R{}C{}_V06N{:02}03".format(r-3, c, i) for i in range(4)]	
    extra_sources += ["R{}C{}_V02S{:02}01".format(r+1, c, i) for i in range(8)]	
    extra_sources += ["R{}C{}_V06S{:02}03".format(r+3, c, i) for i in range(4)]	
    extra_sources += ["R{}C{}_H02W{:02}01".format(r, c-1, i) for i in range(8)]
    extra_sources += ["R{}C{}_H06W{:02}03".format(r, c-3, i) for i in range(4)]
    #nodes = [n.name for n in tiles.get_nodes_for_tile(cfg.device, tile)]
    #fuzz_interconnect(config=cfg, nodenames=nodes, regex=True, bidir=True)#, ignore_tiles=set(["TAP_PLC_R16C14:TAP_PLC"]))

    cfg.job = cfg.job + "-extra-srcs"
    fuzz_interconnect(config=cfg, nodenames=extra_sources, regex=True, bidir=False)#, ignore_tiles=set(["TAP_PLC_R16C14:TAP_PLC"]))

def main():
    run_cfg("LIFCL-40")
    
if __name__ == "__main__":
    main()
