#!/bin/bash

cd /code

python manage.py collectstatic --no-input
python manage.py createcachetable
python manage.py migrate
python manage.py migrate --database=timescale

if [ -z "$GIT_COMMIT_HASH" ]; then
    if [ -d .git ] && command -v git >/dev/null 2>&1; then
        export GIT_COMMIT_HASH=$(git rev-parse --short=8 HEAD 2>/dev/null)
    fi
fi

if [ -z "$GIT_COMMIT_TIME" ]; then
    if [ -d .git ] && command -v git >/dev/null 2>&1; then
        export GIT_COMMIT_TIME=$(git log -1 --format=%cd --date=rfc 2>/dev/null)
    fi
fi
export PYTHONPATH=$(which python)

if [ "$DEBUG" == 'True' ]; then
    python manage.py check # Doing it manually since checks aren't run by WSGI stack
    granian --interface asgi rosak.asgi:application --host 0.0.0.0 --port 8001 --reload --workers-kill-timeout 1
else
    granian --interface asgi rosak.asgi:application --host 0.0.0.0 --port 8001
fi
