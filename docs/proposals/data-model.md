# Proposal: a new data model, a TFWiki-driven Add Figure flow, and the migration

Refs eratosthene/tfc#53. This is a proposal only: no application code or schema
changes in this PR. It rests on the issue text, `app/models.py`, `app/views.py`,
the two Alembic revisions, `scripts/migrate_mongo_to_sql.py`, `scripts/backup.sh`,
and the notes from the abandoned #14 importer (branch `claude/tfwiki-importer-cd621d`,
read for reference only). I have **not** seen the production data, so Section 5
lists what I can only decide once I have.

Contents: 1 Problems · 2 Target model · 3 Add Figure flow · 4 Migration ·
5 Production dump and what it will decide · 6 PR plan · 7 Tests · 8 Risks ·
9 Open questions (all answered; see Decisions)

---

## Decisions (answered by Chris, 11 Nov 2026) and what the production dump showed

| Q | Decision |
|---|---|
| 1 Non-owned figures | No rows; ancestors and pack-mates are per-figure name+link references |
| 2 No-suffix characters | Continuity nullable, left blank for Chris to fill, never guessed |
| 3 Character key | Unique by link |
| 4 Shared figure links | Allowed, with a warning at add time |
| 5 Accessories | **Comma-separated** (not one per line). See the note below on the one name containing commas |
| 6 Franchises | Single parent, tag the lowest level, previewed prune, Claude drafts the hierarchy |
| 7 Wiki images | **Link/preview plus an optional "use this picture" download button** (the button saves into the uploads folder only when clicked; nothing is downloaded by default) |
| 8 Fetching | In the web app, behind `TFWIKI_ENABLED` (default off) |
| 9 Downtime | A few minutes at cutover is fine |
| 10 Old tables | Kept about 4 weeks |
| 11 Fixtures | Yes: the issue's seven pages plus three chosen from the dump: `Omega_Prime` (anchor `Robots_in_Disguise_.282001.29`, percent-style encoding), `Optimus_Prime_(G1)/Generations_toys` (the other toys suffix) and `The_Fallen/toys` (page title differs from the figure's name, "Megatronus the Fallen") |
| 12 `legacy_id` | Left alone |
| 13 Bulk import | **Never wanted.** Removed from the scope entirely, not "later" |

Dump findings (the dump was examined on 11 Nov 2026; nothing was changed):
661 figures, 1480 `tf_wiki_link` rows (927 with `#`, 553 without), 292 of the figure
links already in the new `/toys` form, 71 franchises, 574 accessories, 57 gestalt
rows, 411 history and 597 packed-with rows, 564 distinct links used as history or
packed-with, 150 links not referenced by any figure, 160 of the 553 character links
without a `(X)` suffix, and every link a `tfwiki.net/wiki` URL. Surprises that change
the transform:

- **A link's type must come from how a figure uses it, not from `#`.** Six *character*
  links carry a `#fragment` (e.g. `Squawktalk_(G1)#The_Transformers`,
  `Rumble_(G1)/toys#Vintage_G1`, `Wingspan#Titans_Return`), and one history/pack-mate
  link has none (`Metroplex_(G1)`). The transform therefore classifies by role
  (character, figure link, ancestor, packed-with); a character link's fragment and
  `/toys` suffix are stripped when making the `character.link`, and the original
  string is listed in the report.
- Anchors use MediaWiki's old escaping (`Robots_in_Disguise_.282001.29` means
  "Robots in Disguise (2001)"). Link comparison and display must decode it; stored
  links stay verbatim.
- The `Generations_toys` suffix really occurs, so the parser handles both suffixes.
- Franchise names have no parent/child hints in the data, as expected; the hierarchy
  proposal is a separate step (below).
- Exactly one accessory name contains a comma
  (`Devastator components (waist, breastplate, forearms)/Trailer`). With the comma-separated
  layout this would split into three accessories on `reverse` and in search results. The
  transform stores that entry with its commas intact (searching still finds it) and the
  report names it; `reverse` takes a one-off exception for it, and verification
  compares text, not a re-split list, so nothing is lost.

## 1. What is wrong today

- `tf_wiki_link` is one table holding three different things (characters,
  figures, and "things a figure was derived from or sold with"). Its type is
  *guessed from the URL* (`link_type()`, `__str__`: `#` means figure, `(X)`
  suffix means continuity). Rows exist that Chris does not own, only so
  searches work.
- A figure's `character`, `figure_link`, `history` and `packed_with` all point
  at that same table, so the UI cannot say "pick a character" vs "pick a
  figure".
- Moved wiki pages (`Alpha_Trion_(G1)#Legacy` became `Alpha_Trion/toys#Legacy`)
  silently leave stale rows.
- `accessory` is a many-to-many table of 60-char names with a unique constraint,
  which is heavy for what is a free-form list on the wiki.
- Franchises are flat. Each ancestor franchise is added by hand to each figure.
- `gestalt_of` is *already* `Figure -> Figure` (`figure_gestalt`), so the issue's
  "could just be a list of Figures" is how it works now. It stays; only
  validation is added.

## 2. Target data model

```
continuity_family     id, name (unique), link                 -- the wiki's grouping: Aligned, Generation 1, Robots in Disguise
continuity            id, name (unique), link, family_id -> continuity_family (nullable)
character             id, name, link (unique), continuity_id -> continuity (nullable)
franchise             + parent_id -> franchise (nullable, self-reference)
franchise_alias       id, franchise_id, alias (unique)        -- wiki heading/anchor -> franchise
figure                + link (the exact wiki figure URL), character_id -> character,
                        accessories TEXT; - figure_link_id; - accessories M2M
figure_reference      id, figure_id, kind ('ancestor' | 'packed_with'), position, name, link
figure_gestalt        unchanged (figure_id, gestalt_id, position)
faction, category, tooling   unchanged
```

Removed at the end (Section 6, PR 7): `tf_wiki_link`, `accessory`,
`figure_accessory`, `figure_history`, `figure_packed_with`, `figure.figure_link_id`.

### Decisions and trade-offs

**Accessories: a `Text` column on `figure`.** Comma-separated (Q5, decided). Searchable with FAB's existing "contains"
filter (`LIKE`), which is fine for a personal collection of a few thousand rows;
no FULLTEXT index needed. The old `Accessory` view and its "Search Figures" link
go away; searching accessories happens in the Figure list's filter box.
Trade-off: no per-accessory normalisation ("Rifle" vs "rifle"), accepted because
that was the issue's own judgement and the wiki text is free-form.

**Continuity and Character, each with a link.** `character` means a
character-in-a-continuity (`Bumblebee (Animated)`), as the issue defines it, so
`link` is the wiki page (`https://tfwiki.net/wiki/Bumblebee_(Animated)`) and is
unique. `continuity_id` is nullable because a bare page such as `Boater`
carries no suffix even though its continuity is "Japanese G1"; the wiki URL
cannot tell us, Chris can, in the review step. Continuity names come from the
`(X)` suffixes already in the data (G1, Animated, BW, FOC...) and Chris edits the
names and fills the links.

**The figure link lives on `Figure.link`.** Stored as entered (a full
`https://tfwiki.net/wiki/<page>#<anchor>` URL). Not unique, because Chris may own
two copies in different conditions as two rows (`quantity` exists too).
"Search for this Figure" disappears as a helper, because the figure *is* the row:
the Figure list gets `link` as a searchable column, which finds duplicates.

**History (ancestors) and packed-with: per-figure references, not shared rows,
and no rows for figures Chris does not own.** `figure_reference` stores
`(name, link)` text for each ancestor / pack-mate in order. Rejected
alternatives:

- *A shared `wiki_figure` table of stub rows* recreates today's problem (rows for
  things not owned, kept in sync by hand).
- *Making ancestors real Figures* is wrong; he sells figures, and ancestors are
  usually things he never owned.

Searches still work, by link equality:

- Figure page, History section: each ancestor shows its name as a wiki link,
  plus **"In collection"** if a Figure with that exact `link` exists, plus
  **"Other figures from this ancestor"** (the old "Search for this Ancestor"),
  a Figure list filtered on `figure_reference(kind='ancestor').link == X`
  (small custom FAB filter).
- Cost: a reference to Arcee 2014 appearing on three figures is stored three
  times. Accepted. The bigger risk is that old and new URLs for the same figure
  do not compare equal. Mitigation in PR 7: an optional, previewed
  "modernize links" command that rewrites `Name_(G1)#A` to `Name/toys#A` only
  when the cached `/toys` page really has that anchor.
- `packed_with` is the same table with `kind='packed_with'`. It need not be only
  figures Chris still owns, so rows are plain references too.

**Gestalt.** Unchanged `Figure -> Figure`, plus a soft warning (not an error)
if set on a figure without the Combiner, Duocon or Duobot category, and the show page lists
component figures as links.

**Nested franchises.** `franchise.parent_id` (single parent; a tree, not a graph).

- Chris tags a figure with only the lowest level (`Legacy United`). The *effective*
  franchises are the tagged ones plus all ancestors, computed by a small helper
  and shown in the Figure list/show.
- Filtering a Figure list by a franchise includes its descendants
  (`_flt_0_franchise=Generations` finds Legacy United figures). Franchise list
  "Search Figures" uses the same filter.
- Parent changes validate against cycles (and an arbitrary depth cap of, say, 8).
- Existing figures are tagged with every level by hand today. After Chris sets
  the parents, an explicit, previewed `flask prune-franchises` removes a figure's
  tag when a descendant of it is also on that figure. It never runs on its own.
  Without it nothing is wrong, just redundant.
- `start_year` stays required (as findings noted, this blocks auto-creating
  franchises from toyline headings; the review step will let Chris pick an
  existing one or jump to a "new franchise" form).
- `franchise_alias` maps wiki toyline headings and anchors to a franchise
  (`"The Transformers"` -> `Generation 1`). It is seeded from nothing; the review
  step offers "remember this mapping" and the next import pre-selects it.

**Unchanged on purpose:** `Faction`, `Category`, `Tooling`, `exclusive_to`,
`hasbro_id`, `takara_id`, `condition`, `quantity`, image columns and the uploads
folder.

**Helpers after the change**

| Today | After |
|---|---|
| TFWikiLinks "Search for this Character" | Character list: "Figures" link, `?_flt_0_character=<id>` (a normal FK filter) |
| (none) | Continuity list: "Characters" and "Figures" links (the Figure link needs a small custom join filter, `character.continuity`) |
| "Search for this Figure" | gone; `link` is a search column on Figure |
| "Search for this Ancestor" | on the figure page, as above |
| TFWikiLink view | removed; Character and Continuity views replace it |

---

## 3. How the new Add Figure flow works

A new page **Figures -> Add from TFWiki** (a Flask-AppBuilder `BaseView`, with the
plain "Add Figure" form kept for anything the wiki does not cover). Three steps.

**1. Paste.** Chris pastes e.g. `https://tfwiki.net/wiki/Alpha_Trion/toys#Legacy`.
The server accepts only `https://tfwiki.net/wiki/...` URLs, splits title and
anchor, and normalises. If a character page (`Alpha_Trion_(G1)#Legacy`) is pasted,
it fetches that page, reads the `{{main|...}}` pointer to `/toys` (or
`/Generations_toys`) and follows it, noting that the link moved (the issue's
Alpha Trion example).

**2. Fetch and parse** (no database writes). Through one fetcher, rebuilt from the
reference branch's `Fetcher`, with these rules:

- Off by default: `TFWIKI_ENABLED = False`. robots.txt disallows automated
  clients, so use is an explicit opt-in setting, never an `--ignore-robots`
  trapdoor. The 2 s minimum gap, one request at a time and stop-on-429/503 stay.
- The gap and "stopped" flag are enforced **across the two gunicorn workers**
  with a file lock and a timestamp file in the cache directory (an in-process
  timer, as the old branch had, would let two workers each fetch at once).
- Every response cached on disk by page title (`TFWIKI_CACHE_DIR`, a new volume in
  `docker/compose.yml`), never refetched without an explicit "Refresh from wiki"
  button, honest `User-Agent` with the repo URL.
- A paste costs at most three requests (the figure page, the character page for
  continuity if not cached, and a redirect target), so about 6 s the first time and
  none after.
- Attribution: we store facts and links, not article text; the page footer says
  data is from TFWiki (CC BY-SA 3.0).

Parsing (pure functions, tested on recorded wikitext fixtures), per the findings:

- Find the figure's block: the `{{anchor|X}}` matching the URL fragment (a
  `Legacy` anchor is not unique across franchises, so if several blocks share
  it the review step lists them and Chris picks), else the toyline heading.
  Take everything up to the next anchor / `<ul class="iconlist">`.
- **Name:** the `'''Name'''` in the `Bp-xx` line. Strip a leading faction word
  *only if it matches a known Faction name or the faction implied by the template
  code* (`Autobot Blaster` -> `Blaster`); anything else stays (`Animated Universe
  Bumblebee`).
- **Faction:** first the `Bp-` code (`a1`, `d1`, ...; mapping table to be confirmed
  against real pages, I verified only a handful), then the stripped prefix word,
  then faction symbol images in the block (`[[File:...symbol...]]`, mapped through
  an editable `faction.wiki_symbol` list), else left blank for Chris. Never guessed
  silently: each suggestion shows where it came from.
- **Release year:** first year in the parentheses (ignoring `<s>` strikes and
  wikilinked years); **Class** is offered as a Category suggestion.
- **Accessories / Hasbro ID / Takara ID:** from the labelled bullets (labels vary
  in case and colons, as noted).
- **Tooling and ancestors:** wikilinks to `.../toys#...` inside sentences with
  keywords (redeco, retool, remold, reissue, rerelease, "based on"), with the
  keyword giving a Tooling suggestion. This is heuristic. The raw paragraph is
  shown beside the form so Chris can correct it, and "New" tooling means no
  ancestors.
- **Packed with:** other figure anchors/links in a multi-pack entry.
- **Continuity and character:** from the `Name_(X)` page title when it has a
  suffix, otherwise unset (see Q2). Character match is by link; an existing
  Character is reused, never edited.
- **Faction and continuity family:** a character page's lead sentence ("Omega Prime is an [[Autobot]] ... from the [[Robots in Disguise continuity family]]"; "... the Fall of Cybertron portion of the [[Aligned continuity family]]") gives a faction and a family, and often a portion (era). Both are wiki links, so they are read as suggestions with the sentence shown, never saved unseen. The family is stored on `continuity_family`; a portion is matched to one of our continuities by Chris. This can also suggest a continuity for a character with no `(X)` suffix, such as Boater ("Victory era of the Generation 1 continuity family").
- **Franchise:** toyline heading, else anchor, looked up in `franchise_alias`,
  then by exact name; unmatched stays blank. Neither the anchor nor the heading
  is trusted to equal a franchise name.
- **Picture:** the first `File:` link in the block, shown as a link and a preview
  *hot-linked from the wiki page*. Nothing is downloaded or stored unless Chris
  clicks "use this picture", which saves that one image into the uploads folder
  through the normal image column; or he uploads his own photo in the review form.
  Images stay under his control.

**3. Review, then save.** One pre-filled form showing every field with its
source and a confidence hint ("from Bp-a1", "guessed from sentence"), the raw
wiki block alongside, and anything unparsed highlighted. Saving, in a single
transaction:

- creates the Figure and any *new* Character/Continuity/FigureReference rows;
- never updates an existing row. If a Figure with the same `link` exists, the
  page shows it and offers "add another copy" (a new row) or cancel; it does not
  merge, update, or overwrite anything entered by hand;
- stores `name`/`link` references for ancestors and pack-mates exactly as shown.

Edits afterwards use the normal edit form. There is no bulk import ("import all of
Bumblebee's 40 figures"); Chris does not want one.

---

## 4. The migration

### Principles

- **Expand, backfill, switch, contract.** New structures are added next to the old
  ones; data is copied; the app is switched; old structures are dropped last and
  separately. At no point before the final PR does the migration delete anything.
- The container runs `flask db upgrade` on every start
  (`docker/docker-entrypoint.sh`), so **any Alembic revision shipped is applied
  automatically on deploy.** Therefore revisions that ship before the cutover are
  purely additive (safe to run unattended), and the data copy is a separate,
  explicit script that Chris runs by hand after a backup. Only the final contract
  revision (which drops tables) is guarded: it refuses to run unless a
  `data_model_migration` marker row says `verify` passed.
- **Backup first, always.** `scripts/backup.sh` (DB dump plus uploads archive)
  before every step below. Restore steps are in the README; the cutover runbook
  repeats them.

### Alembic revisions

| # | Revision | What it does | Downgrade |
|---|---|---|---|
| E | `expand_data_model` | Create `continuity`, `character`, `figure_reference`, `franchise_alias`, `data_model_migration`; add `franchise.parent_id`, `figure.link`, `figure.character_id_new`, `figure.accessories_text`. Additive only, all nullable. | Drops what it created. |
| F | `add_continuity_family` | Create `continuity_family`; add `continuity.family_id` (nullable). Additive only, added after E when the wiki's lead sentences showed the grouping. | Drops both. |
| C | `contract_data_model` (PR 7) | Guard, then drop `figure_link_id`, `figure_history`, `figure_packed_with`, `figure_accessory`, `accessory`, `tf_wiki_link`; rename the `_new`/`_text` columns to their final names; make `character_id` `NOT NULL` | Recreates the *structure*; data comes back with `reverse` or a restore. After C, rollback is a backup restore, and I say so in the PR. |

Existing safety nets reused: `tests/test_migrations.py` already checks that
`flask db upgrade` builds exactly the models' schema (`compare_metadata`).

### The data script: `scripts/migrate_data_model.py`

Modelled on `scripts/migrate_mongo_to_sql.py` (same subcommand style, same
reporting habits). Idempotent, inside a transaction, one command per job:

```
migrate_data_model.py dry-run   # run the whole transform in a transaction, print the plan and
                                # the "needs review" lists, then ROLL BACK
migrate_data_model.py apply     # same, then COMMIT; refuses if verify of the plan finds a problem
migrate_data_model.py verify    # compare old and new structures; exit non-zero on any mismatch
migrate_data_model.py reverse   # rebuild the old structures from the new ones, then verify again
```

The transform:

1. **Classify each `tf_wiki_link` by the role it plays**, not by its URL: used as a
   figure's `character_id` -> character; as `figure_link_id` -> figure link; in
   `figure_history` / `figure_packed_with` -> reference. A link used in two roles is
   fine and is reported. Rows whose URL is not `tfwiki.net/wiki/...` are flagged
   (none in the current dump).
2. **Continuities:** distinct `(X)` suffixes of character links become `continuity`
   rows (name = X; link blank for Chris to fill). The dump has about 30 distinct
   suffixes (G1, Armada, SG, RID, Cyberverse, BW, Movie, G2, BM, ...), some of them not
   continuities (`facility`, `species`), so the review list shows each with its
   characters before anything is created.
3. **Characters:** one `character` row per distinct link used by a figure's
   `character_id`, `name` from the old row, `continuity` from the suffix (or
   NULL, reported). Figures' `character_id_new` set.
4. **Figure link:** `figure.link` = the old `figure_link` row's `link`, verbatim.
   Not rewritten and not fetched.
5. **History and packed-with:** each `figure_history` / `figure_packed_with` row
   becomes a `figure_reference(kind, position, name, link)`, copying `position`.
6. **Accessories:** each figure's accessories, in `position` order, joined with
   the chosen separator into `accessories_text`. Names containing the separator
   are reported (they would split wrongly on `reverse`; the dry-run will tell us
   if any exist and the separator can be changed before apply).
7. **Franchise parents:** left NULL. We cannot infer the hierarchy from data;
   Chris sets it in the UI (or I generate a one-off SQL from his answers after
   the dump review).
8. Everything else (`faction`, `category`, `tooling`, `figure_gestalt`,
   `figure_franchise`, `figure_tooling`, `figure_category`, images,
   `exclusive_to`, ids, `condition`, `quantity`) is untouched; the figure row is
   updated in place, never recreated, so ids and uploads filenames never change.
   Unreferenced `tf_wiki_link` rows (the ones Chris added just to enable search)
   are *not* migrated. They are listed, and their count is in the report. The old
   table stays until contract.

### Verification

`verify` produces a text and JSON report (written next to the backup) and fails
loudly:

- **Row counts:** `figure` before = after (the figure count is the headline
  number), and per table: faction, category, tooling, franchise unchanged;
  distinct character links used = `character` rows; `figure_history` rows =
  `figure_reference(ancestor)` rows; likewise packed-with; figures with
  accessories = figures with non-empty `accessories_text`.
- **Field-level, every figure:** `name`, `release_year`, `image`, `faction_id`,
  `exclusive_to`, `hasbro_id`, `takara_id`, `condition`, `quantity`; franchise,
  tooling, category and gestalt id lists **in order**; `figure.link` equals the old
  link; `character.link` equals the old character link; ancestors and pack-mates
  equal the old links in order; accessories text, split back, equals the old
  accessory names in order. Any difference is printed with the figure id and name.
- **Files:** each `figure.image` / `faction.image` / `franchise.image` filename
  exists in the uploads folder (reported, never changed).
- **Round trip:** a test (and, on request, a staging run on the dump) does
  `apply -> reverse -> verify` and compares a stable checksum of every old table
  before and after.
- Records its success in `data_model_migration`, which the contract revision checks.

### Cutover runbook (documented in the PR that switches the app)

1. `scripts/backup.sh`; confirm both files exist and are non-empty.
2. Stop the app (`docker/live-down.sh`); run the expand revision if not yet applied.
3. `migrate_data_model.py dry-run`; read the review lists with Chris.
4. `apply`, then `verify`; keep the report.
5. Start the new app version; click through a handful of figures.
6. Roll back by `reverse` plus the previous image, or restore the backup.
7. A few weeks later, ship the contract PR.

Downtime is a few minutes (single user, one server); the app is not written to
between `apply` and the switch, so there is no write-skew to reconcile.

---

## 5. Production dump, and what only the real data can settle

I cannot and will not touch production. Exact steps for the home server (from the
repo checkout; `backups/` is git-ignored). The uploads folder holds the image files;
the database holds only their file names, so the dump contains **no images**. The
listing in step 3 covers them.

1. Take the normal backup first:
   ```bash
   scripts/backup.sh
   ```
2. Dump only the app's own tables, **not** the Flask-AppBuilder user/role tables
   (they hold password hashes). Pick the variant that matches the server:
   ```bash
   # a) database in the compose stack (dev stack)
   docker compose -f docker/compose.dev.yml exec -T db sh -c '. /db-env.sh; exec mariadb-dump --single-transaction --skip-comments -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" accessory category faction figure figure_accessory figure_category figure_franchise figure_gestalt figure_history figure_packed_with figure_tooling franchise tf_wiki_link tooling alembic_version' > backups/tfc-data-for-review.sql
   ```
   ```bash
   # b) the server's own MariaDB (what docker/.env points at); fill in USER, HOST, DBNAME
   MYSQL_PWD='<password>' mariadb-dump --single-transaction --skip-comments -h HOST -u USER DBNAME accessory category faction figure figure_accessory figure_category figure_franchise figure_gestalt figure_history figure_packed_with figure_tooling franchise tf_wiki_link tooling alembic_version > backups/tfc-data-for-review.sql
   ```
   (use `mysqldump` if `mariadb-dump` is not installed).
3. Record the uploads folder contents without the images:
   ```bash
   ls -l uploads > backups/uploads-listing.txt
   ```
4. Sanity check, and share the counts:
   ```bash
   grep -c '^INSERT INTO `figure` ' backups/tfc-data-for-review.sql
   wc -c backups/tfc-data-for-review.sql
   ```
5. Put `backups/tfc-data-for-review.sql` and `backups/uploads-listing.txt` where I
   can read them (the repo's git-ignored `backups/` folder in a worktree, or the
   shared notes folder). No password, key or `config.py` is in them. Check with
   `grep -il password backups/tfc-data-for-review.sql` (expect no output).

I then load it into the throwaway test MariaDB, never anything shared, and run
`dry-run` on it.

**Only the real data decides:**

- How many figures, links and franchises there are; the figure count that must not
  change.
- How many `tf_wiki_link` rows are characters vs figures; how many have no `(X)`
  suffix (so need a continuity from Chris); which URLs are not `tfwiki.net/wiki`.
- The real continuity list, and whether some characters appear under two links.
- How many links are still the pre-split form (`Name_(G1)#X` vs `Name/toys#X`), which
  decides how much the "modernize links" command matters (and needs a few cached
  wiki requests to check, only with approval).
- Accessory names containing commas (the separator choice) and near-duplicates
  (`Rifle`/`rifle`).
- Unreferenced links (what the "needs review" list will actually contain).
- Whether any ancestor/pack-mate links point at pages that are not figure links.
- The franchise hierarchy to seed (I propose a parent for each of the franchises, and
  Chris fixes it).
- Whether gestalt data is consistent with the Combiner category.
- Whether `legacy_id` columns are populated, and uploads filenames that do not exist.

---

## 6. Implementation plan: separately mergeable PRs

Order matters mainly in that the migration PRs wait for the dump. Each PR keeps
the 100 % line coverage gate (`app/` only; `scripts/` are tested separately).

1. **TFWiki fetcher and parser** (no schema, no UI). Cross-worker throttle,
   cache, opt-in setting, wikitext parser, recorded fixtures (from the reference
   branch, plus the issue's seven pages and the three from the dump named above, about
   10 requests, 2 s apart, approved). Can start immediately and be
   reviewed on its own.
2. **Expand schema + models + data script.** Revision E and the new models (unused
   by the views), `scripts/migrate_data_model.py` (`dry-run`, `apply`, `verify`,
   `reverse`), seed-data tests. Written after I have seen the dump, so the transform
   covers what is really there.
3. **Nested franchises.** Parent field in the Franchise add/edit forms, cycle check,
   effective-franchise helper, descendant-aware filters, `flask prune-franchises`
   (dry-run first). Independent of the rest; depends only on revision E's column,
   so it can go before or after 2.
4. **Cutover.** Views and models read the new structures (Character and Continuity
   views, `Figure.link`, accessories text search, history/packed-with from
   `figure_reference`, ancestor search filter, continuity filter), removes the
   TFWikiLink view and the Accessory view, the cutover runbook in the README.
   Deployed with the Section 4 steps.
5. **Add from TFWiki.** The three-step page of Section 3, `franchise_alias`, the
   faction symbol list, the cache volume.
6. **Link modernisation** (optional; the dump has 292 of 927 figure links already in the `/toys` form, so most are old-style): "check/modernize links", previewed, using only
   the cache and approved fetches.
7. **Contract.** Guarded revision C, delete old models and scripts' old paths,
   README cleanup. Ships weeks after PR 4 once Chris is satisfied.

PRs 1 and 3 can proceed in parallel with the dump round trip; 4 needs 2; 5 needs
1 and 4.

## 7. Test strategy

- **Parser/fetcher:** pure-function tests on recorded wikitext; fake `get`/`sleep`/
  `clock` (the old branch's pattern) so nothing touches the network or waits; a
  two-process test for the file lock; 429/503 stops; opt-in off by default.
- **Migration script:** build the *old* schema at revision `a1c3e5f7b902`, seed a
  fixture with every awkward case (no-suffix characters, duplicate links, comma
  accessory, orphan links, empty lists, unicode names), run E, `dry-run` (assert
  nothing changed), `apply`, `verify` passes, `reverse` then compares checksums of
  every old table. A negative test corrupts one field and asserts `verify` fails.
  These run on MariaDB in CI (like `tests/test_migrations.py`).
- **Models/views:** effective-franchise ancestors and cycle rejection, descendant
  filter, ancestor/continuity custom filters, helpers' links, Add-from-TFWiki flow
  end to end (paste -> preview -> save) with fixtures, duplicate-link refusal, "never
  overwrites" assertions, CSRF and URL validation (only `tfwiki.net`).
- `scripts/` stays outside coverage (as `.coveragerc` says), so its tests carry the
  assertions; everything under `app/` stays at 100 %.

## 8. Risks

- **Parser heuristics are wrong sometimes.** Mitigated by the review step: nothing
  auto-saves, every guess shows its source and the raw block.
- **TFWiki changes layout or blocks us.** Everything cached; manual entry still works;
  throttling and stop-on-429 limit exposure. Robots.txt disallows clients, so this
  stays opt-in and low-rate by design.
- **Migration surprises in real data.** That is why the dump comes first and the
  script has `dry-run` and `verify`.
- **Entrypoint auto-migrates.** Pre-cutover revisions are additive; the destructive
  one is guarded.
- **Old vs new URLs not comparing equal** (ancestor search). PR 6 plus visible
  "In collection" fallback.
- **FAB custom filters** (continuity, ancestor, descendants) are the least
  conventional code; small and tested.
- **Franchise hierarchy errors** affect filtering only; `prune` is never automatic.
- **Contract is the point of no return;** it is separate, guarded and delayed.

## 9. Open questions

All thirteen were answered; see "Decisions" at the top. Still open, to settle on the
real data during PR 2:

1. The continuity names (about 30 suffixes in the dump, some not real continuities) and
   which characters need one filled in; 160 characters have no suffix.
2. The franchise hierarchy for the 71 franchises (a draft will be proposed for Chris to
   correct).
3. The 150 unreferenced links (not migrated): confirm they can be left behind in the
   old table until the contract PR.
