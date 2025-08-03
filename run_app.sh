#!/bin/bash

cd /code

python manage.py collectstatic --no-input
python manage.py createcachetable
python manage.py migrate

export GIT_COMMIT_HASH=$(cat .git/refs/heads/main | head -c 8)
export GIT_COMMIT_TIME=$(date -r .git/refs/heads/main -R)
export PYTHONPATH=$(which python)

if [ "$DEBUG" == 'True' ]; then
    python manage.py check # Doing it manually since checks aren't run by WSGI stack
    granian --interface asgi rosak.asgi:application --host 0.0.0.0 --port 8001 --reload --workers-kill-timeout 1
else
    granian --interface asgi rosak.asgi:application --host 0.0.0.0 --port 8001
fi
