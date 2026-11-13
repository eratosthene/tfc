"""From a pasted tfwiki.net link to suggestions for one figure."""

from app.tfwiki import parser
from app.tfwiki.fetcher import FetchError, normalize_title


class FigureNotFound(parser.ParseError):
    """The page was read but has no figure for the link's ``#fragment``."""

    def __init__(self, message, available):
        super().__init__(message)
        self.available = available


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


def read_figure(fetcher, url, factions=parser.DEFAULT_FACTIONS, search_all=False):
    """Suggestions for the figure a tfwiki.net link points at.

    Reads the page, and when the figure is not on it follows the
    ``{{main|Name/toys}}`` pointers (the toys of long character pages were moved
    to their own pages). It stops at the first toys page that has the figure,
    unless ``search_all`` is set, which reads every toys page and returns a
    candidate from each page that has it. Returns the character, and for each
    matching entry the suggested fields and its canonical link. Raises
    ``parser.ParseError`` for a link that is not a tfwiki.net page,
    ``FigureNotFound`` when no page has such a figure, and the fetcher's errors
    unchanged.
    """
    asked, fragment = parser.parse_url(url)
    title, text = fetcher.page(asked)
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
        fields = parser.figure_fields(entry, page, factions, own_urls=(link,))
        if fields["faction"] is None and fields["bp_code"]:
            css, faction = _symbol(fetcher, fields["bp_code"], factions)
            fields["symbol_class"] = css
            if faction:
                fields["faction"] = {"value": faction, "source": "symbol class " + css}
        candidates.append(
            {
                "matched_by": how,
                "anchors": entry["anchors"],
                "link": link,
                "fields": fields,
                "block": "\n".join(entry["lines"]),
            }
        )
    return {
        "page": found[0][0],
        "fragment": fragment,
        "moved": moved,
        "character": parser.character(found[0][0]),
        "candidates": candidates,
    }
