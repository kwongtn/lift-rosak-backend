#!/bin/bash

cd /code

pipenv run python manage.py collectstatic --no-input

export GIT_COMMIT_HASH=$(cat .git/refs/heads/main | head -c 8)
export GIT_COMMIT_TIME=$(date -r .git/refs/heads/main -R)

if [ "$DEBUG" == 'True' ]; then
    pipenv run python manage.py check # Doing it manually since checks aren't run by WSGI stack
    pipenv run gunicorn rosak.asgi:application -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001 --reload --config gunicorn.dev.conf.py
else
    pipenv run gunicorn rosak.asgi:application -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001
fi
