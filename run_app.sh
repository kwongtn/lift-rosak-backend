#!/bin/bash

cd /code

pipenv run python manage.py collectstatic --no-input

if [ "$DEBUG" == 'True' ]; then
    pipenv run python manage.py check # Doing it manually since checks aren't run by WSGI stack
    pipenv run gunicorn rosak.asgi:application -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001 --reload --config gunicorn.dev.conf.py
else
    pipenv run gunicorn rosak.asgi:application -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001
fi
