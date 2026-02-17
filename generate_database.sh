#!/bin/bash -i

. user_environment.sh

pushd tools
#python3 tilegrid_all.py
popd

PRJOXIDE_ROOT=`pwd`
pushd fuzzers

run_fuzzer() {
    dir="$1"
    if [ -f "$dir/fuzzer.py" ]; then
        echo "=================== Entering $dir ==================="
        pushd "$dir" > /dev/null || return
        rm -rf db .deltas
        $PRJOXIDE_ROOT/link-db-root.sh
        FUZZER_TITLE=$dir PRJOXIDE_DB="$(pwd)/db" python3 fuzzer.py 2>&1 | tee >(gzip --stdout > fuzzer.log.gz)
        popd > /dev/null || true
    fi
}

export -f run_fuzzer
export PRJOXIDE_ROOT

#find . -mindepth 1 -maxdepth 1 -type d ! -name LIFCL -exec bash -c 'run_fuzzer "$0"' {} \;
find LIFCL -mindepth 1 -maxdepth 1 -type d | sort | xargs -I {} bash -c 'run_fuzzer "{}"'
