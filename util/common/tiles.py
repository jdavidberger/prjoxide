import itertools
import random
import re
from collections.abc import Iterable

import database
from collections import defaultdict
import lapie

import cachecontrol

pos_re = re.compile(r'R(\d+)C(\d+)')


def pos_from_name(tile):
    """
    Extract the tile position as a (row, column) tuple from its name
    """
    s = pos_re.search(tile)
    assert s
    return int(s.group(1)), int(s.group(2))

def type_from_fullname(tile):
    """
    Extract the type from a full tile name (in name:type) format
    """
    return tile.split(":")[1]

def get_rc_from_edge(device, side, offset):
    devices = database.get_devices()
    device_info = devices["families"][device.split("-")[0]]["devices"][device]

    max_row = device_info["max_row"]
    max_col = device_info["max_col"]

    if side == "T":
        return (0, int(offset))
    elif side == "B":
        return (int(max_row), int(offset))
    elif side == "R":
        return (int(offset), int(max_col))
    elif side == "L":
        return (int(offset), 0)
    
    assert False, f"Could not match IO with side as side {side} offset {offset}"

def get_tiles_from_edge(device, side, offset = -1):
    (r, c) = get_rc_from_edge(device, side, offset)
    tg = database.get_tilegrid(device)["tiles"]

    return [t for t, tinfo in tg.items() if (c == -1 or tinfo["x"] == c) and (r == -1 or tinfo["y"] == r)]

def get_sites_from_primitive(device, primitive):
    sites = database.get_sites(device)    
    return {k:s for (k,s) in sites.items() if s['type'] == primitive}


def get_tiletypes(device):
    tilegrid = database.get_tilegrid(device)['tiles']
    tiletypes = defaultdict(list)
    for (k,v) in tilegrid.items():
        tiletypes[k.split(":")[-1]].append(k)
    return tiletypes

def get_tiles_by_filter(device, fn):
    tilegrid = database.get_tilegrid(device)['tiles']

    return {k:v for k,v in tilegrid.items() if fn(k, v)}
    

def get_tiles_by_tiletype(device, tiletype):
    tilegrid = database.get_tilegrid(device)['tiles']

    return {k:v for k,v in tilegrid.items() if k.split(":")[-1] == tiletype}

def get_tiles_by_primitive(device, primitive):
    tilegrid = database.get_tilegrid(device)['tiles']
    
    rc_regex = re.compile("R([0-9]*)C([0-9]*)")
    edge_regex = re.compile("IOL_(.)([0-9]*)")    
    sites = get_sites_from_primitive(device, primitive)

    tg_by_rc = { (t['y'], t['x']):(k, t) for (k, t) in tilegrid.items() }

    rcs = {}
    for (a,v) in sites.items():
        rc = get_rc_from_name(device, a)

        (name, t) = tg_by_rc[rc]
        rcs[(a,name)] = t

    return rcs

def get_tiletypes_by_primitive(device, primitive):
    tiles = get_tiles_by_primitive(device, primitive)

    rtn = defaultdict(list)
    for ((site,tilename),v) in tiles.items():
        tiletype = tilename.split(":")[1]
        rtn[tiletype].append((site, tilename, v))
    return rtn

def get_sites_for_tile(device, tile):
    tilegrid = database.get_tilegrid(device)['tiles']
    tile = [v for (k,v) in tilegrid.items() if k.startswith(tile) ][0]

    sites = database.get_sites(device)

    RC = (tile["y"], tile["x"])
    
    return {k:v for k,v in sites.items() if RC == get_rc_from_name(device, k)}

_node_list_lookup = {}
_node_owned_lookup = {}

_spine_regex = re.compile("(.)([0-9][0-9])(.)([0-9][0-9])([0-9][0-9])")

_full_node_set = {}
def get_full_node_set(device):
    if device not in _full_node_set:
        all_nodes = lapie.get_full_node_list(device)
        _full_node_set[device] = sorted(list(set([n for n in all_nodes if len(n)])))
    return _full_node_set[device]


def get_node_list_for_tile(device, tile, owned = False):
    if device not in _node_list_lookup:
        all_nodes = lapie.get_full_node_list(device)
        _node_list_lookup[device] = defaultdict(list)
        _node_owned_lookup[device] = defaultdict(list)
        for name in all_nodes:
            rc = get_rc_from_name(device, name)

            if rc is None:
                continue
            elif rc[0] < 0 or rc[1] < 0:
                print(f"Nodename {name} has negative rc: {rc}")
            name_no_rc = "_".join(name.split("_")[1:])
            m = _spine_regex.match(name_no_rc)
            if m is not None:
                (r, c) = rc
                orientation = m.group(1)
                size = int(m.group(2))
                direction = m.group(3)
                track = int(m.group(4))
                segment = int(m.group(5))

                if size == 0:
                    continue

                assert (orientation in ["H", "V"])
                assert (direction in ["N", "E", "W", "S"])

                (dir_x, dir_y) = (0, 0)
                if direction == "N":
                    dir_y = -1
                elif direction == "S":
                    dir_y = 1
                elif direction == "E":
                    dir_x = 1
                else:
                    dir_x = -1

                rs = r - dir_y * segment
                cs = c - dir_x * segment

                for i in range(0, size + 1):
                    ro = rs + dir_y * i
                    co = cs + dir_x * i
                    alias_name = f"R{ro}C{co}{orientation}{size:02}{direction}{track:02}{i:02}"
                    # _node_list_lookup[device][ro, co].append(name)
                    if i == 0:
                        _node_owned_lookup[device][rc].append(name)
            else:
                _node_list_lookup[device][rc].append(name)
                _node_owned_lookup[device][rc].append(name)

    def _get_node_list_for_tile(t):
        return (_node_owned_lookup if owned else _node_list_lookup)[device].get(get_rc_from_name(device, t), [])

    if isinstance(tile, list):
        return {n:t for t in tile for n in _get_node_list_for_tile(t)}
    else:
        return _get_node_list_for_tile(tile)

def get_nodes_for_tile(device, tile, owned = False):
    if isinstance(tile, list):
        nodes2tile = {n:t for t in tile for n in get_node_list_for_tile(device, t, owned)}
        node_info = {n.name:n for n in lapie.get_node_data(device, list(nodes2tile.keys()), False)}

        tile_nodes = defaultdict(dict)
        for n, ninfo in node_info.items():
            tile_nodes[nodes2tile[n]][n.name] = ninfo        
        
        return tile_nodes
    else:
        tile_nodes = get_node_list_for_tile(device, tile, owned)
        if len(tile_nodes) == 0:
            return {}
    
        return {n.name:n for n in lapie.get_node_data(device, tile_nodes, False)}

_get_tiles_by_rc = {}
def get_tiles_by_rc(device, rc = None):
    if isinstance(rc, str):
        rc = get_rc_from_name(device, rc)

    if device not in _get_tiles_by_rc:
        tilegrid = database.get_tilegrid(device)['tiles']
        _get_tiles_by_rc[device] = defaultdict(dict)
        for k,v in tilegrid.items():
            nrc = (v['y'], v['x'])
            _get_tiles_by_rc[device][nrc][k] = v

    return _get_tiles_by_rc[device][rc]



def get_tile_routes(device, tilename, owned = False):
    node_data = get_nodes_for_tile(device, tilename, owned = owned)

    return node_data

rc_regex = re.compile("R([0-9]+)C([0-9]+)")
edge_regex = re.compile("IOL_(.)([0-9]+)")
def get_rc_from_name(device, name):
    if isinstance(name, tuple):
        return name
    
    m = rc_regex.search(name)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    m = edge_regex.search(name)
    if m:
        return get_rc_from_edge(device, m.group(1), m.group(2))
    
    return None

def get_tile_from_node(device, node):
    rc = get_rc_from_name(device, node)
    tilegrid = database.get_tilegrid(device)['tiles']

    for k,v in tilegrid.items():
        if (v['y'], v['x']) == rc:
            return k

def get_connected_nodes(device, tilename):
    routes = get_tile_routes(device, tilename)

    def tile_route(route):    
        return list(set([
            wire
            for (n,r) in route.items()
            for p in r.pips()
            for wire in [p.from_wire, p.to_wire]
        ]))
        
    
    if isinstance(tilename, list):
        return {t:tile_route(route) for t,route in routes.items()}

    print(routes)
    return tile_route(routes)
        

def get_pins_for_site(device, site):
    sites = database.get_sites(device)
    site_info = sites[site]

    nodes = {n.name:n for n in lapie.get_node_data(device, [p['pin_node'] for p in site_info['pins']])}

    return [(p, nodes[p['pin_node']]) for p in site_info['pins']]
    
def get_pips_for_tile(device, tilename, owned = False, dir = None):
    assert(dir is None or dir == "uphill" or dir == "downhill")

    def pips(r):
        if dir is None:
            return r.pips()
        elif dir == "uphill":
            return r.uphill_pips
        elif dir == "downhill":
            return r.downhill_pips
    
    routes = get_tile_routes(device, tilename, owned = owned)
    return list(set([
        (p.from_wire,
         p.to_wire)
        for (n,r) in routes.items()
        for p in pips(r)
    ]))

def get_connected_tiles(device, tilename):    
    connected_nodes = get_connected_nodes(device, tilename)
    
    tilegrid = database.get_tilegrid(device)['tiles']
    
    rcs = set([get_rc_from_name(device, n) for n in connected_nodes])
    
    return { k:v for k,v in tilegrid.items() if (v['y'], v['x']) in rcs  }

def draw_rc(rcs):
    rcs = set(rcs)
    for y in range(0, 55):
        for x in range(0, 83):
            print("■" if (x,y) in rcs else " " , end='')
        print()

def get_wires_for_tiles(device):
    anon_nodes = defaultdict(lambda : defaultdict(list))
    for n in get_full_node_set(device):
        wire_name = "_".join(n.split("_")[1:])
        rc = get_rc_from_name(device, n)
        for tile in sorted(get_tiles_by_rc(device, rc)):
            tiletype = tile.split(":")[-1]
            anon_nodes[tiletype][wire_name].append(tile)

    return anon_nodes

def get_wires_for_sites(device):
    anon_nodes = defaultdict(lambda : defaultdict(list))
    sites = database.get_sites(device)

    for site, site_info in sites.items():
        pins = site_info['pins']
        pin_nodes = [p["pin_node"] for p in pins]

        for n in pin_nodes:
            wire_name = "_".join(n.split("_")[1:])
            rc = get_rc_from_name(device, n)

            anon_nodes[site_info["type"]][wire_name].append(site)
    return anon_nodes

def get_representative_nodes_data(device, seed = 42, exclude_set = []):
    rep_nodes = get_wires_for_tiles(device)
    nodes = []
    random.seed(42)

    lookup = {}
    for tiletype, wire_dict in sorted(rep_nodes.items()):
        if tiletype not in exclude_set:
            for wire, tiles in sorted(wire_dict.items()):
                tile = random.choice(tiles)
                (r,c) = get_rc_from_name(device, tile)
                wire_name = f"R{r}C{c}_{wire}"
                nodes.append(f"R{r}C{c}_{wire}")
                lookup[wire_name] = (tiletype, wire, tile)

    nodes = sorted(nodes)

    batches = list(itertools.batched(nodes, 5000))
    batch_returns = [None] * len(batches)

    def f(idx_batch):
        (idx, batch) = idx_batch
        batch_returns[idx] = lapie.get_node_data(device, list(batch))

    import fuzzloops
    fuzzloops.parallel_foreach(enumerate(batches), f, jobs=len(batches))

    node_data = {a:v
                 for d in batch_returns
                 for v in d
                 for a in v.aliases}

    rtn = defaultdict(list)
    for wire_name, lu in lookup.items():
        rtn[lu[0]].append((lu[2], node_data[wire_name]))

    return rtn

def get_node_data_local_graph(device, node, should_expand = None):
    if isinstance(node, Iterable):
        node = list(node)

    if not isinstance(node, list):
        node = [node]

    rc = get_rc_from_name(device, node[0])
    def def_should_expand(node):
        return rc == get_rc_from_name(device, node)

    if should_expand is None:
        should_expand = def_should_expand

    query_list = node

    graph = {}
    while len(query_list) > 0:
        new_nodes = lapie.get_node_data(device, query_list)
        #new_nodes = [k for k in lapie.get_list_arc(device)
        query_list = []

        for n in new_nodes:
            graph[n.name] = n

            for p in n.pips():
                for wire in [p.to_wire, p.from_wire]:
                    if wire not in graph and should_expand(wire):
                        query_list.append(wire)
    return graph

def get_local_pips_for_site(device, site, include_interface_pips = True):
    if isinstance(site, str):
        sites = database.get_sites(device)
        site = sites[site]

    site_nodes = [p["pin_node"] for p in site["pins"]]

    return get_local_pips_for_nodes(device, site_nodes,
                                    include_interface_pips = include_interface_pips,
                                    should_expand = lambda x: site["type"] in x)

def get_local_pips_for_nodes(device, nodes, should_expand = None, include_interface_pips = True, executor = None):
    if executor is not None:
        return executor.submit(get_local_pips_for_nodes, device, nodes, should_expand = should_expand ,include_interface_pips = include_interface_pips)

    local_graph = get_node_data_local_graph(device, nodes, should_expand = should_expand)

    def should_include(p):
        if include_interface_pips:
            return p.from_wire in local_graph or p.to_wire in local_graph
        else:
            return p.from_wire in local_graph and p.to_wire in local_graph

    pips = [(p.from_wire, p.to_wire) for n, info, in local_graph.items() for p in info.pips() if
            should_include(p)]

    return sorted(set(pips)), local_graph

def get_representative_nodes_for_tiletype(device, tiletype):
    node_set = None

    for tile in get_tiles_by_tiletype(device, tiletype):
        nodes = set(["_".join(n.split("_")[1:]) for n in get_node_list_for_tile(device, tile)])
        if node_set is None:
            node_set = nodes
        else:
            node_set = node_set & nodes
    if node_set is None:
        return set()

    return node_set

def get_outlier_nodes_for_tiletype(device, tiletype):
    repr_nodes = get_representative_nodes_for_tiletype(device, tiletype)

    outliers = {}
    for tile in get_tiles_by_tiletype(device, tiletype):
        nodes = set(["_".join(n.split("_")[1:]) for n in get_node_list_for_tile(device, tile)])

        node_outliers = nodes - repr_nodes

        if len(node_outliers) > 0:
            outliers[tile] = node_outliers

    return outliers

@cachecontrol.cache_fn()
def get_connections_for_device(device):
    arcs = lapie.get_jump_wires(device)

    connections = defaultdict(set)
    for frm, to in arcs:
        connections[frm].add(to)

    return connections

def find_path(device, frm, to):
    nodes = lapie.get_node_data(device, [frm])

    edges = {}
    visited = set()
    found = False
    while not found:
        query = set()
        for n in nodes:
            for p in n.uphill_pips:
                if p.to_wire == to:
                    found = True
                    break

                if p.to_wire not in visited:
                    edges[p.to_wire] = n
                    visited.add(p.to_wire)
                    query.add(p.to_wire)
        nodes = lapie.get_node_data(device, query)

    path = []
    c = to
    while c != frm:
        path.append(c)
        c = edges[c]
    return path