FROM tiangolo/uwsgi-nginx-flask:python3.7

# ca-certificates is already in the base image; an apt-get upgrade of it
# fails now that the Debian 11 security mirror no longer carries the package.

COPY ./requirements.txt /requirements.txt
RUN pip install --upgrade -r /requirements.txt

ENV STATIC_PATH=/usr/local/lib/python3.7/site-packages/flask_appbuilder/static
ENV LISTEN_PORT=9999
# For `flask db upgrade` and `flask fab create-admin` inside the container.
ENV FLASK_APP=app
EXPOSE 9999

COPY ./uwsgi.ini /app/uwsgi.ini
COPY ./app /app/app
COPY ./migrations /app/migrations

# config.py holds the real secrets and is deliberately not copied into the
# image. Mount it read-only at /app/config.py (Compose does this).
