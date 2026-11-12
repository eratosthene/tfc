#!/usr/bin/env python
"""Copy TFC's data into the new data model (docs/proposals/data-model.md, section 4).

The expand revision (b2d4f6a8c013) added the new tables and columns next to the
old ones. This script fills them from the old structures and can undo it. It
never deletes the old structures; only the contract revision (a later PR) does.

    migrate_data_model.py dry-run   do the whole transform, print the plan and the
                                    "needs review" lists, then ROLL BACK
    migrate_data_model.py apply     the same, check it, then COMMIT
    migrate_data_model.py verify    compare the old and new structures; exit 1 on any
                                    mismatch; on success record that in
                                    data_model_migration (the contract revision needs it)
    migrate_data_model.py reverse   rebuild the old structures from the new ones,
                                    check them, and clear the markers

Take a backup first (scripts/backup.sh). Run the commands where the app's
config.py is, normally inside the app container:

    docker compose -f docker/compose.yml exec tfc python scripts/migrate_data_model.py dry-run

Options: ``--no-continuity NAME`` (repeatable) leaves characters whose page suffix
is NAME without a continuity (for suffixes that are not continuities, like
``facility``); ``--family "NAME=SUFFIX,SUFFIX"`` (repeatable) puts the continuities
for those suffixes in a continuity family, creating it (``--family "Generation
1=G1,G2"``). A suffix no character has, or one left out, is reported as a
problem; ``--again`` lets ``apply`` run a second time, which overwrites
anything edited in the new structures since; ``--json PATH`` also writes the report
as JSON. The exit status is 0 only if nothing was wrong.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import warnings
from collections import OrderedDict, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Flask-AppBuilder's ImageColumn does not say it is cacheable; every query that
# selects an image column would warn about it.
warnings.filterwarnings("ignore", message=".*ImageColumn.*cache_ok")

from sqlalchemy import delete, insert, select, update  # noqa: E402

from app import app, db  # noqa: E402
from app.models import (  # noqa: E402
    Accessory,
    Category,
    Character,
    Continuity,
    ContinuityFamily,
    DataModelMigration,
    Faction,
    Figure,
    FigureReference,
    Franchise,
    TFWikiLink,
    Tooling,
    figure_accessory,
    figure_category,
    figure_franchise,
    figure_gestalt,
    figure_history,
    figure_packed_with,
    figure_tooling,
)

SEPARATOR = ", "
WIKI = "https://tfwiki.net/wiki/"
TOYS_SUFFIXES = ("/toys", "/Generations_toys")
ACCESSORY_NAME_LENGTH = 60
REFERENCES = (("ancestor", figure_history), ("packed_with", figure_packed_with))

# The columns the new structures add; the checksum of the old data ignores them.
NEW_COLUMNS = {"figure": {"link", "character_id_new", "accessories_text"}}
NEW_COLUMNS["franchise"] = {"parent_id"}
OLD_TABLES = [
    Faction.__table__,
    Category.__table__,
    Tooling.__table__,
    Franchise.__table__,
    Figure.__table__,
    TFWikiLink.__table__,
    Accessory.__table__,
    figure_franchise,
    figure_tooling,
    figure_category,
    figure_gestalt,
    figure_history,
    figure_packed_with,
    figure_accessory,
]


# --- the rules (pure functions) --------------------------------------------


def character_link(link):
    """The page a character link stands for: no #fragment, no /toys suffix."""
    page = link.split("#", 1)[0]
    for suffix in TOYS_SUFFIXES:
        if page.endswith(suffix):
            return page[: -len(suffix)]
    return page


def continuity_name(link):
    """The ``(X)`` at the end of a character page, as ``X``, else None.

    The closing bracket is optional: one production link (``Fireflight_(G1``)
    has lost it.
    """
    match = re.search(r"_\(([^()]+)\)?$", character_link(link).rsplit("/", 1)[-1])
    return match.group(1).replace("_", " ") if match else None


def join_accessories(names):
    return SEPARATOR.join(names) if names else None


def split_accessories(text, known=()):
    """The inverse of join_accessories.

    ``known`` holds the names that contain the separator themselves (one in the
    production data); they are matched first, so they come back whole.
    """
    names = []
    rest = text or ""
    ordered = sorted(known, key=len, reverse=True)
    while rest:
        for name in ordered:
            if rest == name or rest.startswith(name + SEPARATOR):
                names.append(name)
                rest = rest[len(name) + len(SEPARATOR) :]
                break
        else:
            head, _, rest = rest.partition(SEPARATOR)
            names.append(head)
    return names


# --- reading the old structures ---------------------------------------------


def read_old(session):
    """Everything the transform needs from the old tables, as plain data."""
    old = {
        "links": OrderedDict(
            (r.id, (r.name, r.link))
            for r in session.execute(
                select(TFWikiLink.id, TFWikiLink.name, TFWikiLink.link).order_by(
                    TFWikiLink.id
                )
            )
        ),
        "figures": session.execute(
            select(
                Figure.id,
                Figure.name,
                Figure.image,
                Figure.character_id,
                Figure.figure_link_id,
            ).order_by(Figure.id)
        ).all(),
        "refs": {},
        "accessories": defaultdict(list),
    }
    for kind, table in REFERENCES:
        rows = defaultdict(list)
        for r in session.execute(
            select(table).order_by(
                table.c.figure_id, table.c.position, table.c.tf_wiki_link_id
            )
        ):
            rows[r.figure_id].append((r.position, r.tf_wiki_link_id))
        old["refs"][kind] = rows
    for r in session.execute(
        select(figure_accessory.c.figure_id, Accessory.name)
        .join(Accessory, Accessory.id == figure_accessory.c.accessory_id)
        .order_by(
            figure_accessory.c.figure_id,
            figure_accessory.c.position,
            figure_accessory.c.accessory_id,
        )
    ):
        old["accessories"][r.figure_id].append(r.name)
    return old


def make_plan(old, skip_continuities=(), families=None):
    """What the new structures should hold, and what needs a human look.

    Pure: it reads ``old`` and decides; nothing is written.
    """
    links = old["links"]
    characters = OrderedDict()
    figures = OrderedDict()
    roles = defaultdict(set)
    for fid, fname, _image, char_id, link_id in old["figures"]:
        name, link = links[char_id]
        roles[char_id].add("character")
        page = character_link(link)
        char = characters.setdefault(
            page, {"name": name, "originals": [], "figures": 0}
        )
        char["figures"] += 1
        if link != page and link not in char["originals"]:
            char["originals"].append(link)
        if link_id is not None:
            roles[link_id].add("figure link")
        refs = []
        for kind, _table in REFERENCES:
            for position, lid in old["refs"][kind].get(fid, ()):
                roles[lid].add("ancestor" if kind == "ancestor" else "packed with")
                refs.append((kind, position, links[lid][0], links[lid][1]))
        figures[fid] = {
            "name": fname,
            "link": links[link_id][1] if link_id is not None else None,
            "character": page,
            "accessories": join_accessories(old["accessories"].get(fid)),
            "refs": refs,
        }
    continuities = OrderedDict()
    for page, char in characters.items():
        suffix = continuity_name(page)
        char["suffix"] = suffix
        char["continuity"] = None if suffix in skip_continuities else suffix
        if char["continuity"]:
            continuities.setdefault(suffix, []).append(char["name"])
    placed = {}
    problems = []
    for family, suffixes in (families or {}).items():
        for suffix in suffixes:
            if suffix in skip_continuities:
                problems.append(
                    "family %r lists %r, which --no-continuity leaves out"
                    % (family, suffix)
                )
            elif suffix not in continuities:
                problems.append(
                    "family %r lists %r, which no character's page has"
                    % (family, suffix)
                )
            elif suffix in placed:
                problems.append(
                    "%r is in both %r and %r" % (suffix, placed[suffix], family)
                )
            else:
                placed[suffix] = family
    used = set(roles)
    return {
        "problems": problems,
        "families": placed,
        "continuities": continuities,
        "characters": characters,
        "figures": figures,
        "report": {
            "figures": len(figures),
            "links": len(links),
            "characters": len(characters),
            "continuities": {k: len(v) for k, v in continuities.items()},
            "families": {
                f: [s for s in continuities if placed.get(s) == f]
                for f in OrderedDict.fromkeys(placed.values())
            },
            "continuities_without_family": [s for s in continuities if s not in placed],
            "references": sum(len(f["refs"]) for f in figures.values()),
            "with_accessories": sum(1 for f in figures.values() if f["accessories"]),
            "no_suffix": sorted(
                c["name"] + " <" + p + ">"
                for p, c in characters.items()
                if c["suffix"] is None
            ),
            "skipped_suffixes": sorted(
                {
                    c["suffix"]
                    for c in characters.values()
                    if c["suffix"] in skip_continuities
                }
            ),
            "rewritten_character_links": [
                {"to": p, "from": c["originals"]}
                for p, c in characters.items()
                if c["originals"]
            ],
            "several_roles": [
                {"id": i, "link": links[i][1], "roles": sorted(r)}
                for i, r in sorted(roles.items())
                if len(r) > 1
            ],
            "not_tfwiki": [
                {"id": i, "link": ln}
                for i, (_n, ln) in links.items()
                if not ln.startswith(WIKI)
            ],
            "unreferenced": [
                {"id": i, "name": n, "link": ln}
                for i, (n, ln) in links.items()
                if i not in used
            ],
            "accessory_names_with_separator": sorted(
                {
                    n
                    for names in old["accessories"].values()
                    for n in names
                    if SEPARATOR in n
                }
            ),
        },
    }


# --- writing the new structures ---------------------------------------------


def write_plan(session, plan):
    """Create what is missing and set the new columns. Never touches the old data."""
    families = {f.name: f for f in session.scalars(select(ContinuityFamily))}
    for name in OrderedDict.fromkeys(plan["families"].values()):
        if name not in families:
            families[name] = ContinuityFamily(name=name)
            session.add(families[name])
    session.flush()
    continuities = {c.name: c for c in session.scalars(select(Continuity))}
    for name in plan["continuities"]:
        if name not in continuities:
            continuities[name] = Continuity(name=name)
            session.add(continuities[name])
        family = families.get(plan["families"].get(name))
        if family and continuities[name].family_id is None:
            continuities[name].family_id = family.id
    session.flush()
    characters = {c.link: c for c in session.scalars(select(Character))}
    for page, spec in plan["characters"].items():
        if page not in characters:
            cont = continuities.get(spec["continuity"])
            characters[page] = Character(
                name=spec["name"], link=page, continuity_id=cont.id if cont else None
            )
            session.add(characters[page])
    session.flush()
    session.execute(
        delete(FigureReference).where(FigureReference.figure_id.in_(plan["figures"]))
    )
    for fid, spec in plan["figures"].items():
        session.execute(
            update(Figure.__table__)
            .where(Figure.__table__.c.id == fid)
            .values(
                link=spec["link"],
                character_id_new=characters[spec["character"]].id,
                accessories_text=spec["accessories"],
            )
        )
        for kind, position, name, link in spec["refs"]:
            session.execute(
                insert(FigureReference.__table__).values(
                    figure_id=fid, kind=kind, position=position, name=name, link=link
                )
            )
    session.flush()


def checksum(session):
    """A digest of every old table (without the columns the new model added)."""
    result = {}
    for table in OLD_TABLES:
        skip = NEW_COLUMNS.get(table.name, ())
        columns = [c for c in table.c if c.name not in skip]
        digest = hashlib.sha256()
        count = 0
        for row in session.execute(select(*columns).order_by(*columns)):
            digest.update(repr(tuple(row)).encode())
            count += 1
        result[table.name] = [count, digest.hexdigest()]
    return result


# --- checking ---------------------------------------------------------------


def check(session):
    """Compare the old and new structures. Returns (problems, info)."""
    old = read_old(session)
    links = old["links"]
    problems = []
    new_chars = {c.id: c for c in session.scalars(select(Character))}
    new_figs = {
        r.id: r
        for r in session.execute(
            select(
                Figure.id,
                Figure.link,
                Figure.character_id_new,
                Figure.accessories_text,
            )
        )
    }
    refs = {kind: defaultdict(list) for kind, _t in REFERENCES}
    for r in session.scalars(
        select(FigureReference).order_by(
            FigureReference.figure_id, FigureReference.position, FigureReference.id
        )
    ):
        refs[r.kind][r.figure_id].append((r.name, r.link))

    def bad(fid, name, what, old_value, new_value):
        problems.append(
            "figure %s (%s): %s: old %r, new %r"
            % (fid, name, what, old_value, new_value)
        )

    for fid, fname, _image, char_id, link_id in old["figures"]:
        new = new_figs[fid]
        want = links[link_id][1] if link_id is not None else None
        if new.link != want:
            bad(fid, fname, "figure link", want, new.link)
        char = new_chars.get(new.character_id_new)
        want = character_link(links[char_id][1])
        if char is None or char.link != want:
            bad(fid, fname, "character link", want, char.link if char else None)
        text = join_accessories(old["accessories"].get(fid))
        if new.accessories_text != text:
            bad(fid, fname, "accessories", text, new.accessories_text)
        for kind, _t in REFERENCES:
            want = [tuple(links[lid]) for _p, lid in old["refs"][kind].get(fid, ())]
            have = refs[kind].get(fid, [])
            if have != want:
                bad(fid, fname, kind + "s", want, have)
    for kind, _t in REFERENCES:
        want = sum(len(v) for v in old["refs"][kind].values())
        have = sum(len(v) for v in refs[kind].values())
        if want != have:
            problems.append("%s rows: old %d, new %d" % (kind, want, have))
    used = {character_link(links[f[3]][1]) for f in old["figures"]}
    if used != {c.link for c in new_chars.values()}:
        problems.append(
            "characters: %d distinct links used by figures, %d in the character table"
            % (len(used), len(new_chars))
        )
    folder = app.config.get("IMG_UPLOAD_FOLDER")
    missing = []
    if folder:
        for model in (Figure, Faction, Franchise):
            for pk, image in session.execute(select(model.id, model.image)):
                if image and not os.path.exists(os.path.join(folder, image)):
                    missing.append("%s %s: %s" % (model.__tablename__, pk, image))
    info = {
        "figures": len(old["figures"]),
        "characters": len(new_chars),
        "missing_images": missing,
    }
    return problems, info


# --- markers ----------------------------------------------------------------


def record(session, step, detail):
    row = session.scalar(
        select(DataModelMigration).where(DataModelMigration.step == step)
    )
    if row is None:
        row = DataModelMigration(step=step)
        session.add(row)
    row.recorded_at = datetime.now()
    row.detail = json.dumps(detail, sort_keys=True)
    session.flush()


def marker(session, step):
    return session.scalar(
        select(DataModelMigration).where(DataModelMigration.step == step)
    )


# --- the commands -----------------------------------------------------------


def do_transform(session, skip, commit, again=False, families=None):
    """dry-run (commit=False) and apply (commit=True). Returns (report, problems)."""
    if commit and not again and marker(session, "apply") is not None:
        return {}, [
            "apply already ran (%s). A second run would overwrite anything edited in "
            "the new structures since; pass --again if that is what you want."
            % marker(session, "apply").recorded_at
        ]
    before = checksum(session)
    plan = make_plan(read_old(session), skip, families)
    write_plan(session, plan)
    problems = list(plan["problems"])
    after = checksum(session)
    for name in before:
        if before[name] != after[name]:
            problems.append("the old table %s changed during the transform" % name)
    found, info = check(session)
    problems += found
    report = dict(plan["report"], **info)
    if problems or not commit:
        session.rollback()
    else:
        record(
            session,
            "apply",
            {
                "skipped": sorted(skip),
                "families": families or {},
                "figures": info["figures"],
            },
        )
        session.commit()
    return report, problems


def do_verify(session):
    problems, info = check(session)
    if marker(session, "apply") is None:
        problems.append("apply has not been run")
    if not problems:
        record(session, "verify", info)
        session.commit()
    return info, problems


def do_reverse(session):
    """Rebuild the old structures from the new ones."""
    old = read_old(session)
    links = old["links"]
    by_pair = {}
    by_link = {}
    for lid, (name, link) in links.items():
        by_pair.setdefault((name, link), lid)
        by_link.setdefault(link, lid)
    problems = []

    def link_id(name, link):
        if (name, link) not in by_pair:
            row = TFWikiLink(name=name, link=link)
            session.add(row)
            session.flush()
            by_pair[(name, link)] = row.id
            by_link.setdefault(link, row.id)
        return by_pair[(name, link)]

    chars = {c.id: c for c in session.scalars(select(Character))}
    known = {
        n for names in old["accessories"].values() for n in names if SEPARATOR in n
    }
    known |= {n for n in session.scalars(select(Accessory.name)) if SEPARATOR in n}
    accessory_ids = {a.name: a.id for a in session.scalars(select(Accessory))}
    new_refs = {kind: defaultdict(list) for kind, _t in REFERENCES}
    for r in session.scalars(
        select(FigureReference).order_by(
            FigureReference.figure_id, FigureReference.position, FigureReference.id
        )
    ):
        new_refs[r.kind][r.figure_id].append(r)
    for _kind, table in REFERENCES:
        session.execute(delete(table))
    session.execute(delete(figure_accessory))
    for r in session.execute(
        select(
            Figure.id,
            Figure.name,
            Figure.link,
            Figure.character_id,
            Figure.figure_link_id,
            Figure.character_id_new,
            Figure.accessories_text,
        ).order_by(Figure.id)
    ):
        label = "figure %s (%s)" % (r.id, r.name)
        values = {}
        char = chars.get(r.character_id_new)
        if char is None:
            problems.append(label + ": has no character")
            continue
        current = links.get(r.character_id)
        if current is not None and character_link(current[1]) == char.link:
            values["character_id"] = r.character_id
        else:
            values["character_id"] = by_link.get(char.link) or link_id(
                char.name, char.link
            )
        current = links.get(r.figure_link_id)
        if r.link is None:
            values["figure_link_id"] = None
        elif current is not None and current[1] == r.link:
            values["figure_link_id"] = r.figure_link_id
        else:
            values["figure_link_id"] = by_link.get(r.link) or link_id(r.name, r.link)
        session.execute(
            update(Figure.__table__)
            .where(Figure.__table__.c.id == r.id)
            .values(**values)
        )
        for kind, table in REFERENCES:
            seen = set()
            for ref in new_refs[kind].get(r.id, ()):
                lid = link_id(ref.name, ref.link)
                if lid in seen:
                    problems.append("%s: %s %r listed twice" % (label, kind, ref.name))
                    continue
                seen.add(lid)
                session.execute(
                    insert(table).values(
                        figure_id=r.id,
                        tf_wiki_link_id=lid,
                        position=ref.position,
                    )
                )
        seen = set()
        for pos, name in enumerate(split_accessories(r.accessories_text, known)):
            if name in seen:
                problems.append("%s: accessory %r listed twice" % (label, name))
                continue
            seen.add(name)
            if len(name) > ACCESSORY_NAME_LENGTH:
                problems.append(
                    "%s: accessory %r is too long for the old table" % (label, name)
                )
                continue
            if name not in accessory_ids:
                row = Accessory(name=name)
                session.add(row)
                session.flush()
                accessory_ids[name] = row.id
            session.execute(
                insert(figure_accessory).values(
                    figure_id=r.id, accessory_id=accessory_ids[name], position=pos
                )
            )
    session.flush()
    found, info = check(session)
    problems += found
    if problems:
        session.rollback()
    else:
        session.execute(
            delete(DataModelMigration).where(
                DataModelMigration.step.in_(["apply", "verify"])
            )
        )
        session.commit()
    return info, problems


# --- output -----------------------------------------------------------------


def render(command, report, problems):
    lines = ["== migrate_data_model.py %s ==" % command]
    for key, value in report.items():
        if isinstance(value, (list, dict)) and value:
            lines.append("%s (%d):" % (key, len(value)))
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for k, v in list(items)[:200]:
                lines.append(
                    "  %s" % (v if isinstance(value, list) else "%s: %s" % (k, v))
                )
        elif not isinstance(value, (list, dict)):
            lines.append("%s: %s" % (key, value))
    if problems:
        lines.append("PROBLEMS (%d):" % len(problems))
        lines += ["  " + p for p in problems]
    lines.append("RESULT: " + ("FAILED" if problems else "ok"))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["dry-run", "apply", "verify", "reverse"])
    parser.add_argument("--no-continuity", action="append", default=[], metavar="NAME")
    parser.add_argument(
        "--family", action="append", default=[], metavar="NAME=SUFFIX,..."
    )
    parser.add_argument("--again", action="store_true")
    parser.add_argument("--json", metavar="PATH")
    args = parser.parse_args(argv)
    with app.app_context():
        session = db.session
        skip = set(args.no_continuity)
        families = {}
        for spec in args.family:
            name, _sep, rest = spec.partition("=")
            suffixes = [x.strip() for x in rest.split(",") if x.strip()]
            if not name.strip() or not suffixes:
                parser.error("--family wants NAME=SUFFIX,SUFFIX (got %r)" % spec)
            families.setdefault(name.strip(), []).extend(suffixes)
        if args.command == "dry-run":
            report, problems = do_transform(
                session, skip, commit=False, families=families
            )
        elif args.command == "apply":
            report, problems = do_transform(
                session, skip, commit=True, again=args.again, families=families
            )
        elif args.command == "verify":
            report, problems = do_verify(session)
        else:
            report, problems = do_reverse(session)
        print(render(args.command, report, problems))
        if args.json:
            with open(args.json, "w") as f:
                json.dump({"report": report, "problems": problems}, f, indent=2)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
