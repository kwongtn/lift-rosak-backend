#!/bin/bash

cd /code

poetry run celery -A rosak.celery_app beat \
    -l INFO \
    --scheduler django_celery_beat.schedulers:DatabaseScheduler
