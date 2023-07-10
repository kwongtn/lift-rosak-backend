#!/bin/bash

cd /code

pipenv run celery -A rosak.celery_app worker -l INFO -c 2
