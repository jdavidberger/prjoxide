"""
Python wrapper for `lapie`
"""
import logging
import sys
from os import path
import os
import subprocess
import database
import tempfile
import re
import hashlib
import shutil
import fuzzconfig

# `lapie` seems to be renamed every version or so. Map that out here. Most installations will have
# the version name at the end of their path, so we just look at the radiant dir for a hint. The user
# can override this setting with a RADIANTVERSION env variable
known_versions = [ "2.2", "3.1", "2023", "2024", "2025" ]
RADIANT_DIR = os.environ.get("RADIANTDIR")
radiant_version= os.environ.get("RADIANTVERSION", None)
get_nodes = "dev_get_nodes"
    
if radiant_version is None:
    for version in known_versions:
        if RADIANT_DIR.find(version) > -1:
            radiant_version = version

if radiant_version is None:
    radiant_version = "3.1"

if radiant_version == "2023":
    tcltool = "lark"
    tcltool_log = "radiantc.log"
    dev_enable_name = "RAT_DEV_ENABLE"
elif radiant_version == "2025" or radiant_version == "2024":
    # For whatever reason; these versions of the tool have a dependency on libqt 3 so finding a way to run it
    # might be challenging; even in a container environment. Included here for completeness; recommend running 2023
    # for tasks requiring this instead.
    tcltool = "labrus"
    tcltool_log = "radiantc.log"
    dev_enable_name = "RAT_DEV_ENABLE"    
else:
    tcltool = "lapie"
    tcltool_log = "lapie.log"
    dev_enable_name = "LATCL_DEV_ENABLE"    
    get_nodes = "get_nodes"
    
def run(commands, workdir=None, stdout=None):
    from radiant import run_bash_script

    """Run a list of Tcl commands, returning the output as a string"""
    rcmd_path = path.join(database.get_oxide_root(), "radiant_cmd.sh")
    if workdir is None:
        workdir = tempfile.mkdtemp()
    scriptfile = path.join(workdir, "script.tcl")
    with open(scriptfile, 'w') as f:
        for c in commands:
            f.write(c + '\n')
    env = os.environ.copy()
    env[dev_enable_name] = "1"

    result_struct = run_bash_script(env, rcmd_path, tcltool, scriptfile, cwd=workdir, stdout=stdout)

    result = result_struct.returncode

    outfile = path.join(workdir, tcltool_log)
    output = ""
    with open(outfile, 'r') as f:
        for line in f:
            if line.startswith("WARNING - "):
                continue
            output += line
    # Strip Lattice header
    delimiter = "-" * 80
    output = output[output.rindex(delimiter)+81:].strip()
    # Strip Lattice pleasantry
    pleasantry = "Thank you for using"
    output = output[:output.find(pleasantry)].strip()
    return output

def run_with_udb(udb, commands, stdout = None):
    return run(['des_read_udb "{}"'.format(path.abspath(udb))] + commands, stdout = stdout)

class PipInfo:
    def __init__(self, from_wire, to_wire, is_bidi = False, flags = 0, buffertype = ""):
        self.from_wire = from_wire
        self.to_wire = to_wire
        self.flags = flags
        self.buffertype = buffertype
        self.is_bidi = is_bidi
       
    def __repr__(self):
        return str((self.from_wire, self.to_wire, self.flags, self.buffertype, self.is_bidi))

class PinInfo:
    def __init__(self, site, pin, wire, pindir):
        self.site = site
        self.pin = pin
        self.wire = wire
        self.dir = pindir

class NodeInfo:
    def __init__(self, name):
        self.name = name
        self.aliases = []
        self.nodetype = None
        self.uphill_pips = []
        self.downhill_pips = []
        self.pins = []
        
    def pips(self):
        return self.uphill_pips + self.downhill_pips
        
node_re = re.compile(r'^\[\s*\d+\]\s*([A-Z0-9a-z_]+)')
alias_node_re = re.compile(r'^\s*Alias name = ([A-Z0-9a-z_]+)')
pip_re = re.compile(r'^([A-Z0-9a-z_]+) (<--|<->|-->) ([A-Z0-9a-z_]+) \(Flags: .+, (\d+)\) \(Buffer: ([A-Z0-9a-z_]+)\)')
#R1C77_JLFTRMFAB7_OSC_CORE <-- R1C75_JCIBMUXOUTA7 (Flags: ----j, 0) (Buffer: b_ciboutbuf)
pin_re = re.compile(r'^Pin  : ([A-Z0-9a-z_]+)/([A-Z0-9a-z_]+) \(([A-Z0-9a-z_]+)\)')

# Parsing is weird here since the format of the report can vary somewhat.
# Pre 2023; there were no aliases listed and the nodes returned were numbered. Post 2023, each node
# can have a lot of aliases and the only clear indication of which name is normative is its the one
# used in the connections.

def parse_node_report(rpt):    
    curr_node = None
    nodes_dict = {}
    nodes = []
    reset_curr_node = True
    
    def get_node(name):
        if name in nodes_dict:
            n = nodes_dict[name]
            n.name = name
            return n

        nodes_dict[name] = NodeInfo(name)
        nodes.append(nodes_dict[name])
        return nodes_dict[name]
        
    for line in rpt.split('\n'):
        sl = line.strip()

        name_match = [nm.group(1) for nm in [re.match(sl) for re in [node_re, alias_node_re]] if nm is not None]

        if len(name_match):
            new_name = name_match[0]
            if reset_curr_node:
                curr_node = get_node(new_name)
                reset_curr_node = False
            curr_node.aliases.append(new_name)
            continue

        # If we get back into an alias section, we are onto a new node
        reset_curr_node = True
        
        pm = pip_re.match(sl)
        if pm:
            # Name the node according to what things call it
            curr_node.name = pm.group(1)
            
            flg = int(pm.group(4))
            btyp = pm.group(5)
            #print(f"Found connection {pm}")
            if pm.group(2) == "<--":
                curr_node.uphill_pips.append(
                    PipInfo(pm.group(3), pm.group(1), False, flg, btyp)
                )
            elif pm.group(2) == "<->":
                curr_node.uphill_pips.append(
                    PipInfo(pm.group(3), pm.group(1), True, flg, btyp)
                )
                curr_node.downhill_pips.append(
                    PipInfo(pm.group(1), pm.group(3), True, flg, btyp)
                )
            elif pm.group(2) == "-->":
                curr_node.downhill_pips.append(
                    PipInfo(pm.group(1), pm.group(3), False, flg, btyp)
                )
            else:
                assert False
            continue
        qm = pin_re.match(sl)
        #print("Match", qm, curr_node)
        if qm and curr_node:
            curr_node.pins.append(
                PinInfo(qm.group(1), qm.group(2), curr_node.name, qm.group(3))
            )
    #print([x.name for x in nodes])
    return nodes

def parse_sites(rpt):
    past_preamble = False
    sites = []
    for line in rpt.split('\n'):
        sl = line.strip()

        if not past_preamble:
            past_preamble = "Successfully loading udb" in sl
            continue

        if "--------------------" in sl:
            break

        if len(sl):
            sites.append(sl)

    return sites

def get_full_node_list(udb):
    workdir = f"/tmp/prjoxide_node_data/{udb}"
    nodefile = path.join(workdir, "full_nodes.txt")
    os.makedirs(workdir, exist_ok=True)
    
    if not os.path.exists(nodefile):
        if not udb.endswith(".udb"):
            config = fuzzconfig.FuzzConfig(udb, "extract-site-info", [])
            config.setup()
            udb = config.udb
        run_with_udb(udb, [f'dev_list_node_by_name -file {nodefile}'])
    with open(nodefile, 'r') as nf:
        return [line.split(":")[-1].strip() for line in nf.read().split("\n")]

def get_node_data(udb, nodes, regex=False):
    workdir = tempfile.mkdtemp()
    nodefile = path.join(workdir, "nodes.txt")
    nodelist = ""
    
    if not isinstance(nodes, list):
        nodelist = nodes
        nodes = [nodes]        
    elif len(nodes) == 1:
        nodelist = nodes[0]
    elif len(nodes) > 1:
        nodes = sorted(set(nodes))
        nodelist = "[list {}]".format(" ".join(nodes))

    logging.info(f"Querying for {len(nodes)} nodes {nodes[:10]}")
    key_input = "\n".join([radiant_version, udb, f"regex: {regex}", ''] + nodes)
    key = hashlib.md5(key_input.encode('utf-8')).hexdigest()
    key_path = f"/tmp/prjoxide_node_data/{key}"
    os.makedirs("/tmp/prjoxide_node_data", exist_ok=True)
    
    if os.path.exists(key_path):
        #print(f"Nodefile found at {key_path}")        
        shutil.copyfile(key_path, nodefile)            
    else:
        if not udb.endswith(".udb"):
            device = udb
            udb = f"/tmp/prjoxide_node_data/{device}.udb"
            if not os.path.exists(udb):
                config = fuzzconfig.FuzzConfig(device, f"extract-site-info-{device}", [])
                config.setup()
                shutil.copyfile(config.udb, udb)
        
        re_slug = "-re " if regex else ""
        run_with_udb(udb, [f'dev_report_node -file {nodefile} [{get_nodes} {re_slug}{nodelist}]'], stdout = subprocess.DEVNULL)
        shutil.copyfile(nodefile, key_path)
        with open(key_path + ".input", 'w') as f:
            f.write(key_input)
        #print(f"Nodefile cached at {key_path}")        
        
    with open(nodefile, 'r') as nf:
        return parse_node_report(nf.read())

def get_sites(udb, rc = None):
    if not udb.endswith(".udb"):
        config = fuzzconfig.FuzzConfig(udb, "extract-site-info", [])
        config.setup()
        udb = config.udb

    rc_slug = ""
    if rc is not None:
        rc_slug = f"-row {rc[0]} -column {rc[1]}"
    rpt = run_with_udb(udb, [f'dev_list_site {rc_slug}'], stdout = subprocess.DEVNULL)

    return parse_sites(rpt)

def parse_report_site(rpt):
    site_re = re.compile(
        r'^Site=(?P<site_name>\S+)\s+'
        r'id=(?P<id>\d+)\s+'
        r'type=(?P<type>\S+)\s+'
        r'X=(?P<x>-?\d+)\s+'
        r'Y=(?P<y>-?\d+)$'
    )

    pin_re = re.compile(
        r'^\s*Pin\s+id\s*=\s*(?P<pin_id>\d+)\s+'
        r'pin\s+name\s*=\s*(?P<pin_name>\S+)\s+'
        r'pin\s+node\s+name\s*=\s*(?P<pin_node>\S+)$'
    )
    
    past_preamble = False
    sites = {}
    current_site = None
    
    for line in rpt.split('\n'):
        sl = line.strip()

        if not past_preamble:
            past_preamble = "Successfully loading udb" in sl
            continue

        if "--------------------" in sl:
            break

        m = site_re.match(line)
        if m:
            current_site = m.groupdict()
            current_site["pins"] = []
            sites[current_site["site_name"]] = current_site
            del current_site["site_name"]
            
        m = pin_re.match(line)
        if m:
            pins = m.groupdict()
            del pins["pin_id"]
            current_site["pins"].append(pins)

    return sites

def get_sites_with_pin(udb, rc = None):
    if not udb.endswith(".udb"):
        config = fuzzconfig.FuzzConfig(udb, "extract-site-info", [])
        config.setup()
        udb = config.udb
        
    rc_slug = ""
    if rc is not None:
        rc_slug = f"-row {rc[0]} -column {rc[1]}"
    rpt = run_with_udb(udb, [f'dev_report_site {rc_slug}'])

    return parse_report_site(rpt)


def list_nets(udb):
    # des_list_net no longer works?
    output = run_with_udb(udb, ['des_report_instance'])
    net_list = set()

    for line in output.split('\n'):
        net_re = re.compile(r'.*sig=([A-Za-z0-9_\[\]()./]+).*')
        m = net_re.match(line)
        if m:
            if m.group(1) == "n/a":
                continue
            net_list.add(m.group(1))
    return list(sorted(net_list))


class NetPin:
    def __init__(self, cell, pin, node):
        self.cell = cell
        self.pin = pin
        self.node = node

class NetPip:
    def __init__(self, node1, node2, is_dir):
        self.node1 = node1
        self.node2 = node2
        self.is_dir = is_dir

class NetRouting:
    def __init__(self):
        self.pins = []
        self.pips = []

def get_routing(udb, nets):
    output = run_with_udb(udb, ['des_report_net {{{}}}'.format(n) for n in nets])
    curr_routing = NetRouting()
    routing = {}
    name_re = re.compile(r'Name = ([^ ]*) id = \d+ power_type = \d+')
    pin_re = re.compile(r'comp= ([^ ]*) pin= ([^ ]*) node= ([^ ]*) subnet= \d+ num_x=\d+')
    pip_re = re.compile(r'node1= ([^ ]*) node2= ([^ ]*) subnet= \d+  type=\(\d+ -> \d+\)  dir=([A-Z])')

    for line in output.split('\n'):
        sl = line.strip()
        nm = name_re.match(sl)
        if nm:
            curr_net = nm.group(1)
            routing[curr_net] = curr_routing
            curr_routing = NetRouting()
            continue
        pm = pin_re.match(sl)
        if pm:
            curr_routing.pins.append(NetPin(pm.group(1), pm.group(2), pm.group(3)))
            continue
        pipm = pip_re.match(sl)
        if pipm:
            is_dir = pipm.group(3) == "D"
            curr_routing.pips.append(NetPip(pipm.group(1), pipm.group(2), is_dir))
    return routing
