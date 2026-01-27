#!/usr/bin/env python3
"""
Bitstream cache tool for prjoxide

This avoids expensive bitstream rebuilds when making small changes to the
fuzzer and the Verilog input is largely unchanged.

Note that it is disabled by default. Run:
    tools/bitstreamcache.py init
to start using it.

Usage:
    tools/bitstreamcache.py fetch <DEVICE> <OUTPUT DIR> <INPUT FILE 1> <INPUT FILE 2> ...
        if a bitstream with the given configuration and input already exists,
        copy the products to <OUTPUT DIR> and return 0. Otherwise return 1.

    tools/bitstreamcache.py commit <DEVICE> <INPUT FILE 1> <INPUT FILE 2> output <OUTPUT FILE 1> ..
        save output files as the products of the input files and configuration

gzip and gunzip must be on your path for it to work

"""
import logging
import sys, os, shutil, hashlib, gzip
from logging import exception
from pathlib import Path

root_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
cache_dir = os.path.join(root_dir, ".bitstreamcache")

def get_hash(device, input_files, env = None):
    if env is None:
        env = os.environ

    hasher = hashlib.sha1()
    hasher.update(b"DEVICE")
    hasher.update(device.encode('utf-8'))
    for envkey in ("GEN_RBF", "DEV_PACKAGE", "SPEED_GRADE", "STRUCT_VER", "RBK_MODE"):
        if envkey in env:
            hasher.update(envkey.encode('utf-8'))
            hasher.update(env[envkey].encode('utf-8'))
    for fname in input_files:
        ext = os.path.splitext(fname)[1]
        hasher.update("input{}".format(ext).encode('utf-8'))
        with open(fname, "rb") as f:
            hasher.update(f.read())
    return hasher.hexdigest()

def fetch(device, input_files, env = None):
    if not os.path.exists(cache_dir):
        return

    h = get_hash(device, input_files, env=env)
    #print(h)

    cache_entry = os.path.join(cache_dir, h)
    if not os.path.exists(cache_entry) or len(os.listdir(cache_entry)) < 2:
        return

    # Touch the directory and it's contents
    Path(cache_entry).touch()
    for outprod in os.listdir(cache_entry):
        gz_path = os.path.join(cache_entry, outprod)
        Path(gz_path).touch()

        yield (outprod, gz_path)

def main():
    if len(sys.argv) < 2:
        print("Expected command (init|fetch|commit)")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "init":
        if not os.path.exists(cache_dir):
            os.mkdir(cache_dir)
    if cmd == "fetch":

        if not os.path.exists(cache_dir):
            sys.exit(1)
        if len(sys.argv) < 5:
            print("Usage: tools/bitstreamcache.py fetch <DEVICE> <OUTPUT DIR> <INPUT FILE 1> <INPUT FILE 2> ...")
            sys.exit(1)

        cache_entries = fetch(sys.argv[2], sys.argv[4:])

        for (outprod, gz_path) in cache_entries:
            assert gz_path.endswith(".gz")

            Path(gz_path).touch()
            if gz_path.endswith(".bit.gz"):
                print(f"Linking {os.path.join(sys.argv[3], outprod)}")
                os.symlink(gz_path, os.path.join(sys.argv[3], outprod))
            else:
                bn = Path(gz_path[:-3]).name
                with gzip.open(gz_path, 'rb') as gzf:
                    print(f"Writing {os.path.join(sys.argv[3], bn)}")
                    with open(os.path.join(sys.argv[3], bn), 'wb') as outf:
                        outf.write(gzf.read())
        else:
            sys.exit(1)

        sys.exit(0)

    if cmd == "commit":
        if not os.path.exists(cache_dir):
            sys.exit(0)
        idx = sys.argv.index("output")
        if len(sys.argv) < 6 or idx == -1:
            print("Usage: tools/bitstreamcache.py commit <DEVICE> <INPUT FILE 1> <INPUT FILE 2> output <OUTPUT FILE 1> ..")
            sys.exit(1)
        h = get_hash(sys.argv[2], sys.argv[3:idx])
        cache_entry = os.path.join(cache_dir, h)
        if not os.path.exists(cache_entry):
            os.mkdir(cache_entry)
        for outprod in sys.argv[idx+1:]:
            bn = os.path.basename(outprod)
            cn = os.path.join(cache_entry, bn + ".gz")

            if not os.path.exists(outprod):
                raise Exception(f"Output product does not exist")

            if os.path.getsize(outprod) == 0:
                raise Exception(f"Output product has zero length; refusing to gzip {outprod}")

            with gzip.open(cn, 'wb') as gzf:
                with open(outprod, 'rb') as inf:
                    gzf.write(inf.read())
        sys.exit(0)

if __name__ == "__main__":
    main()