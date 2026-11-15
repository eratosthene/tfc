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

Many saved figure links are in the old form ``Name_(G1)#Section``; the wiki has since
moved the toys of long character pages to ``Name/toys``, and renamed other pages
(``Direct-Hit_(G1)`` is now ``Direct-Hit``, ``Doublecrosser`` is now
``Doublecrosser_(Earthrise)``). ``flask modernise-links`` rewrites such a link to the
page the figure is on now, only when that page has the section **by exactly that
name**: an ``{{anchor}}`` or a heading (the wiki gives a heading an id of the same
name), capitals included. A link to a page that is still right is reported as already
current. Anything else is left alone and listed with the reason: the section is only
found ignoring capitals, it is on more than one page, the page or figure is gone, or
the page is not cached. It changes figures' *Link to Figure* and the links of their
ancestors and pack-mates, and nothing else.

Every link the command could not settle is listed with **who uses it** (the figures
whose own link it is, and the figures that list it as an ancestor or pack-mate), so you
can see where it has to be fixed. A link the tools can never work out for themselves (a
wiki page that changed with no redirect, ``Daburu_(TR)#Titans_Return`` becoming
``Daburu#Titans_Return``) is fixed by hand, everywhere it is used, with
``flask replace-link``. Quote both links, since they contain ``(`` and ``#``; without
``--apply`` it only lists what would change::

	flask replace-link 'https://tfwiki.net/wiki/Daburu_(TR)#Titans_Return' 'https://tfwiki.net/wiki/Daburu#Titans_Return'
	flask replace-link 'https://tfwiki.net/wiki/Daburu_(TR)#Titans_Return' 'https://tfwiki.net/wiki/Daburu#Titans_Return' --apply

It changes figures' *Link to Figure* and the links of ancestors and pack-mates that are
exactly the old link (not one that differs in capitals or in its fragment), never fetches,
and, if the new link's page is in the cache, checks that the section is there and warns
if it is not.

A fragment can also be one the wiki *numbered* because a heading repeats on the page:
``Darth_Maul#Star_Wars_Transformers_2`` is the second heading called "Star Wars
Transformers" (the first is under Fiction, the second under Toys). Repeats are counted
across the whole page, the way MediaWiki does, so such a link is matched to the right
section.

A name that has since become a **disambiguation page** (``Battletrap`` now lists
``Battletrap (G1)``, ``(Cyberverse)``, ``(ROTB)``) is followed too: each page it
lists is read, and if exactly one has a section with that exact name (capitals
included), the link is rewritten to that page (``Battletrap_(G1)#Power_of_the_Primes``).
If more than one has it, the link is left alone and the pages are listed; if none
does, it is reported as no figure. Add from TFWiki and the Edit page's refresh follow
a disambiguation the same way. This reads every page the disambiguation page lists
(cached afterwards), so a link like this costs a few requests when fetching is on.

Characters have the same problem: a character's own link names a wiki page that may
since have been renamed (``Alpha_Trion_(G1)`` is now ``Alpha_Trion``) or turned into a
disambiguation page (``Battletrap``). ``flask modernise-characters`` fixes those, with
the same ``--fetch``, ``--limit``, ``--delay``, ``--apply`` and ``--json`` options and
the same rules about the network. A renamed page is rewritten to its current title. A
disambiguation page is rewritten to the page it lists that the character's **own
figures** are on (their links are resolved first, as above), and only if exactly one is;
otherwise it is listed as undecided. A link another character already has is never taken
(it is listed as a conflict, for you to merge by hand), and everything else is left alone
with the reason. It reads one page per character, so on a fresh cache it needs a few
hundred requests; run it in ``--limit`` batches. Run ``modernise-links`` first if you like,
but it is not required.

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

Dropping the old tables
~~~~~~~~~~~~~~~~~~~~~~~

The move to the new data model (``docs/proposals/data-model.md``) has two
halves. The first, long done, added the new structures and copied the data. The
last one, revision ``f6b8d0e2a457``, drops what they replaced: ``tf_wiki_link``,
``accessory``, ``figure_accessory``, ``figure_history``, ``figure_packed_with``,
``figure.figure_link_id`` and the old ``figure.character_id``. It then renames
``character_id_new`` to ``character_id`` (now NOT NULL) and ``accessories_text``
to ``accessories``.

**This cannot be undone from the app.** The downgrade only recreates the empty
tables and columns; the old data comes back from a backup. Because the container
runs ``flask db upgrade`` on start, deploying an image that contains this
revision applies it. So deploy it only when you mean to:

1. Stop editing, then ``scripts/backup.sh``. Check that both files exist.
2. Deploy. The start-up upgrade runs the revision. It refuses, changing nothing,
   if the database holds data and the old ``scripts/migrate_data_model.py
   verify`` was never recorded (the ``data_model_migration`` table), or while any
   figure has no character. A new, empty database upgrades straight through.
3. Click through a few figures (list, show, edit), Characters, the franchise and
   continuity filters, Add from TFWiki and a refresh.
4. To go back, restore the backup (below) and redeploy the previous image.

A URL saved before the change that filters on ``_flt_0_character_new`` now needs
``_flt_0_character``. ``data_model_migration`` (the record of the old copy) and
``legacy_id`` (the MongoDB id of the original rows) stay; either can be dropped in
a later cleanup. The scripts that did the copy (``migrate_data_model.py`` and
``migrate_mongo_to_sql.py``) were removed with the tables they read; they are in
the git history before that change.

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
