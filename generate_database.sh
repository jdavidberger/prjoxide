#!/bin/bash -i

set -o allexport

. user_environment.sh

fuzz=false
merge=false
git_commit=false

while getopts 'fgm' flag; do
  case "${flag}" in
    f) fuzz=true ;;
    m) merge=true ;;
    g) git_commit=true ;;
    *) print_usage
       exit 1 ;;
  esac
done

pushd tools
#python3 tilegrid_all.py
popd

PRJOXIDE_ROOT=`pwd`

run_fuzzer() {
    dir="$1"
    if [ -f "$dir/fuzzer.py" ]; then
        set -ex

        echo "=================== Entering $dir ==================="
        pushd "$dir" > /dev/null || return

        if [ "$fuzz" = true ] ; then
          rm -rf db .deltas
          $PRJOXIDE_ROOT/link-db-root.sh
          FUZZER_TITLE=$dir PRJOXIDE_DB="$(pwd)/db" python3 fuzzer.py 2>&1 | tee >(gzip --stdout > fuzzer.log.gz)
        fi
        popd > /dev/null || true

        if [ -d "$dir/db" ]; then
          if [ "$merge" = true ] ; then
            pushd ..
            python3 ./tools/merge-databases.py fuzzers/$dir/db database/
            popd
          fi

          if [ "$git_commit" = true ] ; then
            pushd ../database
            git add **.ron
            git commit -m "Incorporating database changes from $dir"
            popd
          fi
        fi

    fi
}
export -f run_fuzzer

pushd fuzzers
find . -mindepth 1 -maxdepth 2 -type d | sort | xargs -I {} bash -c 'run_fuzzer "{}"'
