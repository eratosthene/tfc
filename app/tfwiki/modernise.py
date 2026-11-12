"""Old-style figure links and where the figure lives now.

Long character pages moved their toys to ``Name/toys``, so a link saved as
``Alpha_Trion_(G1)#Legacy`` should be ``Alpha_Trion/toys#Legacy``. A link is
only called rewritable when the toys page really has that ``{{anchor|...}}``.
"""

import re
import urllib.parse
from collections import namedtuple

from app.tfwiki import parser
from app.tfwiki.fetcher import Disabled, FetchError, PageNotFound, RateLimited
from app.tfwiki.figure import FigureNotFound, read_figure

# status is one of the names below; ``new`` is set for "rewrite" only.
Result = namedtuple("Result", "status detail new")

REWRITE = "rewrite"
CURRENT = "current"  # the figure is still on the page the link names
REDIRECT = "redirect"  # the page is a redirect, not a toys page: left alone
HEADING = "heading"  # the fragment matches a heading, not an anchor: left alone
CASE = "case"  # the anchor differs only in capital letters: left alone
AMBIGUOUS = "ambiguous"  # more than one entry has that anchor: left alone
NO_PAGE = "no_page"
NO_FIGURE = "no_figure"
NOT_CACHED = "not_cached"
LIMIT = "limit"  # the per-run fetch limit was reached
ERROR = "error"

LABELS = {
    REWRITE: "will be rewritten",
    CURRENT: "already current (the figure is on that page)",
    REDIRECT: "page only redirects (left alone)",
    HEADING: "matches a heading, not an anchor (left alone)",
    CASE: "the anchor differs in capital letters (left alone)",
    AMBIGUOUS: "the anchor is on more than one entry (left alone)",
    NO_PAGE: "the page does not exist on the wiki",
    NO_FIGURE: "no figure for that fragment on the wiki",
    NOT_CACHED: "page not in the cache",
    LIMIT: "not looked at (fetch limit reached)",
    ERROR: "could not be checked",
}


class OutOfBudget(Disabled):
    """The run's fetch limit has been used up."""


class Budget:
    """A fetcher that lets at most ``limit`` network fetches through."""

    def __init__(self, fetcher, limit):
        self.fetcher = fetcher
        self.limit = limit
        self.used = 0

    def cached(self, title):
        return self.fetcher.cached(title)

    def page(self, title, refresh=False):
        if not refresh and not self.fetcher.cached(title) and self.fetcher.enabled:
            if self.limit is not None and self.used >= self.limit:
                raise OutOfBudget("fetch limit reached")
            self.used += 1
        return self.fetcher.page(title, refresh)


def old_style(link):
    """A tfwiki.net page link with a #fragment, on a page that is not a toys page."""
    try:
        title, fragment = parser.parse_url(link)
    except parser.ParseError:
        return False
    return bool(fragment) and not parser.TOYS_SUFFIX.search(title)


def _same(text):
    """A fragment or anchor with escapes decoded and separators unified, but
    with its capital letters: the wiki's anchors are case-sensitive."""
    text = parser.decode_anchor(urllib.parse.unquote(text))
    return re.sub(r"[\s_]+", " ", text).strip()


def check(fetcher, link):
    """Where the figure a link points at is now. Raises RateLimited, which the
    caller must stop on; every other problem is a Result."""
    try:
        result = read_figure(fetcher, link, search_all=True)
    except OutOfBudget as error:
        return Result(LIMIT, str(error), None)
    except Disabled as error:
        return Result(NOT_CACHED, str(error), None)
    except RateLimited:
        raise
    except PageNotFound as error:
        return Result(NO_PAGE, str(error), None)
    except FigureNotFound as error:
        return Result(NO_FIGURE, str(error), None)
    except (FetchError, parser.ParseError) as error:
        return Result(ERROR, str(error), None)
    if not result["moved"]:
        return Result(CURRENT, result["page"], None)
    if not parser.TOYS_SUFFIX.search(result["page"]):
        return Result(REDIRECT, result["page"], None)
    anchored = [c for c in result["candidates"] if c["matched_by"] == "anchor"]
    if not anchored:
        return Result(HEADING, result["page"], None)
    if len(anchored) > 1:
        return Result(AMBIGUOUS, result["page"], None)
    fragment = link.partition("#")[2]
    if not any(_same(fragment) == _same(a) for a in anchored[0]["anchors"]):
        return Result(CASE, result["page"], None)
    # Keep the fragment exactly as it was saved (.28-style escapes and all).
    page = anchored[0]["link"].split("#", 1)[0]
    new = page + "#" + fragment
    return Result(REWRITE, result["page"], new)
