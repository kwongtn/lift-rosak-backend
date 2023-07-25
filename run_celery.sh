#!/bin/bash

cd /code

celery -A rosak.celery_app worker -l INFO -c 2
