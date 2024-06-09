FROM python:3.12-slim-bookworm

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
ENV GOOGLE_APPLICATION_CREDENTIALS /google-application-credential.json
RUN --mount=target=/var/lib/apt/lists,type=cache,sharing=locked \
    --mount=target=/var/cache/apt,type=cache,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update && apt-get install -y \
    curl gdal-bin git gcc jq python3-dev

ADD --chmod=755 https://astral.sh/uv/install.sh /install.sh
RUN /install.sh && rm /install.sh

RUN mkdir /code
WORKDIR /code

COPY requirements.lock ./
COPY requirements-dev.lock ./

RUN --mount=type=cache,target=/root/.cache/uv if [ "$ENVIRONMENT" = "dev" ]; \
    then \
        /root/.cargo/bin/uv \
        pip install --system --no-cache -r requirements-dev.lock \
    ; else \
        /root/.cargo/bin/uv \
        pip install --system --no-cache -r requirements.lock \
    ; fi

COPY . /code/
