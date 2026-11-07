# Build from the repo root: docker build -f docker/Dockerfile .
#
# Pipfile.lock is the only list of dependencies. The first stage exports it as
# a hashed requirements file, so there is no requirements.txt to keep in step.
FROM python:3.12-alpine AS requirements
RUN pip install --no-cache-dir pipenv
COPY Pipfile Pipfile.lock /build/
WORKDIR /build
RUN pipenv requirements --hash > /requirements.txt

FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=requirements /requirements.txt /requirements.txt
# The build tools are only for packages with no musl wheel (MarkupSafe,
# Flask-Login ...), and are removed in the same layer, as in fbc2.
RUN apk add --no-cache --virtual .build-dependencies build-base linux-headers \
    && pip install --require-hashes -r /requirements.txt \
    && apk del .build-dependencies

# For `flask db upgrade` and `flask fab create-admin` inside the container.
ENV FLASK_APP=app
EXPOSE 9999

WORKDIR /app
COPY ./app /app/app
COPY ./migrations /app/migrations

# gunicorn runs as this user. The mounted uploads folder must be writable by
# it (chown it to APP_UID on the host) and config.py readable by it.
ARG APP_UID=1000
RUN adduser -D -H -u ${APP_UID} -s /sbin/nologin app
# Made here so a fresh named volume (compose.dev.yml) is owned by the app user.
RUN mkdir -p /app/app/static/uploads && chown app /app/app/static/uploads
USER app

# config.py holds the real secrets and is deliberately not copied into the
# image. Mount it read-only at /app/config.py (Compose does this).
# Flask serves its own static files and the uploads (app/__init__.py); there is
# no nginx in front.
CMD ["gunicorn", "--bind", "0.0.0.0:9999", "--workers", "2", "--access-logfile", "-", "app:app"]
