FROM tiangolo/uwsgi-nginx-flask:python3.7

RUN apt-get update \
  && apt-get install -y ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /requirements.txt
RUN pip install --upgrade -r /requirements.txt

ENV STATIC_PATH /usr/local/lib/python3.7/site-packages/flask_appbuilder/static
ENV LISTEN_PORT=9999
EXPOSE 9999

COPY ./uwsgi.ini /app/uwsgi.ini
COPY ./app /app/app

# config.py holds the real secrets and is deliberately not copied into the
# image. Mount it read-only at /app/config.py (Compose does this).
