FROM python:3.10-slim-bullseye

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
RUN pip install pipenv
RUN apt-get update && apt-get install -y \
    gdal-bin
RUN mkdir /code
WORKDIR /code

COPY Pipfile /code/Pipfile
COPY Pipfile.lock /code/Pipfile.lock
RUN if [ "$ENVIRONMENT" = "dev" ]; then pipenv install --deploy --ignore-pipfile --dev ; else pipenv install --deploy --ignore-pipfile; fi

COPY . /code/
