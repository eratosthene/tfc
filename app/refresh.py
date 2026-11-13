"""Refresh a figure from its own tfwiki.net link, one change at a time.

On the Edit Figure page: "Refresh from TFWiki" looks the saved link up again
(ignoring the cached copy, which needs fetching on) or "Compare with the cached
copy". It lists what the wiki says that differs from the figure, and each change
is accepted or skipped on its own. Only accepted changes are saved.

What it will and will not propose:
- only values the wiki has; it never proposes to empty a field;
- for franchise, tooling, categories, ancestors and pack-mates it proposes
  additions, never removals (a franchise the figure already has through a tagged
  child is not proposed);
- the name, year, faction, link, accessories and IDs are replacements;
- accept is pre-selected only where the figure's own value is empty, and never for
  a picture, which is a download.
"""

import re

from flask import abort, flash, redirect, request, url_for
from flask_appbuilder import BaseView, expose, has_access

from app import appbuilder, db, pictures
from app.addfigure import CsrfOnly, Problem, find, make_fetcher
from app.addfigure import suggest
from app.franchises import effective_franchises
from app.models import Category, Faction, Figure, FigureReference, Franchise, Tooling
from app.references import format_references, parse_references
from app.tfwiki import parser
from app.tfwiki.fetcher import Disabled, FetchError, RateLimited


def same_text(a, b):
    return " ".join((a or "").split()) == " ".join((b or "").split())


# A wiki entry for a pack ("Dreadwind & Smokejumper", "Bumblebee Cassette Pack"),
# where the figure here is one of its parts.
PACK_NAME = re.compile(r"\s(?:&|/|and)\s|\b(?:\d+-pack|pack|set)\b", re.I)


def is_part_of_pack(figure_name, wiki_name):
    return bool(
        figure_name
        and PACK_NAME.search(wiki_name)
        and re.search(r"\b%s\b" % re.escape(figure_name), wiki_name, re.I)
    )


def same_link(a, b):
    """Two tfwiki.net links that name the same page and fragment."""
    try:
        return parser.parse_url(a) == parser.parse_url(b)
    except parser.ParseError:
        return a == b


def compute(figure, result, index, lead):
    """The changes the wiki suggests for ``figure``, each a dict with ``key``,
    ``label``, ``current`` and ``new`` (text to show), ``note``, ``default``
    ('accept' or 'skip') and ``value`` (what applying it needs)."""
    guess = suggest(result, index, lead)
    candidate = result["candidates"][index]
    fields = candidate["fields"]
    values, notes = guess["values"], guess["notes"]
    changes = []

    def add(key, label, current, new, value, note=""):
        changes.append(
            {
                "key": key,
                "label": label,
                "current": current,
                "new": new,
                "value": value,
                "note": note,
                "default": "skip" if current or key == "picture" else "accept",
            }
        )

    if (
        fields["name"]
        and fields["name"] != figure.name
        and not is_part_of_pack(figure.name, fields["name"])
    ):
        add("name", "Name", figure.name, fields["name"], fields["name"])
    if fields["release_year"] and fields["release_year"] != figure.release_year:
        add(
            "release_year",
            "Release year",
            str(figure.release_year or ""),
            str(fields["release_year"]),
            fields["release_year"],
        )
    faction = db.session.get(Faction, values["faction"]) if values["faction"] else None
    if faction and faction.id != figure.faction_id:
        add(
            "faction",
            "Faction",
            figure.faction.name if figure.faction else "",
            faction.name,
            faction.id,
            notes.get("faction", ""),
        )
    if candidate["link"] and not same_link(candidate["link"], figure.link or ""):
        add(
            "link",
            "Link to Figure",
            figure.link or "",
            candidate["link"],
            candidate["link"],
            "the figure is on " + result["page"] if result["moved"] else "",
        )
    have = {f.id for f in effective_franchises(figure)}
    for key, label, model, current in (
        ("franchise", "Franchise", Franchise, {f.id for f in figure.franchise} | have),
        ("tooling", "Tooling", Tooling, {t.id for t in figure.tooling}),
        ("categories", "Categories", Category, {c.id for c in figure.categories}),
    ):
        new = [
            row
            for row in (db.session.get(model, i) for i in values[key])
            if row is not None and row.id not in current
        ]
        if new:
            shown = {
                "franchise": ", ".join(f.name for f in figure.franchise),
                "tooling": ", ".join(t.name for t in figure.tooling),
                "categories": ", ".join(c.name for c in figure.categories),
            }[key]
            add(
                key,
                label,
                shown,
                "add " + ", ".join(r.name for r in new),
                [r.id for r in new],
                notes.get(key, ""),
            )
    if fields["accessories"] and not same_text(
        fields["accessories"].casefold(), (figure.accessories_text or "").casefold()
    ):
        add(
            "accessories_text",
            "Accessories",
            figure.accessories_text or "",
            fields["accessories"],
            fields["accessories"],
        )
    for key, label in (("hasbro_id", "Hasbro ID"), ("takara_id", "Takara ID")):
        wiki = fields.get(key)
        if wiki and not same_text(wiki, getattr(figure, key)):
            add(key, label, getattr(figure, key) or "", wiki, wiki)
    for kind, key, label in (
        ("ancestor", "history", "Model History"),
        ("packed_with", "packed_with", "Packed With"),
    ):
        mine = [r for r in figure.references if r.kind == kind]
        known = {r.link for r in mine}
        wanted = parse_references(values[key + "_text"])
        new = [(name, link) for name, link in wanted if link not in known]
        if new:
            add(
                key,
                label,
                format_references(mine),
                "add:\n" + "\n".join("%s | %s" % pair for pair in new),
                new,
            )
    picture = fields["picture"]
    if picture:
        add(
            "picture",
            "Picture",
            "has a picture" if figure.image else "none",
            picture["file"]
            + (" (the old file is kept on disk)" if figure.image else ""),
            picture,
            "downloads the picture from tfwiki.net",
        )
    return changes


def apply_changes(figure, chosen, saved_image):
    """Make the accepted changes on ``figure`` (not committed)."""
    for change in chosen:
        key, value = change["key"], change["value"]
        if key in (
            "name",
            "release_year",
            "link",
            "accessories_text",
            "hasbro_id",
            "takara_id",
        ):
            setattr(figure, key, value)
        elif key == "faction":
            figure.faction = db.session.get(Faction, value)
        elif key in ("franchise", "tooling", "categories"):
            model = {
                "franchise": Franchise,
                "tooling": Tooling,
                "categories": Category,
            }[key]
            current = getattr(figure, key)
            for row in (db.session.get(model, i) for i in value):
                if row is not None and row not in current:
                    current.append(row)
        elif key in ("history", "packed_with"):
            kind = "ancestor" if key == "history" else "packed_with"
            position = len([r for r in figure.references if r.kind == kind])
            for name, link in value:
                figure.references.append(
                    FigureReference(kind=kind, position=position, name=name, link=link)
                )
                position += 1
        elif key == "picture":
            figure.image = saved_image


class RefreshFigureView(BaseView):
    route_base = "/refreshfigure"

    def _page(self, step, figure, **kwargs):
        return self.render_template(
            "refreshfigure.html",
            step=step,
            figure=figure,
            csrf_form=CsrfOnly(),
            **kwargs,
        )

    def _expired(self, pk):
        """The form's token ran out (the page was open a while): nothing was
        done; send the user back to the figure to try again."""
        flash(
            "That page had expired, so nothing was done. Please try again.", "warning"
        )
        return redirect(url_for("FigureModelView.edit", pk=str(pk)))

    def _figure(self, pk):
        figure = db.session.get(Figure, pk)
        if figure is None:
            abort(404)
        return figure

    def _diff(self, figure, pick, refresh, errors=(), selected=None):
        if not figure.link:
            return self._page(
                "problem", figure, problem=Problem("This figure has no link.")
            )
        try:
            result, lead = find(figure.link, refresh)
        except Problem as problem:
            return self._page("problem", figure, problem=problem)
        found = result["candidates"]
        if pick is None:
            if len(found) > 1:
                return self._page("choose", figure, result=result)
            pick = 0
        if not 0 <= pick < len(found):
            return self._page(
                "problem", figure, problem=Problem("Pick one of the figures listed.")
            )
        changes = compute(figure, result, pick, lead)
        selected = selected or {}
        return self._page(
            "diff",
            figure,
            result=result,
            pick=pick,
            changes=changes,
            selected=selected,
            errors=list(errors),
            candidate=found[pick],
        )

    @expose("/<int:pk>/compare", methods=["POST"])
    @has_access
    def compare(self, pk):
        if not CsrfOnly().validate_on_submit():
            return self._expired(pk)
        figure = self._figure(pk)
        pick = request.form.get("pick", "")
        return self._diff(
            figure,
            int(pick) if pick.isdigit() else None,
            bool(request.form.get("refresh")),
        )

    @expose("/<int:pk>/apply", methods=["POST"])
    @has_access
    def apply(self, pk):
        if not CsrfOnly().validate_on_submit():
            return self._expired(pk)
        if not appbuilder.sm.has_access("can_edit", "FigureModelView"):
            abort(403)
        figure = self._figure(pk)
        pick = request.form.get("pick", "")
        index = int(pick) if pick.isdigit() else 0
        try:
            result, lead = find(figure.link or "", False)
            changes = compute(figure, result, index, lead)
        except (Problem, IndexError):
            return self._diff(figure, index, False)
        selected = {
            c["key"]: request.form.get("choice_" + c["key"], "skip") for c in changes
        }
        chosen = [c for c in changes if selected[c["key"]] == "accept"]
        if not chosen:
            flash("Nothing was accepted, so the figure is unchanged.", "info")
            return redirect(url_for("FigureModelView.edit", pk=str(figure.id)))
        saved = None
        if any(c["key"] == "picture" for c in chosen):
            picture = next(c["value"] for c in chosen if c["key"] == "picture")
            try:
                saved = pictures.download_picture(make_fetcher(), picture)
            except Disabled:
                error = "Downloading from tfwiki.net is off (TFWIKI_ENABLED)."
            except RateLimited as problem:
                error = "tfwiki.net asked us to slow down. %s" % problem
            except (FetchError, ValueError) as problem:
                error = "Could not use the picture: %s" % problem
            else:
                error = None
            if error:
                return self._diff(
                    figure, index, False, [error + " Nothing was saved."], selected
                )
        apply_changes(figure, chosen, saved)
        db.session.commit()
        flash(
            "Updated %s: %s."
            % (figure.name, ", ".join(c["label"].lower() for c in chosen)),
            "success",
        )
        return redirect(url_for("FigureModelView.show", pk=str(figure.id)))
