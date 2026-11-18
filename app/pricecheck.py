"""Links to look up what a figure has sold for.

Nothing is fetched: each link opens a search on another site, with the figure's
name filled in, and the user reads the prices there. (eBay's sold-price API is
not open to individuals, and scraping its pages is against its terms.)
"""

from urllib.parse import quote_plus, urlparse

from app import app

EBAY_SITE = "www.ebay.com"
TRANSFORMERLAND_PRICE_GUIDE = (
    "https://www.transformerland.com/transformers-price-guide.html"
)


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
            figure.af411_link
            or "https://www.actionfigure411.com/common/search-results.php?g=3&term="
            + quote_plus(name),
        ),
    ]
