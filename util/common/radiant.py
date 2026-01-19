"""
Python wrapper for `radiant.sh`
"""
import asyncio
import logging
from os import path
import os
import subprocess
import database
import sys

def run_bash_script(env, *args, cwd = None, stdout = subprocess.PIPE, stderr = subprocess.PIPE):
    slug = " ".join(args[1:])
    logging.info("Running script: %s", slug)

    proc = subprocess.run(
        args=["bash", *args],
        env=env,
        cwd=cwd,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )

    stdout, stderr = proc.stdout, proc.stderr

    returncode = proc.returncode
    show_output = returncode != 0

    if show_output or True:
        for stream in [("", stdout, sys.stdout), ("ERR:", stderr, sys.stdout)]:
            if stream[1] is not None:
                for l in stream[1].decode().splitlines():
                    print(f"[{stream[0]} {slug}] {l}", file=stream[2])

    if returncode != 0:
        raise Exception(f"Error encountered running radiant: {slug}")

    return proc

def run(device, source, struct_ver=True, raw_bit=False, pdcfile=None, rbk_mode=False):
    """
    Run radiant.sh with a given device name and source Verilog file
    """

    env = os.environ.copy()
    if struct_ver:
        env["STRUCT_VER"] = "1"
    if raw_bit:
        env["GEN_RBT"] = "1"
    if rbk_mode:
        env["RBK_MODE"] = "1"

    dsh_path = path.join(database.get_oxide_root(), "radiant.sh")

    return run_bash_script(env, dsh_path, device, source)
