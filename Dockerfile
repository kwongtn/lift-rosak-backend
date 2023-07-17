FROM python:3.11-slim-bullseye

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
ENV POETRY_VERSION 1.5.1
RUN pip install "poetry==$POETRY_VERSION"
RUN apt-get update && apt-get install -y \
    gdal-bin git
RUN mkdir /code
WORKDIR /code

COPY pyproject.toml /code/pyproject.toml
COPY poetry.lock /code/poetry.lock

RUN poetry install $(test "$ENVIRONMENT" == "dev" && echo "--with=dev") \
    --no-interaction \
    --no-ansi \
    --no-root

# Obtained via `pipenv run which python`
# RUN export PYTHONPATH=/root/.local/share/virtualenvs/code-_Py8Si6I/bin/python

COPY . /code/
