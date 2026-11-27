"""Links to look up what a figure has sold for.

Nothing is fetched: each link opens a search on another site, with the figure's
name filled in, and the user reads the prices there. (eBay's sold-price API is
not open to individuals, and scraping its pages is against its terms.)
"""

import re
from urllib.parse import quote_plus, urlparse

from app import app

EBAY_SITE = "www.ebay.com"
TRANSFORMERLAND_PRICE_GUIDE = (
    "https://www.transformerland.com/transformers-price-guide.html"
)


AF411_SEARCH = "https://www.actionfigure411.com/common/search-results.php?g=3&term="
# A figure's page ends in its number (…/optimus-prime-age-of-extinction-9419.php);
# the guides and other pages around it do not.
AF411_FIGURE_PAGE = re.compile(r"-\d+\.php$")


def af411_search_url(figure):
    return AF411_SEARCH + quote_plus((figure.name or "").strip())


def check_af411_figure_page(value):
    """check_af411_link, and also refuses a guide or other page that is not a
    figure's own. Returns None for an empty box."""
    link = check_af411_link(value)
    if link and not AF411_FIGURE_PAGE.search(urlparse(link).path):
        raise ValueError(
            "That is not a figure's own ActionFigure411 page (its address ends "
            "in a number and .php)."
        )
    return link


def search_terms(figure):
    """The figure's name, led by its first franchise when the name leaves it out."""
    name = (figure.name or "").strip()
    franchise = figure.franchise[0].name if figure.franchise else ""
    if franchise and franchise.lower() not in name.lower():
        return "%s %s" % (franchise, name)
    return name


def check_af411_link(value):
    """The cleaned link, or None for an empty box. Raises ValueError if it is not
    a page on actionfigure411.com (the box takes the figure's own page)."""
    value = (value or "").strip()
    if not value:
        return None
    parts = urlparse(value)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not (
        host == "actionfigure411.com" or host.endswith(".actionfigure411.com")
    ):
        raise ValueError(
            "The ActionFigure411 link must be a page on actionfigure411.com."
        )
    return value


def price_check_links(figure):
    """[(label, url)]: eBay's sold listings, Transformerland and ActionFigure411."""
    name = (figure.name or "").strip()
    if not name:
        return []
    ebay = "https://%s/sch/i.html?_nkw=%s&LH_Sold=1&LH_Complete=1" % (
        app.config.get("EBAY_SITE", EBAY_SITE),
        quote_plus("transformers " + search_terms(figure)),
    )
    return [
        ("eBay sold listings", ebay),
        (
            "Transformerland",
            "https://www.transformerland.com/store/search.php?search="
            + quote_plus(name),
        ),
        (
            "ActionFigure411 (eBay averages)",
            figure.af411_link or af411_search_url(figure),
        ),
    ]
