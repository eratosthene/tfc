TFC: a Transformers collection app, on Flask-AppBuilder and MariaDB
--------------------------------------------------------------------

- Install it::

	pip install flask-appbuilder
	git clone https://github.com/dpgaspar/Flask-AppBuilder-Skeleton.git

- Run it::

	fabmanager run


That's it!!



Docker
------

TFC runs the same way as fbc2 and vc on the shared server: one app container
from ``docker/compose.yml``, with no database service. The data is in the
MariaDB server's database, reached through ``SQLALCHEMY_DATABASE_URI`` (in
``docker/.env`` or ``config.py``, ending in ``?charset=utf8mb4``). Image files
are stored in the ``uploads`` folder, and the tables hold only their file
names.

First-time setup, from the repo root::

	cp config.py.tpl config.py              # set SECRET_KEY
	mkdir uploads                           # image files; mounted into the container
	cp docker/.env.example docker/.env      # set SQLALCHEMY_DATABASE_URI
	docker/live-up.sh                       # build and start, on port 9999
	sudo docker compose -f docker/compose.yml exec tfc flask db upgrade
	sudo docker compose -f docker/compose.yml exec tfc flask fab create-admin

``config.py`` is mounted read-only. ``docker/.env`` is passed to the app as
environment (single-quote the value). ``docker/live-logs.sh`` follows
the logs, ``docker/live-down.sh`` stops the app, and ``docker/live-up.sh -n``
recreates it without a rebuild after changing ``config.py`` or ``docker/.env``.

Database changes
~~~~~~~~~~~~~~~~

Tables are made and changed by Flask-Migrate (Alembic), in ``migrations/``.
Flask-AppBuilder makes its own ``ab_*`` security tables when the app starts, so
migrations leave them alone. Run ``flask db upgrade`` on a new database and
after any update that adds a migration. After changing ``app/models.py``::

	flask db migrate -m "What changed"      # writes migrations/versions/...; read it
	flask db upgrade

``flask db migrate`` writing nothing ("No changes in schema detected") means the
migrations match the models. Users are made with ``flask fab create-admin``.

Local testing
~~~~~~~~~~~~~

``docker/compose.dev.yml`` runs the app with its own throwaway MariaDB on
127.0.0.1 (app on port 5561). The database is behind the ``db`` profile, and
its user, password and database come from ``SQLALCHEMY_DATABASE_URI`` in
``docker/.env`` (host ``db``; avoid ``@ : / % # ?`` in the password)::

	docker compose -f docker/compose.dev.yml --profile db up --build
	docker compose -f docker/compose.dev.yml exec tfc flask db upgrade
	docker compose -f docker/compose.dev.yml exec tfc flask fab create-admin

Tests
~~~~~

``python -m pytest`` runs against in-memory SQLite. To run them against MariaDB
as CI does, point ``TEST_DATABASE_URI`` at an empty database whose name ends in
``_test`` (the tests refuse any other)::

	TEST_DATABASE_URI='mysql+pymysql://tfc:PASSWORD@127.0.0.1:3309/tfc_test?charset=utf8mb4' python -m pytest

Backup
~~~~~~

``scripts/backup.sh`` writes a MariaDB dump and an uploads archive as dated
files in ``backups/``. A backup is only complete with both. It dumps the
server's database with the host's ``mariadb-dump`` or ``mysqldump``, using
``SQLALCHEMY_DATABASE_URI`` from ``docker/.env`` (skipped with a warning while
there is none), and runs docker with ``DOCKER="sudo docker"`` if needed.
``COMPOSE_FILE=docker/compose.dev.yml`` backs up the dev stack instead.
Schedule it from the host, for example with cron::

	0 3 * * * DOCKER="sudo docker" /path/to/tfc/scripts/backup.sh >> /path/to/tfc/backups/backup.log 2>&1

Restore
~~~~~~~

With ``STAMP`` set to the backup's timestamp. The database first, into the
``SQLALCHEMY_DATABASE_URI`` database (``mariadb`` or ``mysql`` on the host, with
the host and user from the URI)::

	STAMP=20250101-030000
	gunzip -c backups/tfc-db-$STAMP.sql.gz | mariadb -h HOST -u USER -p DBNAME

For the dev stack, run it inside the ``db`` service instead::

	gunzip -c backups/tfc-db-$STAMP.sql.gz | docker compose -f docker/compose.dev.yml exec -T db sh -c \
	  '. /db-env.sh; exec mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'

Then the uploads, replacing what is there (add ``sudo`` and ``-f
docker/compose.dev.yml`` as needed)::

	docker compose -f docker/compose.yml exec -T tfc sh -c 'rm -rf /app/app/static/uploads/*'
	docker compose -f docker/compose.yml exec -T tfc tar xzf - -C /app/app/static < backups/tfc-uploads-$STAMP.tar.gz
