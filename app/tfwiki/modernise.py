"""Old-style figure links and where the figure lives now.

Long character pages moved their toys to ``Name/toys``, so a link saved as
``Alpha_Trion_(G1)#Legacy`` should be ``Alpha_Trion/toys#Legacy``. A link is
only called rewritable when the toys page really has that ``{{anchor|...}}``.
"""

from collections import namedtuple

from app.tfwiki import parser
from app.tfwiki.fetcher import Disabled, FetchError, PageNotFound, RateLimited
from app.tfwiki.figure import FigureNotFound, FigureOnSeveralPages, read_figure

# status is one of the names below; ``new`` is set for "rewrite" only.
Result = namedtuple("Result", "status detail new")

REWRITE = "rewrite"
CURRENT = "current"  # the figure is still on the page the link names
CASE = "case"  # the section is only found ignoring capital letters: left alone
AMBIGUOUS = "ambiguous"  # the section is on more than one page: left alone
SEVERAL_PAGES = "several_pages"  # a disambiguation page lists more than one that has it
NO_PAGE = "no_page"
NO_FIGURE = "no_figure"
NOT_CACHED = "not_cached"
LIMIT = "limit"  # the per-run fetch limit was reached
ERROR = "error"

LABELS = {
    REWRITE: "will be rewritten",
    CURRENT: "already current (the figure is on that page)",
    CASE: "the section is only found ignoring capital letters (left alone)",
    AMBIGUOUS: "the section is on more than one page (left alone)",
    SEVERAL_PAGES: "now a disambiguation page, and several of its pages have it (left alone)",
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


def check(fetcher, link):
    """Where the figure a link points at is now. Raises RateLimited, which the
    caller must stop on; every other problem is a Result."""
    try:
        result = read_figure(fetcher, link, search_all=True, fields=False)
    except OutOfBudget as error:
        return Result(LIMIT, str(error), None)
    except Disabled as error:
        return Result(NOT_CACHED, str(error), None)
    except RateLimited:
        raise
    except PageNotFound as error:
        return Result(NO_PAGE, str(error), None)
    except FigureOnSeveralPages as error:
        return Result(SEVERAL_PAGES, str(error), None)
    except FigureNotFound as error:
        return Result(NO_FIGURE, str(error), None)
    except (FetchError, parser.ParseError) as error:
        return Result(ERROR, str(error), None)
    fragment = link.partition("#")[2]
    if result.get("disambiguated"):
        # The name is now a disambiguation page and exactly one page it lists has
        # this section, by exact name: the link belongs on that page.
        page = result["candidates"][0]["link"].split("#", 1)[0]
        return Result(REWRITE, result["page"], page + "#" + fragment)
    if not result["moved"]:
        return Result(CURRENT, result["page"], None)
    # The figure is on another page now: a toys page the character page points at, or
    # the page a renamed page redirects to. The section must be there by exact name
    # (an {{anchor}} or a heading, capitals included).
    exact = [c for c in result["candidates"] if _is_exact(c, fragment)]
    if not exact:
        return Result(CASE, result["page"], None)
    pages = sorted({c["link"].split("#", 1)[0] for c in exact})
    if len(pages) > 1:
        return Result(AMBIGUOUS, ", ".join(pages), None)
    # Keep the fragment exactly as it was saved (.28-style escapes and all).
    return Result(REWRITE, result["page"], pages[0] + "#" + fragment)


def _is_exact(candidate, fragment):
    """The candidate's section has exactly this name: an anchor, the heading, the
    sub-heading, or the id the wiki gave a repeated heading."""
    names = (
        candidate["anchors"]
        + [candidate["heading"], candidate["subheading"]]
        + candidate["heading_ids"]
    )
    return any(n and parser.same_fragment(fragment, n) for n in names)
