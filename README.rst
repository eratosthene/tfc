Base Skeleton to start your application using Flask-AppBuilder and MongoEngine
------------------------------------------------------------------------------

- Install it::

	pip install flask-appbuilder
	git clone https://github.com/dpgaspar/Flask-AppBuilder-Skeleton.git

- Run it::

	fabmanager run


That's it!!



Docker Compose
--------------

The stack is the app, MariaDB (``db``, optional for now) and a temporary MongoDB (``mongo``).
The app still stores its data in MongoDB until the MariaDB migration lands;
remove ``mongo`` from ``compose.yml`` once that is verified.

First-time setup::

	cp .env.example .env          # optional until the MariaDB migration
	cp config.py.tpl config.py    # set SECRET_KEY; set MONGODB_SETTINGS host to "mongo"
	docker compose up --build

MariaDB (``db``) is optional until the migration and not started by default.
To run it, set ``SQLALCHEMY_DATABASE_URI`` in ``.env`` (the user, password and
database are taken from it) and use ``docker compose --profile db up --build``.

The app listens on http://127.0.0.1:9999 (change with ``TFC_BIND`` and
``TFC_PORT`` in ``.env``). Create the first user with::

	docker compose exec app flask fab create-admin

``config.py`` is mounted read-only into the container; uploaded images live in
the ``uploads`` volume.

Backup
~~~~~~

``scripts/backup.sh`` writes a MariaDB dump and an uploads archive (and, while
Mongo is in use, a Mongo archive) as dated files in ``backups/``. A backup is
only complete with all of them. Schedule it from the host, for example with
cron::

	0 3 * * * /path/to/tfc/scripts/backup.sh >> /path/to/tfc/backups/backup.log 2>&1

Restore
~~~~~~~

With the stack running and ``STAMP`` set to the backup's timestamp::

	STAMP=20250101-030000
	gunzip -c backups/tfc-db-$STAMP.sql.gz | docker compose exec -T db sh -c \
	  '. /db-env.sh; exec mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'
	docker compose exec -T app sh -c 'rm -rf /app/app/static/uploads/* /app/app/static/uploads/.[!.]*' || true
	docker compose exec -T app tar xzf - -C /app/app/static < backups/tfc-uploads-$STAMP.tar.gz
	# while Mongo is in use:
	docker compose exec -T mongo mongorestore --archive --gzip --drop < backups/tfc-mongo-$STAMP.archive.gz

The dump loads into the existing database, replacing tables it contains. To
restore into a fresh machine, run ``docker compose --profile db up -d db`` first, then the
commands above.
