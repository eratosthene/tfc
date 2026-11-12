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
	sudo chown 1000 uploads                 # the container runs as UID 1000, not root
	cp docker/.env.example docker/.env      # set SQLALCHEMY_DATABASE_URI
	docker/live-up.sh                       # build and start, on port 9999
	sudo docker compose -f docker/compose.yml exec tfc flask fab create-admin

The container runs ``flask db upgrade`` before gunicorn starts (``docker/docker-entrypoint.sh``),
so the tables are made and kept up to date on every start, and Flask-AppBuilder's
first-boot permissions are made by one process, not raced by two workers.
``config.py`` is mounted read-only. ``docker/.env`` is passed to the app as
environment (single-quote the value). ``docker/live-logs.sh`` follows
the logs, ``docker/live-down.sh`` stops the app, and ``docker/live-up.sh -n``
recreates it without a rebuild after changing ``config.py`` or ``docker/.env``.

Python and dependencies
~~~~~~~~~~~~~~~~~~~~~~~

The app runs on Python 3.12 (``Pipfile``'s ``python_version``; the image is
``python:3.12-alpine``, as in fbc2). It is served by gunicorn, as the non-root ``app`` user
(UID 1000, build argument ``APP_UID``), on port 9999. There is no nginx: Flask
serves Flask-AppBuilder's ``/static`` files, and ``/static/uploads/<file>`` from
``UPLOAD_FOLDER`` (404 if the file is missing, and no path outside the folder).
The mounted ``uploads`` folder must therefore be writable by that UID
(``sudo chown -R 1000 uploads``), and ``config.py`` readable by it.

``Pipfile.lock`` is the only list of dependencies; there is no
``requirements.txt``. **The Dockerfile generates it**: its first stage runs
``pipenv requirements --hash`` on the lock, and the app stage installs that with
``--require-hashes``. CI's tests and audit export the lock the same way. To
change a dependency, edit ``Pipfile``, run ``pipenv lock``, and commit both.

Current versions (sub-issue 13): Flask 3.1, Werkzeug 3.1, Flask-AppBuilder 5.3,
SQLAlchemy 2, Flask-SQLAlchemy 3, Flask-Migrate 4.1 and Pillow 13. Only the
packages the app imports are in ``Pipfile`` (Flask, Werkzeug, Flask-AppBuilder,
Flask-Migrate, Flask-SQLAlchemy, SQLAlchemy, greenlet, PyMySQL, gunicorn,
python-dotenv, Pillow and PyYAML); Flask-Login, Flask-WTF, Flask-Babel, PyJWT,
marshmallow, blinker and the rest come from Flask-AppBuilder and Flask, so
``pipenv lock`` keeps them current. ``flask-restful`` was removed (nothing
imports it). ``prison``, ``sqlalchemy-utils``, ``flask-jwt-extended`` and
``marshmallow-enum`` are not direct dependencies; FAB 5.3 requires the first
three, and the last is no longer in the lock. ``flask-openid`` and
``python3-openid`` are gone with FAB 3, and the repo has no ``freeze.py``.

Translations: ``app/translations`` was deleted in sub-issue 1 and the app has no
``babel.cfg`` or Babel code, so there are none. Flask-Babel is present only as a
FAB dependency, with FAB's own built-in strings.

``pip-audit`` on the lock (11 November 2026) reports no known vulnerabilities, and
the audit workflow now fails on a finding. ``pip list --outdated`` shows only
``python-dateutil`` (4.0.0 available; FAB allows only 2.x, so it follows FAB).

To run it locally with the dev Compose file, create ``config.py`` and
``docker/.env`` as above, then::

	docker compose -f docker/compose.dev.yml --profile db up --build
	docker compose -f docker/compose.dev.yml exec tfc flask fab create-admin

and open http://127.0.0.1:5561. Tests: ``pipenv install --dev``, then
``pipenv run pytest --cov=app --cov-fail-under=100``.

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
	docker compose -f docker/compose.dev.yml exec tfc flask fab create-admin

TFWiki fetcher and parser
~~~~~~~~~~~~~~~~~~~~~~~~~

``app/tfwiki`` reads figure sections from tfwiki.net (issue 53); nothing in the app
uses it yet. ``fetcher.py`` gets a page's wikitext through the MediaWiki API,
``parser.py`` turns a figure's section into suggestions (name, faction, year,
accessories, tooling, ancestors, packed-with, first picture), and ``figure.py`` ties
them together from a pasted link. tfwiki.net's robots.txt disallows automated clients,
so fetching is **off** unless ``TFWIKI_ENABLED`` is set in ``config.py`` (see
``config.py.tpl``). When on it makes one request at a time, at least two seconds apart
(shared by all workers through files in ``TFWIKI_CACHE_DIR``), stops for an hour after
a 429 or 503, sends a User-Agent naming this repository, and caches every page by
title, so a page is fetched once. Cached pages are readable with fetching off. The
recorded pages the tests use are in ``tests/fixtures/tfwiki`` (see its README).

Tests
~~~~~

``python -m pytest`` runs against in-memory SQLite. To run them against MariaDB
as CI does, point ``TEST_DATABASE_URI`` at an empty database whose name ends in
``_test`` (the tests refuse any other)::

	TEST_DATABASE_URI='mysql+pymysql://tfc:PASSWORD@127.0.0.1:3309/tfc_test?charset=utf8mb4' python -m pytest

CI also requires 100% line coverage of ``app/`` (``--cov=app --cov-fail-under=100``;
see ``.coveragerc`` for what is not measured: ``migrations/``, ``scripts/`` and
the tests). Check it locally with ``python -m pytest --cov=app --cov-report=term-missing``.

Nested franchises
~~~~~~~~~~~~~~~~~

A franchise can have one parent (Legacy United under Legacy under Generations),
set in the franchise's add and edit forms. Tag a figure with only the lowest
franchise that fits: its page lists the franchises above it too, and filtering
the Figure list by a franchise (or "Search Figures" on the Franchise list) also
finds the figures tagged with anything below it. A franchise cannot go under
itself or one of its own descendants, a tree may be 8 levels deep at most, and
a franchise that still has sub-franchises cannot be deleted.

Figures already tagged with every level by hand are not harmed. To tidy them
after setting the parents, ``flask prune-franchises`` lists the tags that a
lower tag on the same figure already covers, and changes nothing;
``flask prune-franchises --apply`` removes them. It never runs by itself.

Moving to the new data model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``docs/proposals/data-model.md`` describes the new model (characters,
continuities, per-figure references, accessories as text). It arrives in steps.
This one only *adds*: the ``b2d4f6a8c013`` revision creates the new tables and
columns next to the old ones, and runs on deploy like any revision. The app
does not read them yet, so nothing looks different.

``scripts/migrate_data_model.py`` fills them from the old tables. It never
deletes or changes the old tables. **Take a backup first** (``scripts/backup.sh``),
then, from the repo root on the server:

.. code-block:: bash

	docker compose -f docker/compose.yml exec tfc python scripts/migrate_data_model.py dry-run
	docker compose -f docker/compose.yml exec tfc python scripts/migrate_data_model.py apply
	docker compose -f docker/compose.yml exec tfc python scripts/migrate_data_model.py verify

``dry-run`` does everything in a transaction, prints the plan and the lists to
look at (characters with no ``(X)`` continuity, character links rewritten, links
used in more than one role, links that are not tfwiki.net, links nothing uses,
accessories whose name contains a comma, missing upload files), and rolls
back. ``apply`` does it for real, checks every figure against the old data, and
refuses to commit if anything differs. ``verify`` repeats the comparison and
records that it passed (the revision that finally drops the old tables needs
that). ``reverse`` rebuilds the old structures from the new ones and clears
those records. Options: ``--no-continuity NAME`` leaves a suffix that is not a
continuity (``facility``) blank, ``--family "NAME=SUFFIX,SUFFIX"`` (repeatable) puts those suffixes' continuities in a
continuity family, creating it, ``--json PATH`` also writes the report, and
``--again`` lets ``apply`` run twice, overwriting edits made in the new
structures since. Run ``verify`` straight after ``apply``: once the new
structures are edited it reports those edits as differences.

Migrating the Mongo data
~~~~~~~~~~~~~~~~~~~~~~~~

One-time: ``scripts/migrate_mongo_to_sql.py`` copies the old MongoDB data and
its GridFS images into MariaDB and the ``uploads`` folder (sub-issue #8). It
only reads Mongo. The MariaDB tables get a ``legacy_id`` column (the Mongo
ObjectId) from the ``a1c3e5f7b902`` migration; each row is upserted on it, so
the script can be re-run safely. **Run it before anyone edits data in the new
app**: a re-run puts the Mongo values back over the rows.

How it maps: lookup tables first, then TFWikiLink, Figure, and the figure
association rows, with list order kept in ``position``. Each image is written
byte for byte to ``uploads/`` named ``<uuid>_sep_<name>``, as the app names
uploads, with its thumbnail made by Flask-AppBuilder's ImageManager (the app's
code). The original is kept as it was, not shrunk to 2000px. Anything that
cannot migrate is left out and listed (a figure whose character or faction no
longer exists, a name too long for its column); list entries that point at a
deleted document are dropped with a warning.

``docker/compose.migrate.yml`` has a throwaway MongoDB for a *restored copy* of
the dump, so the real Mongo is never connected to. Steps, from the repo root on
the server (add ``sudo`` to docker as needed):

1. Back up Mongo, and the new side, first. ``MONGO`` is the running Mongo
   container's name (``docker ps``)::

	mkdir -p backups
	docker exec MONGO mongodump --db tfc --archive > backups/mongo-$(date +%Y%m%d-%H%M%S).archive
	ls -l backups/mongo-*.archive           # not empty? the dump says "done dumping" for each collection
	scripts/backup.sh                       # the MariaDB database and uploads, as they are now

2. Be on this code, with the tables up to date (starting the container runs ``flask db upgrade``,
   which adds ``legacy_id``), and ``uploads/`` present::

	docker/live-up.sh

3. Restore the dump into the throwaway Mongo::

	docker compose -f docker/compose.migrate.yml up -d mongo
	docker compose -f docker/compose.migrate.yml exec -T mongo mongorestore --archive --nsInclude 'tfc.*' < backups/mongo-STAMP.archive

4. Dry run: reads everything, checks each image can be opened, and writes
   nothing. It prints the Mongo counts and any problems::

	docker compose -f docker/compose.migrate.yml run --rm migrate --dry-run

   If it says no collection was found, the names printed are what is in the
   dump; adjust ``SPECS`` in the script.

5. The real run. It prints a verification report: counts per collection and
   per association, every field and list compared, every image compared by
   length and SHA-256, and ten figures to check by hand::

	docker compose -f docker/compose.migrate.yml run --rm migrate | tee backups/migration-report.txt

   Exit status 0 and "OK: nothing wrong found." mean the counts match and every
   image matches its source. Anything under "Problems" or "Mismatches" needs a
   look before going on; fixing it and re-running is safe.
   ``... run --rm migrate --verify-only`` repeats just the comparison, and
   ``--sample N --seed S`` picks the figures to spot-check.

6. Open the app and check the ten figures listed (``/figuremodelview/show/<id>``):
   name, year, faction, character, franchises, tooling, lists in order, and the
   picture and thumbnail.

7. Done: stop the throwaway Mongo, keeping the dump (``-v`` deletes its data)::

	docker compose -f docker/compose.migrate.yml down -v

The ``mongo`` container on the server and its data stay until the checks above
pass and the dump is kept somewhere safe; only then remove it. ``compose.yml``
has no Mongo service now, so there is nothing to remove from it. Once this has
been run and checked, the script stays in ``scripts/`` as a record (its header
says so), and ``legacy_id`` can be dropped in a later cleanup once sub-issue 13
no longer needs it. The tests for the script run against a real MongoDB when
``TEST_MONGO_URI`` is set, as in CI.

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
