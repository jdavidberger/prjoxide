"""
Database and Database Path Management
"""
import os
from os import path
import json
import subprocess
from pathlib import Path
import pyron as ron
import gzip

import sqlite3
import lapie

def get_oxide_root():
    """Return the absolute path to the Project Oxide repo root"""
    return path.abspath(path.join(__file__, "../../../"))


def get_db_root():
    """
    Return the path containing the Project Oxide database
    This is database/ in the repo, unless the `PRJOXIDE_DB` environment
    variable is set to another value.
    """
    if "PRJOXIDE_DB" in os.environ and os.environ["PRJOXIDE_DB"] != "":
        return os.environ["PRJOXIDE_DB"]
    else:
        return path.join(get_oxide_root(), "database")


def get_db_subdir(family = None, device = None, package = None):
    """
    Return the DB subdirectory corresponding to a family, device and
    package (all if applicable), creating it if it doesn't already
    exist.
    """
    subdir = get_db_root()
    dparts = [family, device, package]
    for dpart in dparts:
        if dpart is None:
            break
        subdir = path.join(subdir, dpart)
        if not path.exists(subdir):
            os.mkdir(subdir)
    return subdir

_tilegrids = {}
def get_tilegrid(family, device = None):
    """
    Return the deserialised tilegrid for a family, device
    """
    if device is None:
        device = family
        family = device.split('-')[0]

    if device not in _tilegrids:
        tgjson = path.join(get_db_subdir(family, device), "tilegrid.json")
        if path.exists(tgjson):
            with open(tgjson, "r") as f:
                try:
                    _tilegrids[device] = json.load(f)
                except:
                    print(f"Exception encountered reading {tgjson}")
                    raise
        else:
            _tilegrids[device] = {"tiles":{}}
    return _tilegrids[device]

def get_iodb(family, device = None):
    """
    Return the deserialised iodb for a family, device
    """
    if device is None:
        device = family
        family = device.split('-')[0]
    tgjson = path.join(get_db_subdir(family, device), "iodb.json")
    with open(tgjson, "r") as f:
        return json.load(f)


def get_devices():
    """
    Return the deserialised content of devices.json
    """
    djson = path.join(get_db_root(), "devices.json")
    with open(djson, "r") as f:
        return json.load(f)

def get_tiletypes(family):
    family = family.split("-")[0]    
    p = path.join(get_db_root(), family, "tiletypes")

    tiletypes = {}

    if path.exists(p):
        for entry in Path(p).iterdir():
            if entry.name.endswith(".ron"):
                with open(entry.absolute(), "r") as f:
                    tiletypes[entry.name.split(".")[0]] = ron.loads(f.read().replace("\\'", "'"))

    return tiletypes
            

def get_db_commit():
    return subprocess.getoutput('git -C "{}" rev-parse HEAD'.format(get_db_root()))

_sites = {}
def get_sites(family, device = None):
    if device is None:
        device = family
        family = device.split('-')[0]

    site_file = path.join(get_db_subdir(family, device), "sites.json.gz")
    if site_file not in _sites:
        if not path.exists(site_file):
            sites = lapie.get_sites_with_pin(device)
            with gzip.open(site_file, 'wb') as f:
                f.write(json.dumps(sites).encode('utf-8'))        
        
        with gzip.open(site_file, 'r') as f:
            _sites[site_file] = json.loads(f.read().decode('utf-8'))
    return _sites[site_file]
            

def check_tiletype(tiletype, tiletype_info):
    pips = tiletype_info["pips"]
    enums = tiletype_info["enums"]
    words = tiletype_info["words"]
    
    for to_pin in pips:
        for from_pin in pips[to_pin]:
            if "bits" not in from_pin:
                wire = from_pin["from_wire"]
                print(f"Warning: Unmapped pip {wire} -> {to_pin}")

    for enum in enums:
        for option in enums[enum]["options"]:
            if len(enums[enum]["options"][option]) == 0:
                print(f"Warning unmapped option {option} in {enum}")

    for word in words:
        idx = 0
        for bit in words[word]["bits"]:
            if len(bit):
                print(f"Warning word entry for value {idx} in {word}")
            idx = idx + 1
            


def check_device(device):
    tiletypes = get_tiletypes(device)    
    tg = get_tilegrid(device)["tiles"]

    warned = set()
    
    for tile, tile_info in tg.items():
        tiletype = tile_info["tiletype"]

        if tiletype not in tiletypes and tiletype not in warned:
            warned.add(tiletype)            
            print(f"Warning: Could not find tile type definition for tiletype {tiletype} tile {tile} in {device}")

def get_device_list():
    devices = get_devices()

    for family in devices["families"]:
        for device in devices["families"][family]["devices"]:
            yield device


            
def check_consistency():
    devices = get_devices()

    for family in devices["families"]:
        
        tiletypes = get_tiletypes(family)

        for tiletype in tiletypes:
            check_tiletype(tiletype, tiletypes[tiletype])

        for device in devices["families"][family]["devices"]:
            check_device(device)
           
