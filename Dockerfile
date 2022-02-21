FROM tiangolo/uwsgi-nginx-flask:python3.7

ENV LISTEN_PORT=9999
EXPOSE 9999

RUN apt-get update \
  && apt-get install -y ca-certificates

COPY ./requirements.txt /requirements.txt
RUN pip install --update /requirements.txt

COPY ./tfc.cfg /tfc.cfg
ENV TFC_SETTINGS=/tfc.cfg
COPY ./app /app
