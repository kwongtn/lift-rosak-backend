#!/bin/bash

cd /code

poetry run celery -A rosak.celery_app worker -l INFO -c 2
