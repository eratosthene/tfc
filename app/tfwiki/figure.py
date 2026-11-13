"""From a pasted tfwiki.net link to suggestions for one figure."""

from app.tfwiki import parser
from app.tfwiki.fetcher import FetchError, PageNotFound, normalize_title


class FigureNotFound(parser.ParseError):
    """The page was read but has no figure for the link's ``#fragment``."""

    def __init__(self, message, available):
        super().__init__(message)
        self.available = available


class FigureOnSeveralPages(FigureNotFound):
    """The link's page is now a disambiguation page, and more than one of the
    pages it lists has a section called that."""


def _found(entries, fragment):
    if fragment is None:
        return [(e, None) for e in entries]
    return [(e, how) for e in entries if (how := parser.matches(e, fragment))]


def _symbol(fetcher, code, factions):
    """(CSS class, faction) from ``Template:Bp-code``; (None, None) if unknown."""
    try:
        _, text = fetcher.page("Template:Bp-" + code)
    except FetchError:
        return None, None
    css = parser.bullet_class(text)
    return css, parser.faction_from_class(css, factions)


def read_figure(
    fetcher, url, factions=parser.DEFAULT_FACTIONS, search_all=False, fields=True
):
    """Suggestions for the figure a tfwiki.net link points at.

    Reads the page, and when the figure is not on it follows the
    ``{{main|Name/toys}}`` pointers (the toys of long character pages were moved
    to their own pages). It stops at the first toys page that has the figure,
    unless ``search_all`` is set, which reads every toys page and returns a
    candidate from each page that has it. Returns the character, and for each
    matching entry the suggested fields and its canonical link. Raises
    ``parser.ParseError`` for a link that is not a tfwiki.net page,
    ``FigureNotFound`` when no page has such a figure, and the fetcher's errors
    unchanged. With ``fields=False`` only the link is worked out: no suggestions
    are made, and so no faction-symbol template pages are fetched.

    A name that used to be a character page may now be a disambiguation page
    (``Battletrap`` -> ``Battletrap (G1)``, ``(Cyberverse)``...). If the figure is not
    on it and the link has a ``#fragment``, each page it lists is read, and if
    exactly one has a section with that exact name (capitals included) the result
    is that page's, with ``disambiguated`` set to the disambiguation page's title.
    More than one raises ``FigureOnSeveralPages``; none, ``FigureNotFound``.
    """
    return _read(fetcher, url, factions, search_all, fields, None)


def _read(fetcher, url, factions, search_all, fields, via):
    asked, fragment = parser.parse_url(url)
    title, text = fetcher.page(asked)
    first_title, first_text = title, text
    moved = normalize_title(title).lower() != asked.lower()
    entries = parser.entries(text, title)
    found = [(title, e, how) for e, how in _found(entries, fragment)]
    if not found:
        for pointer in parser.toys_pointers(text, title):
            title, text = fetcher.page(pointer)
            moved = True
            entries = parser.entries(text, title)
            found += [(title, e, how) for e, how in _found(entries, fragment)]
            if found and not search_all:
                break
    if not found and fragment and via is None and parser.is_disambiguation(first_text):
        return _through_disambiguation(
            fetcher,
            first_title,
            first_text,
            asked,
            fragment,
            factions,
            search_all,
            fields,
        )
    if not found:
        available = sorted(
            {e["heading"] for e in entries if e["heading"]}
            | {a for e in entries for a in e["anchors"]}
        )
        raise FigureNotFound(
            "No figure for #%s on %s" % (fragment, title)
            if fragment
            else "No figures on %s" % title,
            available,
        )
    candidates = []
    for page, entry, how in found:
        use = fragment or (entry["anchors"] or [entry["heading"]])[0]
        link = parser.page_url(page, use or None)
        suggestions = None
        if fields:
            suggestions = parser.figure_fields(entry, page, factions, own_urls=(link,))
            if suggestions["faction"] is None and suggestions["bp_code"]:
                css, faction = _symbol(fetcher, suggestions["bp_code"], factions)
                suggestions["symbol_class"] = css
                if faction:
                    suggestions["faction"] = {
                        "value": faction,
                        "source": "symbol class " + css,
                    }
        candidates.append(
            {
                "matched_by": how,
                "heading": entry["heading"],
                "subheading": entry["subheading"],
                "heading_ids": entry["heading_ids"],
                "anchors": entry["anchors"],
                "link": link,
                "fields": suggestions,
                "block": "\n".join(entry["lines"]),
            }
        )
    return {
        "asked": asked,
        "page": found[0][0],
        "fragment": fragment,
        "moved": moved,
        "character": parser.character(found[0][0]),
        "candidates": candidates,
    }


def _through_disambiguation(
    fetcher, title, text, asked, fragment, factions, search_all, fields
):
    """Look for ``fragment`` on every page a disambiguation page lists."""
    targets = parser.disambiguation_targets(text)
    hits = []
    for target in targets:
        try:
            found = _read(
                fetcher,
                parser.page_url(target, fragment),
                factions,
                search_all,
                fields,
                title,
            )
        except (FigureNotFound, PageNotFound):
            continue  # that namesake has no such section, or its page is gone
        for candidate in found["candidates"]:
            names = (
                candidate["anchors"]
                + [candidate["heading"], candidate["subheading"]]
                + candidate["heading_ids"]
            )
            if any(n and parser.same_fragment(fragment, n) for n in names):
                hits.append((found, candidate))
    if len(hits) == 1:
        found, candidate = hits[0]
        return {
            "asked": asked,
            "page": found["page"],
            "fragment": fragment,
            "moved": True,
            "disambiguated": title,
            "character": found["character"],
            "candidates": [candidate],
        }
    if len(hits) > 1:
        pages = sorted({found["page"] for found, _candidate in hits})
        raise FigureOnSeveralPages(
            "%s is a disambiguation page and #%s is on more than one page it lists: %s"
            % (title, fragment, ", ".join(pages)),
            pages,
        )
    raise FigureNotFound(
        "No figure for #%s: %s is a disambiguation page and none of the %d pages it "
        "lists has it" % (fragment, title, len(targets)),
        [t.replace("_", " ") for t in targets],
    )
