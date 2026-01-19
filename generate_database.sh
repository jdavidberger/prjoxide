#!/bin/bash

. user_environment.sh

pushd tools
#python3 tilegrid_all.py
popd

pushd fuzzers
for dir in LIFCL/* ; do
    if [ -d "$dir" ]; then
        echo "=================== Entering $dir ==================="
        pushd $dir
        python3 fuzzer.py 2>&1 | tee >(gzip --stdout > fuzzer.log.gz) || true
        popd
    fi
done