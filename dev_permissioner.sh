#! /bin/bash

DIRS=$(find -path './*' -prune -type d)

for dir in $DIRS; do

    if [[ $dir == "./.latest_migrations" ]]; then
        chown --reference=README.md "$dir" -Rc
        continue
    fi

    SUB_DIRS=$(find -path "$dir/*" -prune -type d)

    for subdir in $SUB_DIRS; do
        if [[ $subdir == "$dir/migrations" ]]; then
            chown --reference=README.md "$subdir" -Rc
        fi

    done

done
