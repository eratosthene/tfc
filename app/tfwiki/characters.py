"""A character's own wiki page, and where it is now.

A character's link names its wiki page (``https://tfwiki.net/wiki/Battletrap``). The
wiki renames and splits pages: ``Alpha_Trion_(G1)`` became ``Alpha_Trion``, and
``Battletrap`` became a disambiguation page that lists ``Battletrap (G1)``,
``(Cyberverse)`` and ``(ROTB)``. For a rename the character moves to the page's
current title. For a disambiguation page the right namesake is the one the
character's own figures are on, and only if exactly one of the listed pages is.
"""

from app.tfwiki import parser
from app.tfwiki.fetcher import Disabled, FetchError, PageNotFound, RateLimited
from app.tfwiki.modernise import (
    ERROR,
    LIMIT,
    NO_PAGE,
    NOT_CACHED,
    OutOfBudget,
    Result,
)

CURRENT = "current"
RENAMED = "renamed"  # the page redirects to another one: use its current title
DISAMBIGUATED = "disambiguated"  # the figures pick one page the name lists
UNDECIDED = "undecided"  # a disambiguation page the figures do not decide
CONFLICT = "conflict"  # another character already has the new link

LABELS = {
    RENAMED: "the page was renamed (will be rewritten)",
    DISAMBIGUATED: "now a disambiguation page, settled by the character's figures (will be rewritten)",
    CURRENT: "already current",
    UNDECIDED: "now a disambiguation page and the figures do not settle it (left alone)",
    CONFLICT: "the new link belongs to another character already (left alone)",
    NO_PAGE: "the page does not exist on the wiki",
    NOT_CACHED: "page not in the cache",
    LIMIT: "not looked at (fetch limit reached)",
    ERROR: "could not be checked",
}
REWRITES = (RENAMED, DISAMBIGUATED)


def same_page(a, b):
    """The same wiki page: separators unified, and the first letter's case ignored
    (MediaWiki capitalises it)."""
    a, b = parser.normalize_title(a), parser.normalize_title(b)
    return a[:1].upper() + a[1:] == b[:1].upper() + b[1:]


def check(fetcher, link, evidence):
    """Where the page a character's ``link`` names is now.

    ``evidence()`` is called only for a disambiguation page, and returns
    (set of normalised character-page titles this character's figures are on, set of
    statuses for figure pages that could not be read yet). Raises RateLimited, which
    the caller must stop on; every other problem is a Result.
    """
    try:
        title, _fragment = parser.parse_url(link)
        canonical, text = fetcher.page(title)
    except OutOfBudget as error:
        return Result(LIMIT, str(error), None)
    except Disabled as error:
        return Result(NOT_CACHED, str(error), None)
    except RateLimited:
        raise
    except PageNotFound as error:
        return Result(NO_PAGE, str(error), None)
    except (FetchError, parser.ParseError) as error:
        return Result(ERROR, str(error), None)
    if parser.is_disambiguation(text):
        targets = parser.disambiguation_targets(text)
        pages, missing = evidence()
        on = [t for t in targets if t in pages]
        if len(on) == 1:
            return Result(DISAMBIGUATED, canonical, parser.page_url(on[0]))
        if not on and missing:
            return Result(
                sorted(missing)[0], "its figures' pages are not all read", None
            )
        return Result(
            UNDECIDED,
            "%s lists %s"
            % (canonical, ", ".join(t.replace("_", " ") for t in targets)),
            None,
        )
    if same_page(canonical, title):
        return Result(CURRENT, canonical, None)
    return Result(RENAMED, canonical, parser.page_url(canonical))
