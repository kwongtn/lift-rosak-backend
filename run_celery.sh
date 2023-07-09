#!/bin/bash

cd /code

pipenv run celery -A rosak worker -l INFO
