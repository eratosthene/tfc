#!/usr/bin/env python
"""One-time migration of TFC's data from MongoDB to MariaDB (sub-issue #8).

ALREADY RUN? This script is kept for the record, and so a later cleanup can use
the ``legacy_id`` columns. See "Migrating the Mongo data" in README.rst for how
to run it, and what to check, before the mongo service goes.

It reads the old ``tfc`` Mongo database (collections and GridFS images, as
mongoengine wrote them) and writes the tables from app/models.py:

* lookup tables (franchise, faction, tooling, accessory, category), then
  TFWikiLink, then Figure, then the figure association rows, in that order;
* every row gets the Mongo ObjectId in ``legacy_id``, and is upserted on it, so
  a re-run updates rows rather than duplicating them;
* each GridFS image is written, byte for byte, to the upload folder as
  ``<uuid>_sep_<name>``, the scheme the app uses on upload, and its thumbnail
  is made by Flask-AppBuilder's ImageManager, the code the app uses. The file's
  length and SHA-256 are checked against the GridFS source;
* a verification report compares counts, every field, every list and every
  image with Mongo, and prints figures to spot-check in the UI.

Nothing is written to Mongo. ``--dry-run`` writes nothing to MariaDB or the
upload folder either (importing the app does what any app start does: it makes
Flask-AppBuilder's own ab_* tables if they are missing). The exit status is 0
only if the run, and the verification, found nothing wrong.

Run it where the app's config.py and Mongo are both reachable, normally with
docker/compose.migrate.yml:

    docker compose -f docker/compose.migrate.yml run --rm migrate --dry-run
    docker compose -f docker/compose.migrate.yml run --rm migrate
    docker compose -f docker/compose.migrate.yml run --rm migrate --verify-only
"""

import argparse
import hashlib
import io
import logging
import os
import random
import sys
import uuid
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gridfs  # noqa: E402
from bson import DBRef  # noqa: E402
from flask_appbuilder.filemanager import ImageManager, thumbgen_filename  # noqa: E402
from PIL import Image  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402

from app import app, db  # noqa: E402
from app.models import (  # noqa: E402
    Accessory,
    Category,
    Faction,
    Figure,
    Franchise,
    Tooling,
    TFWikiLink,
    figure_accessory,
    figure_category,
    figure_franchise,
    figure_gestalt,
    figure_history,
    figure_packed_with,
    figure_tooling,
)

# mongoengine names a collection from the class name, with an underscore before
# each capital: TFWikiLink became t_f_wiki_link. The other spellings are in case
# it was ever renamed.
SPECS = OrderedDict(
    (s["key"], s)
    for s in [
        dict(
            key="franchise",
            model=Franchise,
            collections=["franchise"],
            fields=["name", "link", "start_year", "end_year"],
            bucket="franchise_images",
        ),
        dict(
            key="faction",
            model=Faction,
            collections=["faction"],
            fields=["name"],
            bucket="faction_images",
        ),
        dict(key="tooling", model=Tooling, collections=["tooling"], fields=["name"]),
        dict(
            key="accessory",
            model=Accessory,
            collections=["accessory"],
            fields=["name"],
        ),
        dict(key="category", model=Category, collections=["category"], fields=["name"]),
        dict(
            key="tf_wiki_link",
            model=TFWikiLink,
            collections=["t_f_wiki_link", "tf_wiki_link", "tfwiki_link"],
            fields=["name", "link"],
        ),
        dict(
            key="figure",
            model=Figure,
            collections=["figure"],
            fields=[
                "name",
                "release_year",
                "exclusive_to",
                "hasbro_id",
                "takara_id",
                "condition",
                "quantity",
            ],
            bucket="figure_images",
        ),
    ]
)

# Figure's single references: Mongo field -> (SQL column, target collection key,
# required). A required one that points at nothing leaves the figure out.
FIGURE_REFS = [
    ("figure_link", "figure_link_id", "tf_wiki_link", False),
    ("character", "character_id", "tf_wiki_link", True),
    ("faction", "faction_id", "faction", True),
]

# Figure's lists: (Mongo field, association table, its right-hand column,
# target collection key). The row order in the list becomes ``position``.
FIGURE_LISTS = [
    ("franchise", figure_franchise, "franchise_id", "franchise"),
    ("tooling", figure_tooling, "tooling_id", "tooling"),
    ("history", figure_history, "tf_wiki_link_id", "tf_wiki_link"),
    ("packed_with", figure_packed_with, "tf_wiki_link_id", "tf_wiki_link"),
    ("gestalt_of", figure_gestalt, "gestalt_id", "figure"),
    ("accessories", figure_accessory, "accessory_id", "accessory"),
    ("categories", figure_category, "category_id", "category"),
]

EXT = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "TIFF": ".tiff"}


def oid(value):
    """A Mongo reference or id as its 24-character string."""
    if isinstance(value, DBRef):
        value = value.id
    return None if value is None else str(value)


def image_id(doc):
    """The GridFS file id in a document's ``image`` field, or None."""
    v = doc.get("image")
    if isinstance(v, dict):
        v = v.get("grid_id") or v.get("_id")
    return v or None


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class Data:
    """One Mongo collection, read whole (the data is small), plus its findings."""

    def __init__(self, spec, name, docs, fs):
        self.spec, self.name, self.docs, self.fs = spec, name, docs, fs
        self.bad = {}  # legacy_id -> why the document is left out
        self.ids = {oid(d["_id"]) for d in docs}

    @property
    def valid(self):
        return self.ids - set(self.bad)


class Run:
    """What happened, in the words of the report."""

    def __init__(self):
        self.problems = []  # things that make the exit status non-zero
        self.warnings = []  # fixed up on the way, worth knowing
        self.mismatches = []  # verification differences

    def problem(self, msg):
        self.problems.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def read_mongo(mdb, run):
    names = set(mdb.list_collection_names())
    data = OrderedDict()
    for key, spec in SPECS.items():
        name = next((c for c in spec["collections"] if c in names), None)
        if name is None:
            run.problem(
                "no Mongo collection for %s (looked for %s; found %s)"
                % (key, ", ".join(spec["collections"]), ", ".join(sorted(names)))
            )
            data[key] = Data(spec, spec["collections"][0], [], None)
            continue
        docs = list(mdb[name].find().sort("_id", 1))
        fs = gridfs.GridFS(mdb, collection=spec["bucket"]) if "bucket" in spec else None
        data[key] = Data(spec, name, docs, fs)
    return data


def check_documents(data, run):
    """Find documents that cannot be migrated, and references that point at nothing."""
    for key, d in data.items():
        cols = d.spec["model"].__table__.c
        for doc in d.docs:
            lid, why = oid(doc["_id"]), []
            for f in d.spec["fields"]:
                col, v = cols[f], doc.get(f)
                if v is None:
                    if not col.nullable and col.default is None:
                        why.append("%s is missing" % f)
                    continue
                if col.type.python_type is int:
                    try:
                        int(v)
                    except (TypeError, ValueError):
                        why.append("%s=%r is not a number" % (f, v))
                elif (
                    getattr(col.type, "length", None) and len(str(v)) > col.type.length
                ):
                    why.append(
                        "%s is %d characters; the column holds %d"
                        % (f, len(str(v)), col.type.length)
                    )
            if why:
                d.bad[lid] = "; ".join(why)
    # References, now that every collection's bad documents are known. Figures
    # can point at figures (gestalt_of), so each pass is repeated until nothing
    # more is left out.
    fig = data["figure"]
    changed = True
    while changed:
        changed = False
        for doc in fig.docs:
            lid = oid(doc["_id"])
            if lid in fig.bad:
                continue
            for f, _col, target, required in FIGURE_REFS:
                ref = oid(doc.get(f))
                if required and ref is None:
                    fig.bad[lid] = "%s is missing" % f
                elif required and ref not in data[target].valid:
                    fig.bad[lid] = "%s %s is not in %s" % (f, ref, data[target].name)
                if lid in fig.bad:
                    changed = True
                    break
    for key, d in data.items():
        for lid, why in sorted(d.bad.items()):
            run.problem("%s %s left out: %s" % (d.name, lid, why))
    for doc in fig.docs:
        lid = oid(doc["_id"])
        if lid in fig.bad:
            continue
        ref = oid(doc.get("figure_link"))
        if ref is not None and ref not in data["tf_wiki_link"].valid:
            run.warn(
                "figure %s: figure_link %s points at nothing; dropped" % (lid, ref)
            )
        for f, _t, _c, target in FIGURE_LISTS:
            seen = set()
            for v in doc.get(f) or []:
                ref = oid(v)
                if ref not in data[target].valid:
                    run.warn(
                        "figure %s: %s entry %s points at nothing; dropped"
                        % (lid, f, ref)
                    )
                elif ref in seen:
                    run.warn("figure %s: %s lists %s twice; kept once" % (lid, f, ref))
                seen.add(ref)


def list_targets(doc, field, target, data):
    """The ids in a figure's list that migrate, in order, once each."""
    out = []
    for v in doc.get(field) or []:
        ref = oid(v)
        if ref in data[target].valid and ref not in out:
            out.append(ref)
    return out


def read_image(d, doc, run, what):
    """(bytes, GridOut) for a document's GridFS image, or None (with a problem)."""
    gid = image_id(doc)
    if gid is None:
        return None
    try:
        out = d.fs.get(gid)
        data = out.read()
    except gridfs.errors.NoFile:
        run.problem("%s: image %s is not in GridFS" % (what, gid))
        return None
    if out.length != len(data):
        run.problem(
            "%s: GridFS says %d bytes but %d were read" % (what, out.length, len(data))
        )
        return None
    return data, out


def open_image(data):
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def image_filename(d, doc, out, img):
    """``<uuid>_sep_<name>``, as FAB's uuid_namegen makes it on upload."""
    base = secure_filename(os.path.basename(getattr(out, "filename", None) or ""))
    root = os.path.splitext(base)[0] or "%s-%s" % (d.spec["key"], oid(doc["_id"]))
    return "%s_sep_%s%s" % (uuid.uuid1(), root, EXT.get(img.format, ".jpg"))


def write_image(folder, thumb_size, filename, data, img):
    """Write the original unchanged, then its thumbnail by the app's own code."""
    path = os.path.join(folder, filename)
    os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    fmt = img.format if img.format in EXT else "JPEG"
    if fmt == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")  # the app's save_image cannot write RGBA JPEGs
    # No app context of its own here: leaving one would end the session, and
    # with it the rows that are flushed but not yet committed.
    m = ImageManager(base_path=folder, thumbnail_size=thumb_size)
    m.image = img
    m.save_thumbnail(None, filename, fmt, thumb_size)
    return path


def check_file(folder, name, length, digest):
    """None if the file on disk is the source, else why not."""
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        return "file %s is missing" % name
    with open(path, "rb") as fh:
        body = fh.read()
    if len(body) != length:
        return "%s is %d bytes, source is %d" % (name, len(body), length)
    if sha256(body) != digest:
        return "%s does not match the source SHA-256" % name
    return None


def migrate_images(d, objs, folder, run, written, replaced):
    """Write each document's image, unless the right file is already there."""
    n = skipped = 0
    thumb_size = d.spec["model"].__table__.c.image.type.thumbnail_size
    for doc in d.docs:
        lid = oid(doc["_id"])
        if lid in d.bad or image_id(doc) is None:
            continue
        what = "%s %s" % (d.name, lid)
        got = read_image(d, doc, run, what)
        if got is None:
            continue
        data, out = got
        obj = objs[lid]
        if obj.image and check_file(folder, obj.image, len(data), sha256(data)) is None:
            skipped += 1
            continue
        try:
            img = open_image(data)
            if img.format not in EXT:
                raise ValueError("format %s is not one the app takes" % img.format)
            name = image_filename(d, doc, out, img)
            write_image(folder, thumb_size, name, data, img)
        except Exception as e:  # a bad image is reported, and the rest go on
            run.problem("%s: image could not be written: %s" % (what, e))
            continue
        written.append(name)
        why = check_file(folder, name, len(data), sha256(data))
        if why:
            run.problem("%s: %s" % (what, why))
            continue
        if obj.image:
            replaced.append(obj.image)
        obj.image = name
        n += 1
    return n, skipped


def migrate(data, folder, run, dry_run):
    """Upsert everything in dependency order. Returns the per-collection tally."""
    session = db.session
    objs, tally = {}, OrderedDict()
    written, replaced = [], []
    try:
        for key, d in data.items():
            model = d.spec["model"]
            existing = {
                o.legacy_id: o
                for o in session.query(model).filter(model.legacy_id.isnot(None))
            }
            objs[key] = {}
            new = upd = 0
            for doc in d.docs:
                lid = oid(doc["_id"])
                if lid in d.bad:
                    continue
                obj = existing.get(lid)
                if obj is None:
                    new += 1
                    if dry_run:
                        continue
                    obj = model(legacy_id=lid)
                    session.add(obj)
                else:
                    upd += 1
                objs[key][lid] = obj
                if dry_run:
                    continue
                for f in d.spec["fields"]:
                    v = doc.get(f)
                    if v is None and f == "quantity":
                        v = 1
                    if v is not None and model.__table__.c[f].type.python_type is int:
                        v = int(v)
                    setattr(obj, f, v)
                if key == "figure":
                    for f, col, target, _req in FIGURE_REFS:
                        ref = oid(doc.get(f))
                        setattr(
                            obj,
                            col,
                            objs[target][ref].id if ref in data[target].valid else None,
                        )
            if not dry_run:
                session.flush()
            tally[key] = {"new": new, "updated": upd, "images": 0, "unchanged": 0}
            if "bucket" in d.spec:
                if dry_run:
                    n = 0
                    for doc in d.docs:
                        if oid(doc["_id"]) in d.bad or image_id(doc) is None:
                            continue
                        got = read_image(
                            d, doc, run, "%s %s" % (d.name, oid(doc["_id"]))
                        )
                        if got is None:
                            continue
                        try:
                            open_image(got[0])
                            n += 1
                        except Exception as e:
                            run.problem(
                                "%s %s: image cannot be read: %s"
                                % (d.name, oid(doc["_id"]), e)
                            )
                    tally[key]["images"] = n
                else:
                    n, skipped = migrate_images(
                        d, objs[key], folder, run, written, replaced
                    )
                    tally[key]["images"], tally[key]["unchanged"] = n, skipped
                    session.flush()
        if not dry_run:
            fig = data["figure"]
            for doc in fig.docs:
                lid = oid(doc["_id"])
                if lid in fig.bad:
                    continue
                fid = objs["figure"][lid].id
                for f, table, rcol, target in FIGURE_LISTS:
                    session.execute(table.delete().where(table.c.figure_id == fid))
                    rows = [
                        {"figure_id": fid, rcol: objs[target][ref].id, "position": pos}
                        for pos, ref in enumerate(list_targets(doc, f, target, data))
                    ]
                    if rows:
                        session.execute(table.insert(), rows)
            # Documents that could not migrate are left out and reported; the
            # rest is committed, and a re-run after a fix fills the gaps.
            session.commit()
            for name in replaced:
                for n in (name, thumbgen_filename(name)):
                    p = os.path.join(folder, n)
                    if os.path.exists(p):
                        os.remove(p)
    except Exception:
        session.rollback()
        for name in written:
            for n in (name, thumbgen_filename(name)):
                p = os.path.join(folder, n)
                if os.path.exists(p):
                    os.remove(p)
        raise
    return tally


def verify(data, folder, run):
    """Compare MariaDB with Mongo. Returns (rows, assoc_rows, image_summary)."""
    session = db.session
    session.expire_all()
    rows, per_key = [], {}
    for key, d in data.items():
        model = d.spec["model"]
        sql = {
            o.legacy_id: o
            for o in session.query(model).filter(model.legacy_id.isnot(None))
        }
        per_key[key] = sql
        sql_n = len(sql)
        rows.append((d.name, len(d.docs), sql_n))
        if len(d.docs) != sql_n:
            run.mismatches.append(
                "%s: %d in Mongo, %d in MariaDB" % (d.name, len(d.docs), sql_n)
            )
        for lid in sorted(set(sql) - d.ids):
            run.mismatches.append("%s: MariaDB row %s is not in Mongo" % (d.name, lid))
        for doc in d.docs:
            lid = oid(doc["_id"])
            obj = sql.get(lid)
            if obj is None:
                continue
            what = "%s %s" % (d.name, lid)
            for f in d.spec["fields"]:
                want = doc.get(f)
                if want is None and f == "quantity":
                    want = 1
                got = getattr(obj, f)
                if want is not None and isinstance(got, int):
                    want = int(want)
                if got != want:
                    run.mismatches.append(
                        "%s: %s is %r, Mongo has %r" % (what, f, got, want)
                    )
    fig = data["figure"]
    for doc in fig.docs:
        lid = oid(doc["_id"])
        obj = per_key["figure"].get(lid)
        if obj is None:
            continue
        what = "figure %s" % lid
        for f, col, target, _req in FIGURE_REFS:
            want = oid(doc.get(f))
            if want not in data[target].valid:
                want = None  # points at nothing: dropped, with a warning
            rel = getattr(obj, f)
            got = rel.legacy_id if rel is not None else None
            if got != want:
                run.mismatches.append(
                    "%s: %s is %s, Mongo has %s" % (what, f, got, want)
                )
        for f, _t, _c, target in FIGURE_LISTS:
            want = list_targets(doc, f, target, data)
            got = [x.legacy_id for x in getattr(obj, f)]
            if got != want:
                run.mismatches.append(
                    "%s: %s is %s, Mongo has %s" % (what, f, got, want)
                )
    assoc = []
    for f, table, _rcol, target in FIGURE_LISTS:
        mongo_n = sum(
            len(list_targets(doc, f, target, data))
            for doc in fig.docs
            if oid(doc["_id"]) not in fig.bad
        )
        sql_n = session.execute(
            table.select()
            .with_only_columns(db.func.count())
            .select_from(table.join(Figure.__table__, table.c.figure_id == Figure.id))
            .where(Figure.legacy_id.isnot(None))
        ).scalar()
        assoc.append((table.name, mongo_n, sql_n))
        if mongo_n != sql_n:
            run.mismatches.append(
                "%s: %d entries in Mongo, %d rows in MariaDB"
                % (table.name, mongo_n, sql_n)
            )
    images = {}
    for key, d in data.items():
        if "bucket" not in d.spec:
            continue
        thumb = d.spec["model"].__table__.c.image.type.thumbnail_size
        ok = bad = 0
        for doc in d.docs:
            lid = oid(doc["_id"])
            obj = per_key[key].get(lid)
            if image_id(doc) is None or obj is None:
                continue
            what = "%s %s" % (d.name, lid)
            got = read_image(d, doc, run, what)
            if got is None:
                bad += 1
                continue
            body = got[0]
            why = (
                "has no image"
                if not obj.image
                else check_file(folder, obj.image, len(body), sha256(body))
            )
            if (
                why is None
                and thumb
                and not os.path.isfile(
                    os.path.join(folder, thumbgen_filename(obj.image))
                )
            ):
                why = "thumbnail for %s is missing" % obj.image
            if why:
                bad += 1
                run.mismatches.append("%s: image: %s" % (what, why))
            else:
                ok += 1
        images[d.name] = (ok, bad)
    return rows, assoc, images


def print_report(rows, assoc, images, tally, run, dry_run):
    out = []
    if tally:
        out.append("%s" % ("DRY RUN (nothing written)" if dry_run else "Migrated"))
        out.append(
            "  %-16s %6s %8s %7s %10s" % ("", "new", "existing", "images", "unchanged")
        )
        for key, t in tally.items():
            out.append(
                "  %-16s %6d %8d %7d %10d"
                % (
                    SPECS[key]["collections"][0],
                    t["new"],
                    t["updated"],
                    t["images"],
                    t["unchanged"],
                )
            )
    if rows:
        out.append("")
        out.append(
            "Counts (Mongo vs MariaDB rows with a legacy_id; list entries that point at nothing are\n  warned about and not counted)"
        )
        for name, m, s in rows:
            out.append(
                "  %-24s %6d %6d  %s" % (name, m, s, "ok" if m == s else "MISMATCH")
            )
        for name, m, s in assoc:
            out.append(
                "  %-24s %6d %6d  %s" % (name, m, s, "ok" if m == s else "MISMATCH")
            )
        out.append("")
        out.append("Images matching their GridFS source by length and SHA-256")
        for name, (ok, bad) in images.items():
            out.append("  %-24s %6d ok %4d bad" % (name, ok, bad))
    if run.warnings:
        out.append("")
        out.append("Warnings (fixed up; check them):")
        out += ["  " + w for w in run.warnings]
    if run.problems:
        out.append("")
        out.append("Problems:")
        out += ["  " + p for p in run.problems]
    if run.mismatches:
        out.append("")
        out.append("Mismatches:")
        out += ["  " + m for m in run.mismatches]
    print("\n".join(out))


def print_sample(data, n, seed):
    fig = data["figure"]
    sql = {
        o.legacy_id: o
        for o in db.session.query(Figure).filter(Figure.legacy_id.isnot(None))
    }
    names = {
        k: {oid(d["_id"]): d.get("name") for d in data[k].docs}
        for k in (
            "franchise",
            "faction",
            "tooling",
            "accessory",
            "category",
            "tf_wiki_link",
            "figure",
        )
    }
    docs = [d for d in fig.docs if oid(d["_id"]) in sql]
    random.Random(seed).shuffle(docs)
    print(
        "\nSpot-check these figures in the UI (Mongo values; open /figuremodelview/show/<id>):"
    )
    for doc in docs[:n]:
        lid = oid(doc["_id"])

        def names_of(field, target):
            return ", ".join(
                str(names[target].get(oid(v))) for v in doc.get(field) or []
            )

        print(
            "\n  id %d  %s (%s)  legacy %s"
            % (sql[lid].id, doc.get("name"), doc.get("release_year"), lid)
        )
        print("    faction:     %s" % names["faction"].get(oid(doc.get("faction"))))
        print(
            "    character:   %s" % names["tf_wiki_link"].get(oid(doc.get("character")))
        )
        print("    franchise:   %s" % names_of("franchise", "franchise"))
        print("    tooling:     %s" % names_of("tooling", "tooling"))
        print("    categories:  %s" % names_of("categories", "category"))
        print("    accessories: %s" % names_of("accessories", "accessory"))
        print("    history:     %s" % names_of("history", "tf_wiki_link"))
        print("    packed with: %s" % names_of("packed_with", "tf_wiki_link"))
        print("    gestalt of:  %s" % names_of("gestalt_of", "figure"))
        print(
            "    other:       exclusive_to=%s hasbro=%s takara=%s condition=%s qty=%s image=%s"
            % (
                doc.get("exclusive_to"),
                doc.get("hasbro_id"),
                doc.get("takara_id"),
                doc.get("condition"),
                doc.get("quantity", 1),
                "yes" if image_id(doc) else "no",
            )
        )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--mongo-uri", default=os.environ.get("MONGO_URI", "mongodb://mongo:27017")
    )
    ap.add_argument("--mongo-db", default=os.environ.get("MONGO_DB", "tfc"))
    ap.add_argument(
        "--dry-run", action="store_true", help="read and count; write nothing"
    )
    ap.add_argument(
        "--verify-only", action="store_true", help="only compare MariaDB with Mongo"
    )
    ap.add_argument(
        "--sample", type=int, default=10, help="figures to list for a UI spot-check"
    )
    ap.add_argument(
        "--seed", type=int, default=None, help="seed for choosing the sample"
    )
    args = ap.parse_args(argv)

    logging.getLogger().setLevel(logging.WARNING)  # FAB logs every route at INFO
    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    mdb = client[args.mongo_db]
    folder = app.config["IMG_UPLOAD_FOLDER"]
    run = Run()
    tally = None
    with app.app_context():
        data = read_mongo(mdb, run)
        check_documents(data, run)
        if not args.verify_only:
            tally = migrate(data, folder, run, args.dry_run)
        rows = assoc = images = None
        if not args.dry_run:
            rows, assoc, images = verify(data, folder, run)
        if args.dry_run:
            fig = data["figure"]
            print(
                "Mongo documents: "
                + ", ".join("%s %d" % (d.name, len(d.docs)) for d in data.values())
            )
            print(
                "Association entries: "
                + ", ".join(
                    "%s %d" % (t.name, sum(len(d.get(f) or []) for d in fig.docs))
                    for f, t, _c, _x in FIGURE_LISTS
                )
            )
            print()
        print_report(rows, assoc, images, tally, run, args.dry_run)
        if not args.dry_run and args.sample:
            print_sample(data, args.sample, args.seed)
    bad = bool(run.problems or run.mismatches)
    print("\n%s" % ("FAILED: see above." if bad else "OK: nothing wrong found."))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
