FROM python:3.11-slim-bookworm

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
ENV GOOGLE_APPLICATION_CREDENTIALS /google-application-credential.json
RUN apt-get update && apt-get install -y \
    gdal-bin git gcc python3-dev

ENV POETRY_VERSION 1.7.1
RUN pip install "poetry==$POETRY_VERSION"

RUN mkdir /code
WORKDIR /code

COPY pyproject.toml /code/pyproject.toml
COPY poetry.lock /code/poetry.lock

RUN poetry config virtualenvs.create false \
    && poetry install $(test "$ENVIRONMENT" == "dev" && echo "--with=dev") \
    --no-interaction \
    --no-ansi \
    --no-root

# Obtained via `pipenv run which python`
# RUN export PYTHONPATH=/root/.local/share/virtualenvs/code-_Py8Si6I/bin/python

COPY . /code/
