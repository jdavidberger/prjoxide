#!/bin/bash

. user_environment.sh

pushd tools
python3 tilegrid_all.py
popd

pushd fuzzers
for dir in LIFCL/* ; do
    if [ -f "$dir/fuzzer.py" ]; then
        echo "=================== Entering $dir ==================="
        pushd $dir
        ../../../link-db-root.sh
        PRJOXIDE_DB=`pwd`/db python3 fuzzer.py 2>&1 | tee >(gzip --stdout > fuzzer.log.gz)
        popd
    fi
done
