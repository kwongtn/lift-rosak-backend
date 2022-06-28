FROM python:3.10-buster

ARG ENVIRONMENT
ENV PYTHONUNBUFFERED 1
RUN pip install pipenv
# RUN apt-get update && apt-get install -y \
#   zlib1g-dev \
#   libjpeg-dev \
#   python3-pythonmagick \
#   inkscape \
#   xvfb \
#   poppler-utils \
#   libfile-mimeinfo-perl \
#   qpdf \
#   libimage-exiftool-perl \
#   ufraw-batch \
#   ffmpeg \
#   mediainfo \
#   exiftool \
#   libpq-dev
RUN mkdir /code
WORKDIR /code

COPY Pipfile /code/Pipfile
COPY Pipfile.lock /code/Pipfile.lock
RUN if [ "$ENVIRONMENT" = "dev" ]; then pipenv install --deploy --ignore-pipfile --dev ; else pipenv install --deploy --ignore-pipfile; fi

COPY . /code/
