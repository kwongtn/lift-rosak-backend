#! /bin/bash

# Container-created files are root-owned; re-exec inside the container (root) so
# this script works for a non-root host user without sudo.
if [ "$(id -u)" -ne 0 ]; then
    exec docker compose exec -T app bash dev_permissioner.sh "$@"
fi

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
