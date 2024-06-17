FROM python:3.12-slim-bookworm

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
ENV GOOGLE_APPLICATION_CREDENTIALS /google-application-credential.json
RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y \
    curl gdal-bin git gcc jq python3-dev

RUN POETRY_VERSION=$(curl https://api.github.com/repos/python-poetry/poetry/releases/latest -s | jq .name -r) && \
    pip install "poetry==$POETRY_VERSION"

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
