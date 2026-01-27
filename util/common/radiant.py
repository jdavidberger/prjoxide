"""
Python wrapper for `radiant.sh`
"""
import asyncio
import logging
import time
from os import path
import os
import subprocess
import database
import sys

def run_bash_script(env, *args, cwd = None, stdout = subprocess.PIPE, stderr = subprocess.PIPE):
    slug = " ".join(args[1:])
    logging.debug("Running script: %s", slug)

    subprocess_args = {
        "args": ["bash", *args],
        "env":  env,
        "cwd": cwd,
        "stdout": stdout,
        "stderr": stderr
    }

    def process_subprocess_result(stdout, stderr, returncode):
        show_output = returncode != 0 or len(stderr.strip()) > 0

        if show_output or logging.DEBUG >= logging.root.level:
            for stream in [("", stdout, sys.stdout), ("ERR:", stderr, sys.stdout)]:
                if stream[1] is not None:
                    for l in stream[1].decode().splitlines():
                        logging.info(f"[{stream[0]} {slug}] {l}")

        if returncode != 0:
            raise Exception(f"Error encountered running radiant: {slug} {returncode}")

    # try:
    #     loop = asyncio.get_running_loop()
    #
    #     async def async_function():
    #         proc = await asyncio.create_subprocess_exec(**subprocess_args)
    #
    #         stdout, stderr = await proc.communicate()
    #
    #         process_subprocess_result(stdout, stderr, await proc.wait())
    #
    #         return proc
    #
    #     return asyncio.run_coroutine_threadsafe(async_function(), loop).result()
    # except RuntimeError:
    #     pass


    proc = subprocess.run(**subprocess_args)

    process_subprocess_result(proc.stdout, proc.stderr, proc.returncode)

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
    logging.info(f"Building [{device}] {source}")
    return run_bash_script(env, dsh_path, device, source)
