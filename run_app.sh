#!/bin/bash

cd /code

poetry run python manage.py collectstatic --no-input

export GIT_COMMIT_HASH=$(cat .git/refs/heads/main | head -c 8)
export GIT_COMMIT_TIME=$(date -r .git/refs/heads/main -R)
export PYTHONPATH=$(poetry run which python)

if [ "$DEBUG" == 'True' ]; then
    poetry run python manage.py check # Doing it manually since checks aren't run by WSGI stack
    poetry run gunicorn rosak.asgi:application -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001 --reload --config gunicorn.dev.conf.py
else
    poetry run gunicorn rosak.asgi:application -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001
fi
