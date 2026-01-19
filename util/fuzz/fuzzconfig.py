"""
This module provides a structure to define the fuzz environment
"""
import logging
import os
from os import path
from string import Template
import radiant
import database
import libpyprjoxide

db = None

def get_db():
    global db
    if db is None:
        db = libpyprjoxide.Database(database.get_db_root())
    return db

PLATFORM_FILTER = os.environ.get("FUZZER_PLATFORM", None)

_platform_skip_warnings = set()
def should_fuzz_platform(device):
    if PLATFORM_FILTER is not None and PLATFORM_FILTER not in device:
        if device not in _platform_skip_warnings:
            print(f"FUZZER_PLATFORM set to {PLATFORM_FILTER}, skipping {device}")
        _platform_skip_warnings.add(device)
        return False
    return True


class FuzzConfig:
    def __init__(self, device, job, tiles, sv = None):
        """
        :param job: user-friendly job name, used for folder naming etc
        :param device: Target device name
        :param tiles: List of tiles to consider during fuzzing
        :param sv: Minimal structural Verilog file to use as a base for interconnect fuzzing
        """
        self.device = device
        self.job = job
        self.tiles = tiles
        if sv is None:
            family = device.split("-")[0]
            suffix = device.split("-")[1]
            sv = database.get_db_root() + f"/../fuzzers/{family}/shared/empty.v"
        self.sv = sv
        self.rbk_mode = True if self.device == "LFCPNX-100" or self.device == "LIFCL-33U" else False
        self.struct_mode = True
        self.udb_specimen = None

    @property
    def workdir(self):
        return path.join(".", "work", self.job)

    def make_workdir(self):
        """Create the working directory for this job, if it doesn't exist already"""
        os.makedirs(self.workdir, exist_ok=True)

    def serialize_deltas(self, fz, prefix = ""):
        os.makedirs(".deltas", exist_ok=True)
        fz.serialize_deltas(f".deltas/{prefix}{self.job}_{self.device}")

    def check_deltas(self, name):
        if os.path.exists(f"./.deltas/{name}{self.job}_{self.device}.ron"):
            logging.info(f"Delta exists for {name} {self.job} {self.device}; skipping")
            return True
        logging.debug(f"./.deltas/{name}{self.job}_{self.device}.ron miss")
        return False

    def solve(self, fz):
        try:
            fz.solve(db)
            self.serialize_deltas(fz, fz.get_name())
        except:
            self.serialize_deltas(fz, f"FAILED-{fz.get_name()}")

    def setup(self, skip_specimen=False):
        """
        Create a working directory, and run Radiant on a minimal Verilog file to create a udb for Tcl usage etc
        """

        # Load the global database if it doesn't exist already
        global db
        if db is None:
            db = libpyprjoxide.Database(database.get_db_root())

        self.make_workdir()
        if not skip_specimen:
            self.build_design(self.sv, {})

    def subst_defaults(self):
        return {
            "arch": "LIFCL",
            "arcs_attr": "",
            "device": self.device,
            "package": "WLCSP84" if self.device.startswith("LIFCL-33") else "QFN72",
            "speed_grade": "8" if self.device == "LIFCL-33" else "7"
        }
    
    def build_design(self, des_template, substitutions = {}, prefix="", substitute=True):
        """
        Run Radiant on a given design template, applying a map of substitutions, plus some standard substitutions
        if not overriden.

        :param des_template: path to template (structural) Verilog file
        :param substitutions: dictionary containing template subsitutions to apply to Verilog file
        :param prefix: prefix to append to filename, for running concurrent jobs without collisions

        Returns the path to the output bitstream
        """
        subst = dict(substitutions)

        subst_defaults = {
            "arch": self.device.split("-")[0],
            "arcs_attr": "",
            "device": self.device,
            "package": "WLCSP84" if self.device.startswith("LIFCL-33") else "QFN72",
            "speed_grade": "8" if self.device == "LIFCL-33" else "7"
        }

        subst = subst_defaults | subst

        os.makedirs(path.join(self.workdir, prefix), exist_ok=True)
        desfile = path.join(self.workdir, prefix + "design.v")
        bitfile = path.join(self.workdir, prefix + "design.bit")
        bitfile_gz = path.join(self.workdir, prefix + "design.bit.gz")

        if "sysconfig" in subst:
            pdcfile = path.join(self.workdir, prefix + "design.pdc")
            with open(pdcfile, "w") as pdcf:
                pdcf.write("ldc_set_sysconfig {{{}}}\n".format(subst["sysconfig"]))

        if path.exists(bitfile):
            os.remove(bitfile)
        with open(des_template, "r") as inf:
            with open(desfile, "w") as ouf:
                if substitute:
                    ouf.write(Template(inf.read()).substitute(**subst))
                else:
                    ouf.write(inf.read())
        radiant.run(self.device, desfile, struct_ver=self.struct_mode, raw_bit=False, rbk_mode=self.rbk_mode)
        if self.struct_mode and self.udb_specimen is None:
            self.udb_specimen = path.join(self.workdir, prefix + "design.tmp", "par.udb")
        if path.exists(bitfile):
            return bitfile
        if path.exists(bitfile_gz):
            return bitfile_gz

        raise Exception(f"Could not generate bitstream file {bitfile} {bitfile_gz}")

    @property
    def udb(self):
        """
        A udb file specimen for Tcl
        """
        if self.udb_specimen is None:
            self.setup()
        assert self.udb_specimen is not None
        return self.udb_specimen
