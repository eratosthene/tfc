"""Add a figure from a tfwiki.net link: paste, look up, review, save.

docs/proposals/data-model.md, section 3. The look-up writes nothing; the review
form shows every suggestion with where it came from; saving creates the figure,
and a character, continuity and references only when they are new, in one
transaction. Nothing existing is ever edited.
"""

from flask import flash, redirect, request, url_for
from flask_appbuilder import BaseView, expose, has_access
from flask_wtf import FlaskForm
from sqlalchemy import select

from app import app, db
from app.models import (
    Category,
    Character,
    Continuity,
    Faction,
    Figure,
    FigureReference,
    Franchise,
    FranchiseAlias,
    Tooling,
)
from app.references import format_references, parse_references
from app.tfwiki import parser
from app.tfwiki.fetcher import (
    Disabled,
    FetchError,
    PageNotFound,
    RateLimited,
    fetcher_from_config,
)
from app.tfwiki.figure import FigureNotFound, read_figure

YEAR_RANGE = (1900, 2100)


class CsrfOnly(FlaskForm):
    """No fields: it exists to write and check the form's CSRF token, which is how
    Flask-AppBuilder protects its own forms."""


class Problem(Exception):
    """Something to tell the user on the paste page; ``hints`` are fragments the
    page does have."""

    def __init__(self, message, hints=()):
        super().__init__(message)
        self.hints = list(hints)


class Refreshing:
    """A fetcher whose first request for each page ignores the cache."""

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.done = set()

    def page(self, title, refresh=False):
        if title not in self.done:
            self.done.add(title)
            refresh = True
        return self.fetcher.page(title, refresh)


def make_fetcher(refresh=False):
    fetcher = fetcher_from_config(app.config)
    return Refreshing(fetcher) if refresh else fetcher


def faction_names():
    names = tuple(db.session.scalars(select(Faction.name).order_by(Faction.name)))
    return names or parser.DEFAULT_FACTIONS


def find(url, refresh=False):
    """(read_figure result, lead sentence or None) for a pasted link."""
    fetcher = make_fetcher(refresh)
    factions = faction_names()
    try:
        result = read_figure(fetcher, url, factions=factions)
    except FigureNotFound as error:
        raise Problem(str(error), error.available)
    except parser.ParseError as error:
        raise Problem(str(error))
    except Disabled:
        raise Problem(
            "That page is not in the cache and fetching from tfwiki.net is off. "
            "Set TFWIKI_ENABLED = True in config.py to look it up."
        )
    except RateLimited as error:
        raise Problem(
            "tfwiki.net asked us to slow down, so fetching is paused. %s" % error
        )
    except PageNotFound:
        raise Problem("tfwiki.net has no such page.")
    except FetchError as error:
        raise Problem(str(error))
    lead = None
    try:
        lead = parser.lead(fetcher.page(result["character"]["page"])[1], factions)
    except FetchError:
        pass  # the lead sentence is only a hint
    return result, lead


# --- suggestions -----------------------------------------------------------


def by_name(model):
    return {row.name.lower(): row for row in db.session.scalars(select(model))}


def suggest(result, index, lead):
    """The review form's starting values, with the source of each guess."""
    candidate = result["candidates"][index]
    fields = candidate["fields"]
    factions = by_name(Faction)
    notes = {}
    faction = None
    if fields["faction"]:
        faction = factions.get(fields["faction"]["value"].lower())
        notes["faction"] = "from " + fields["faction"]["source"]
    elif lead and lead.get("faction"):
        faction = factions.get(lead["faction"].lower())
        notes["faction"] = "from the character page: " + lead["sentence"]
    franchise, found = None, None
    aliases = {
        a.alias.lower(): a.franchise for a in db.session.scalars(select(FranchiseAlias))
    }
    names = by_name(Franchise)
    for term in [fields["toyline"]] + list(fields["anchors"]):
        if term and term.lower() in aliases:
            franchise, found = aliases[term.lower()], "remembered mapping of " + term
        elif term and term.lower() in names:
            franchise, found = names[term.lower()], "named like " + term
        if franchise:
            break
    notes["franchise"] = found or (
        "no franchise matches the toyline %r" % fields["toyline"]
        if fields["toyline"]
        else ""
    )
    tooling_names = by_name(Tooling)
    tooling = []
    if fields["tooling"]:
        tooling = [
            tooling_names[v.lower()]
            for v in fields["tooling"]["values"]
            if v.lower() in tooling_names
        ]
        notes["tooling"] = "guessed from: " + fields["tooling"]["evidence"]
    category_names = by_name(Category)
    categories = []
    for kind in fields["classes"]:
        for key in (kind.lower(), kind.lower().replace(" class", "")):
            if key in category_names and category_names[key] not in categories:
                categories.append(category_names[key])
    notes["categories"] = (
        "the wiki says: " + ", ".join(fields["classes"]) if fields["classes"] else ""
    )
    char = result["character"]
    # The character at this page's link; failing that, at the link that was pasted
    # (the wiki may have renamed the page since the character was saved).
    existing, matched = None, ""
    pasted = parser.page_url(parser.character_page(result["asked"]))
    for wanted, how in ((char["link"], ""), (pasted, "the link you pasted")):
        existing = db.session.scalar(select(Character).where(Character.link == wanted))
        if existing:
            matched = how
            break
    if matched:
        notes["character"] = "matched by " + matched
    continuity = None
    if char["qualifier"]:
        continuity = by_name(Continuity).get(char["qualifier"].lower())
    duplicates = list(
        db.session.scalars(select(Figure).where(Figure.link == candidate["link"]))
    )
    return {
        "values": {
            # A section described in prose has no figure line, so no name: use the
            # character's.
            "name": fields["name"] or char["name"],
            "release_year": fields["release_year"] or "",
            "faction": faction.id if faction else "",
            "franchise": [franchise.id] if franchise else [],
            "tooling": [t.id for t in tooling],
            "categories": [c.id for c in categories],
            "accessories_text": fields["accessories"],
            "hasbro_id": fields.get("hasbro_id", ""),
            "takara_id": fields.get("takara_id", ""),
            "exclusive_to": "",
            "link": candidate["link"],
            "history_text": format_references([_ref(a) for a in fields["ancestors"]]),
            "packed_with_text": format_references(
                [_ref(p) for p in fields["packed_with"]]
            ),
            "quantity": 1,
            "condition": "",
            "character_id": existing.id if existing else "",
            "character_name": char["name"],
            "character_link": char["link"],
            "continuity_id": continuity.id if continuity else "",
            "continuity_name": char["qualifier"] or "",
            "alias": fields["toyline"] or "",
        },
        "notes": notes,
        "existing_character": existing,
        "qualifier": char["qualifier"],
        "duplicates": duplicates,
        "candidate": candidate,
        "ancestors": fields["ancestors"],
        "packed_with": fields["packed_with"],
        "picture": fields["picture"],
        "lead": lead,
    }


class _ref:
    def __init__(self, found):
        self.name, self.link = found["name"], found["link"]


def options():
    """What the review form's drop-downs offer."""
    pick = lambda model: list(  # noqa: E731
        db.session.scalars(select(model).order_by(model.name))
    )
    return {
        "factions": pick(Faction),
        "franchises": pick(Franchise),
        "toolings": pick(Tooling),
        "categories": pick(Category),
        "continuities": pick(Continuity),
        "characters": pick(Character),
    }


# --- saving ----------------------------------------------------------------


def clean_form(form):
    """The form as the values dict ``suggest`` makes (strings stripped)."""
    one = lambda key: (form.get(key) or "").strip()  # noqa: E731
    many = lambda key: [int(x) for x in form.getlist(key) if x.isdigit()]  # noqa: E731
    return {
        "name": one("name"),
        "release_year": one("release_year"),
        "faction": one("faction"),
        "franchise": many("franchise"),
        "tooling": many("tooling"),
        "categories": many("categories"),
        "accessories_text": one("accessories_text"),
        "hasbro_id": one("hasbro_id"),
        "takara_id": one("takara_id"),
        "exclusive_to": one("exclusive_to"),
        "link": one("link"),
        "history_text": form.get("history_text") or "",
        "packed_with_text": form.get("packed_with_text") or "",
        "quantity": one("quantity") or "1",
        "condition": one("condition"),
        "character_id": one("character_id"),
        "character_name": one("character_name"),
        "character_link": one("character_link"),
        "continuity_id": one("continuity_id"),
        "continuity_name": one("continuity_name"),
        "alias": one("alias"),
    }


def build(values, add_copy, remember):
    """Check the values and make the new rows. Returns (figure, errors); nothing
    is added to the session unless there are no errors."""
    errors = []

    def get(model, key, label):
        found = (
            db.session.get(model, int(values[key]))
            if str(values[key]).isdigit()
            else None
        )
        if found is None:
            errors.append("Choose a %s." % label)
        return found

    if not values["name"] or len(values["name"]) > 255:
        errors.append("Give the figure a name (up to 255 characters).")
    year = None
    if str(values["release_year"]).isdigit():
        year = int(values["release_year"])
    if year is None or not YEAR_RANGE[0] <= year <= YEAR_RANGE[1]:
        errors.append("The release year must be a year between %d and %d." % YEAR_RANGE)
    faction = get(Faction, "faction", "faction")
    quantity = int(values["quantity"]) if str(values["quantity"]).isdigit() else None
    if quantity is None:
        errors.append("The quantity must be a whole number.")
    link = values["link"] or None
    if link:
        try:
            parser.parse_url(link)
        except parser.ParseError as error:
            errors.append("Link to Figure: %s." % error)
        if len(link) > 500:
            errors.append("Link to Figure is too long.")
    duplicates = (
        list(db.session.scalars(select(Figure).where(Figure.link == link)))
        if link
        else []
    )
    if duplicates and not add_copy:
        errors.append(
            "A figure with this link is already in the collection (%s). Tick "
            "'add another copy' to add this one too."
            % ", ".join("%s #%s" % (d.name, d.id) for d in duplicates)
        )
    references = []
    for kind, key in (
        ("ancestor", "history_text"),
        ("packed_with", "packed_with_text"),
    ):
        try:
            for position, (name, ref_link) in enumerate(parse_references(values[key])):
                references.append(
                    FigureReference(
                        kind=kind, position=position, name=name, link=ref_link
                    )
                )
        except ValueError as error:
            errors.append(
                "%s: %s"
                % ("Model History" if kind == "ancestor" else "Packed With", error)
            )
    character, continuity = None, None
    if str(values["character_id"]).isdigit():
        character = get(Character, "character_id", "character")
    else:
        name, char_link = values["character_name"], values["character_link"]
        try:
            parser.parse_url(char_link)
            valid = bool(name) and len(name) <= 255 and len(char_link) <= 500
        except parser.ParseError:
            valid = False
        if not valid:
            errors.append("A new character needs a name and its tfwiki.net page link.")
        else:
            character = db.session.scalar(
                select(Character).where(Character.link == char_link)
            ) or Character(name=name, link=char_link)
            if character.id is None:
                if str(values["continuity_id"]).isdigit():
                    continuity = get(Continuity, "continuity_id", "continuity")
                elif values["continuity_id"] == "new" and values["continuity_name"]:
                    continuity = db.session.scalar(
                        select(Continuity).where(
                            Continuity.name == values["continuity_name"]
                        )
                    ) or Continuity(name=values["continuity_name"])
                character.continuity = continuity
    if errors:
        db.session.rollback()
        return None, errors
    figure = Figure(
        name=values["name"],
        release_year=year,
        faction=faction,
        quantity=quantity,
        link=link,
        accessories_text=values["accessories_text"] or None,
        hasbro_id=values["hasbro_id"] or None,
        takara_id=values["takara_id"] or None,
        exclusive_to=values["exclusive_to"] or None,
        condition=values["condition"] or None,
        character_new=character,
        references=references,
    )
    for key, model, attr in (
        ("franchise", Franchise, "franchise"),
        ("tooling", Tooling, "tooling"),
        ("categories", Category, "categories"),
    ):
        setattr(
            figure,
            attr,
            [r for r in (db.session.get(model, i) for i in values[key]) if r],
        )
    db.session.add(figure)
    if (
        remember
        and values["alias"]
        and len(figure.franchise) == 1
        and not db.session.scalar(
            select(FranchiseAlias.id).where(FranchiseAlias.alias == values["alias"])
        )
    ):
        db.session.add(
            FranchiseAlias(alias=values["alias"], franchise=figure.franchise[0])
        )
    return figure, []


class AddFromTFWikiView(BaseView):
    route_base = "/addfromtfwiki"
    default_view = "start"

    def _show(self, step, **kwargs):
        return self.render_template(
            "addfigure.html", step=step, csrf_form=CsrfOnly(), **kwargs
        )

    def _paste(self, **kwargs):
        return self._show("paste", **kwargs)

    def _expired(self):
        problem = Problem("This page has expired. Please start again.")
        return self._paste(url="", problem=problem), 400

    def _review(self, url, pick, refresh, values=None, errors=()):
        try:
            result, lead = find(url, refresh)
        except Problem as problem:
            return self._paste(url=url, problem=problem)
        if not 0 <= pick < len(result["candidates"]):
            return self._paste(
                url=url, problem=Problem("Pick one of the figures listed.")
            )
        guess = suggest(result, pick, lead)
        if values is not None:
            guess["values"] = values
        return self._show(
            "review",
            url=url,
            pick=pick,
            result=result,
            errors=list(errors),
            add_copy=bool(values and values.get("_add_copy")),
            **guess,
            **options(),
        )

    @expose("/")
    @has_access
    def start(self):
        return self._paste(url="")

    @expose("/lookup", methods=["POST"])
    @has_access
    def lookup(self):
        if not CsrfOnly().validate_on_submit():
            return self._expired()
        url = (request.form.get("url") or "").strip()
        refresh = bool(request.form.get("refresh"))
        pick = request.form.get("pick", "")
        if not url:
            return self._paste(url="", problem=Problem("Paste a tfwiki.net link."))
        if pick.isdigit():
            return self._review(url, int(pick), refresh)
        try:
            result, _lead = find(url, refresh)
        except Problem as problem:
            return self._paste(url=url, problem=problem)
        if len(result["candidates"]) == 1:
            return self._review(url, 0, False)
        return self._show("choose", url=url, result=result)

    @expose("/save", methods=["POST"])
    @has_access
    def save(self):
        if not CsrfOnly().validate_on_submit():
            return self._expired()
        url = (request.form.get("url") or "").strip()
        pick = request.form.get("pick", "0")
        values = clean_form(request.form)
        add_copy = bool(request.form.get("add_copy"))
        figure, errors = build(values, add_copy, bool(request.form.get("remember")))
        if errors:
            values["_add_copy"] = add_copy
            return self._review(
                url, int(pick) if pick.isdigit() else 0, False, values, errors
            )
        db.session.commit()
        flash("Added %s." % figure.name, "success")
        return redirect(url_for("FigureModelView.show", pk=str(figure.id)))
