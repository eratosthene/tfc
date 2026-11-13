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

Add from TFWiki
~~~~~~~~~~~~~~~

The **Add from TFWiki** menu item makes a figure from a tfwiki.net link, for
example ``https://tfwiki.net/wiki/Alpha_Trion/toys#Legacy`` (an old-style link to
a character page works too: the figure is found on its toys page and the link is
corrected). There is no bulk import, by design: one link, one figure.

1. **Paste** the link. Only ``tfwiki.net/wiki/...`` links are accepted. A page
   already in the cache is read from it; a page that is not is fetched only if
   ``TFWIKI_ENABLED`` is on (see "Modernising old links" for the rules). "Refresh
   from the wiki" ignores the cached copy for that lookup.
2. If the link matches several figures (one toyline heading can hold more than
   one), pick the one you mean.
3. **Review** a form pre-filled with the wiki's data and a note saying where each
   guess came from, next to the raw wiki text: name, release year, faction,
   franchise, tooling, categories, accessories, Hasbro and Takara IDs, ancestors
   (``Model History``), pack-mates (``Packed With``), the character and its
   continuity. Names that match your own factions, franchises, tooling and
   categories are selected; nothing is guessed silently. The character page's
   first sentence ("... is an Autobot from the Robots in Disguise continuity
   family") is shown as a hint and fills in a missing faction. A figure the wiki
   describes only in prose under a toyline heading comes through with the
   character's name and no year.
4. **Add figure** saves, in one transaction, the figure plus a character and
   continuity only if they are new, and the references. An existing character is
   reused and never edited. If a figure with the same link is already in the
   collection, it is shown and you must tick "add another copy"; nothing existing is
   ever changed. Ticking "remember" with exactly one franchise selected stores that
   wiki toyline name as an alias, so the next lookup pre-selects the franchise.

The wiki picture is shown (loaded by your browser from tfwiki.net). Nothing is
downloaded unless you press **Use this picture**: the app then downloads that one
file (needs ``TFWIKI_ENABLED``; it waits its turn like a page does, refuses anything
off tfwiki.net or over 10 MB, and stops if the wiki says to slow down) and saves it
as an upload, with its thumbnail, to go with the figure. **Remove this picture**
deletes a downloaded picture that no figure uses yet; a picture a figure already has
is never deleted. A picture you downloaded and then abandoned by leaving the page
stays in the uploads folder until you delete it.

Refreshing a figure from the wiki
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The **Edit Figure** page has a panel using the figure's saved *Link to Figure*
(nothing to paste): **Refresh from TFWiki** looks the link up again, ignoring the
cached copy (needs fetching on); **Compare with the cached copy** uses what is
cached. Either lists what the wiki says that differs, one row per field, and each is
**Accept** or **Skip** on its own. Only accepted changes are saved, in one step, and
only when you press the button.

What it proposes: values the wiki has (it never empties a field, and never removes
anything); additions for franchise, tooling, categories, ancestors and pack-mates (a
franchise the figure already has through a tagged child is not proposed); and
replacements for the name, year, faction, link, accessories and IDs. A wiki name that
is a whole pack containing this figure's name ("Dreadwind & Smokejumper") is not
proposed as a rename, and accessories are compared without regard to capitals. Accept
is pre-selected only where the figure's own value is empty, and never for a picture,
which is a download; a replaced picture's old file stays on disk. If the link matches
several figures you are asked which one is this.

Modernising old links
~~~~~~~~~~~~~~~~~~~~~

Many saved figure links are in the old form ``Name_(G1)#Anchor``; the wiki has
since moved the toys of long character pages to ``Name/toys``.
``flask modernise-links`` rewrites such a link to ``Name/toys#Anchor`` only when
the toys page really has that ``{{anchor}}``, with the same capitals. Anything
else (the page only redirects, the fragment is a heading and not an anchor, the
anchor is on more than one entry, the page or figure is gone) is left alone and
listed with the reason. It changes figures' *Link to Figure* and the links of
their ancestors and pack-mates, and nothing else.

It never fetches by default: it reads the cache (``TFWIKI_CACHE_DIR``) and says
how many pages are missing. Without ``--apply`` it saves nothing::

	flask modernise-links                 # what the cached pages say
	flask modernise-links --apply         # save those rewrites

To fill the cache, set ``TFWIKI_ENABLED = True`` in ``config.py`` (tfwiki.net's
robots.txt disallows automated clients; this is a deliberate, personal, low-rate
use) and run in small batches, each page two seconds after the last (longer with
``TFWIKI_DELAY`` in ``config.py`` or ``--delay SECONDS``; never shorter than two),
cached for good, stopping if the wiki says to slow down::

	flask modernise-links --fetch --limit 50
	flask modernise-links --fetch --limit 50 --delay 5     # gentler

In Docker, ``docker/compose.yml`` mounts ``tfwiki-cache/`` at the repo root; make
it writable first with ``mkdir -p tfwiki-cache && chown 1000 tfwiki-cache``, and
run the command with ``docker compose -f docker/compose.yml exec tfc flask ...``.
Turn ``TFWIKI_ENABLED`` off again afterwards.

Tests
~~~~~

``python -m pytest`` runs against in-memory SQLite. To run them against MariaDB
as CI does, point ``TEST_DATABASE_URI`` at an empty database whose name ends in
``_test`` (the tests refuse any other)::

	TEST_DATABASE_URI='mysql+pymysql://tfc:PASSWORD@127.0.0.1:3309/tfc_test?charset=utf8mb4' python -m pytest

CI also requires 100% line coverage of ``app/`` (``--cov=app --cov-fail-under=100``;
see ``.coveragerc`` for what is not measured: ``migrations/``, ``scripts/`` and
the tests). Check it locally with ``python -m pytest --cov=app --cov-report=term-missing``.

Cutover runbook
~~~~~~~~~~~~~~~

What changes: Figures use *Character* (with its continuity and continuity
family), a *Link to Figure*, *Accessories* as comma-separated text, and *Model
History* / *Packed With* as one ``Name | link`` per line. The TFWikiLinks and
Accessories menus are gone; Characters, Continuities and Continuity Families
replace them. The Figure list can be filtered by character, continuity,
continuity family, ancestor link and accessory text.

1. Stop editing in the app, then ``scripts/backup.sh``. Check both files exist.
2. If anything was edited since the last ``migrate_data_model.py apply``, copy it
   over again, with the same flags, and check it (a hand-set family is kept)::

	docker compose -f docker/compose.yml exec tfc python scripts/migrate_data_model.py apply --again ...
	docker compose -f docker/compose.yml exec tfc python scripts/migrate_data_model.py verify

3. Deploy the new version. The container start runs ``flask db upgrade``
   (``d4f6b8c0e235``: the old character column may be empty).
4. Click through a few figures: one with ancestors and pack-mates (the
   "In collection" and "Other figures from this ancestor" links), Characters,
   Continuities, Continuity Families, and the franchise and continuity filters.
5. To go back, before anyone edits in the new version: redeploy the previous
   image, which reads the untouched old tables. If figures were edited in the new
   version, run ``migrate_data_model.py reverse`` first (from the new image), then
   redeploy the old one; or restore the backup.
6. A few weeks later, the contract PR drops the old tables. Its revision refuses to
   run until ``verify`` has passed.

The permissions of the removed views stay in the database harmlessly.

Continuity full names
~~~~~~~~~~~~~~~~~~~~~

A continuity's name comes from the wiki page suffix (``G1``, ``ROTF``), so it
is often an abbreviation. Its *Full name* is a separate, optional field, shown
in the Continuities list and editable in its form. ``flask set-continuity-names
FILE`` fills them in from lines like ``G1 = Generation 1``; it lists the changes
and saves nothing unless ``--apply`` is given, leaves names that are already
set alone unless ``--overwrite``, and saves nothing if any line is wrong.
``docs/proposals/continuity-names.txt`` is the drafted list. In Docker:
``docker compose -f docker/compose.yml exec -T tfc flask set-continuity-names - --apply < docs/proposals/continuity-names.txt``.

Nested franchises
~~~~~~~~~~~~~~~~~

A franchise can have one parent (Legacy United under Legacy under Generations),
set in the franchise's add and edit forms. Tag a figure with only the lowest
franchise that fits: its page lists the franchises above it too, and filtering
the Figure list by a franchise (or "Search Figures" on the Franchise list) also
finds the figures tagged with anything below it. A franchise cannot go under
itself or one of its own descendants, a tree may be 8 levels deep at most, and
a franchise that still has sub-franchises cannot be deleted.

``flask set-franchise-parents FILE`` sets many parents at once from an indented
list of franchise names (``-`` reads stdin), checking each one like the form does.
It lists the changes and saves nothing unless ``--apply`` is given, and if
anything is wrong it saves nothing at all. ``docs/proposals/franchise-hierarchy.txt``
holds the agreed hierarchy; in Docker, feed it in with
``docker compose -f docker/compose.yml exec -T tfc flask set-franchise-parents - < docs/proposals/franchise-hierarchy.txt``.

Figures already tagged with every level by hand are not harmed. To tidy them
after setting the parents, ``flask prune-franchises`` lists the tags that a
lower tag on the same figure already covers, and changes nothing;
``flask prune-franchises --apply`` removes them. It never runs by itself.

Moving to the new data model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``docs/proposals/data-model.md`` describes the new model (characters,
continuities, per-figure references, accessories as text). The revisions only
*add* tables and columns next to the old ones, and run on deploy like any
revision. Since the cutover the app reads and writes the new structures; the old
tables and columns stay, untouched, for about four weeks, until the contract PR.

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
