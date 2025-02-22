FROM python:3.12-slim-bookworm

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
ENV UV_HTTP_TIMEOUT 300
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

ENV UV_HTTP_TIMEOUT 300
ENV UV_INSTALL_DIR /root/.local/bin
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$ENVIRONMENT" = "dev" ]; then \
        "$UV_INSTALL_DIR/uv" pip install --no-cache-dir --system -r requirements-dev.lock; \
    else \
        "$UV_INSTALL_DIR/uv" pip install --no-cache-dir --system -r requirements.lock; \
    fi


COPY . /code/
