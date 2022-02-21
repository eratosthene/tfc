FROM tiangolo/uwsgi-nginx-flask:python3.7

RUN apt-get update \
  && apt-get install -y ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /requirements.txt
RUN pip install --upgrade -r /requirements.txt

ENV STATIC_PATH /usr/local/lib/python3.7/site-packages/flask_appbuilder/static
ENV TFC_SETTINGS=/tfc.cfg
ENV LISTEN_PORT=9999
EXPOSE 9999

COPY ./tfc.cfg /tfc.cfg
COPY ./uwsgi.ini /app/uwsgi.ini
COPY ./app /app/app

