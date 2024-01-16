#!/bin/bash

cd /code

celery -A rosak.celery_app beat \
    -l INFO

# To be re-enabled if https://github.com/celery/django-celery-beat/issues/506
# is resolved
# --scheduler django_celery_beat.schedulers:DatabaseScheduler
