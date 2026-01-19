import re
import database
from collections import defaultdict
import lapie

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
        _full_node_set[device] = set(all_nodes)
    return _full_node_set[device]


def get_nodes_for_tile(device, tile, owned = False):
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
                (r,c) = rc
                orientation = m.group(1)
                size = int(m.group(2))
                direction = m.group(3)
                track = int(m.group(4))
                segment = int(m.group(5))

                if size == 0:
                    continue
                
                assert(orientation in ["H", "V"])
                assert(direction in ["N","E","W","S"])

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
                    #_node_list_lookup[device][ro, co].append(name)
                    if i == 0:
                        _node_owned_lookup[device][rc].append(name)                        
            else:
                _node_list_lookup[device][rc].append(name)
                _node_owned_lookup[device][rc].append(name)

    def get_node_list_for_tile(t):
        return (_node_owned_lookup if owned else _node_list_lookup)[device].get(get_rc_from_name(device, t), [])
                
    if isinstance(tile, list):
        nodes2tile = {n:t for t in tile for n in get_node_list_for_tile(t)}
        node_info = {n.name:n for n in lapie.get_node_data(device, list(nodes2tile.keys()), False)}

        tile_nodes = defaultdict(dict)
        for n, nifo in node_info.items():
            tile_nodes[nodes2tile[n]][n.name] = ninfo        
        
        return tile_nodes
    else:
        tile_nodes = get_node_list_for_tile(tile)
        if len(tile_nodes) == 0:
            return {}
    
        return {n.name:n for n in lapie.get_node_data(device, tile_nodes, False)}


def get_tiles_by_rc(device, rc):
    if isinstance(rc, str):
        rc = get_rc_from_name(device, rc)

    tilegrid = database.get_tilegrid(device)['tiles']
    return {k:v for k,v in tilegrid.items() if (v['y'], v['x']) == rc}



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


