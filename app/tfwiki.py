"""Import figures from tfwiki.net (a MediaWiki site) for review.

Pure helpers: fetching through the MediaWiki action API (robots.txt honored, one
request per second at most, raw responses cached on disk), reading the wikitext,
and mapping an infobox to Figure fields. Nothing here touches the database
except ``plan_import``/``save_import``, which only add rows and never edit or
delete one.
"""

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.robotparser import RobotFileParser

from app import db
from app.models import (
    Accessory,
    Category,
    Faction,
    Figure,
    Franchise,
    TFWikiLink,
    Tooling,
)

SITE = "https://tfwiki.net"
API = SITE + "/mediawiki/api.php"
WIKI = SITE + "/wiki/"
USER_AGENT = (
    "tfc-importer/1.0 (+https://github.com/eratosthene/tfc; personal collection app)"
)
# Seconds between requests, enforced in Fetcher itself; one request at a time.
MIN_DELAY = 2.0
ROBOTS_TTL = 24 * 3600


class FetchError(Exception):
    pass


class RobotsDisallowed(FetchError):
    pass


class RateLimited(FetchError):
    """The site answered 429 or 503: stop, do not retry."""


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 503):
            raise RateLimited(f"{url}: HTTP {exc.code}; stopping") from exc
        raise FetchError(f"Could not fetch {url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"Could not fetch {url}: {exc}") from exc


class Fetcher:
    """Fetch a page's wikitext, politely.

    ``get`` (the network call), ``sleep``, ``clock`` and ``wall`` can be replaced
    so tests make no network calls and do not wait.
    """

    def __init__(
        self,
        cache_dir,
        delay=MIN_DELAY,
        get=_http_get,
        sleep=time.sleep,
        clock=time.monotonic,
        wall=time.time,
        ignore_robots=False,
    ):
        self.ignore_robots = ignore_robots
        self._halted = False
        self.cache_dir = cache_dir
        self.delay = max(float(delay), MIN_DELAY)
        self._get = get
        self._sleep = sleep
        self._clock = clock
        self._wall = wall
        self._last = None
        self._robots = None

    def _cache_path(self, name):
        os.makedirs(self.cache_dir, exist_ok=True)
        return os.path.join(self.cache_dir, name)

    def _request(self, url):
        """One network request, at least ``delay`` seconds after the last."""
        if self._halted:
            raise RateLimited("an earlier request was rate limited; not retrying")
        if self._last is not None:
            wait = self.delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            return self._get(url)
        except RateLimited:
            self._halted = True
            raise
        finally:
            self._last = self._clock()

    def _robots_parser(self):
        if self._robots is None:
            path = self._cache_path("robots.txt")
            if os.path.exists(path) and self._wall() - os.path.getmtime(path) < (
                ROBOTS_TTL
            ):
                text = open(path, encoding="utf-8").read()
            else:
                text = self._request(SITE + "/robots.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            self._robots = RobotFileParser()
            self._robots.parse(text.splitlines())
        return self._robots

    def wikitext(self, page, refresh=False):
        """The page's wikitext, from the cache unless ``refresh``."""

        # Keyed by title, so a figure's page and its character's are one entry.
        page = _slug(page)
        path = self._cache_path("page-" + _file_key(page) + ".json")
        if not refresh and os.path.exists(path):
            raw = open(path, encoding="utf-8").read()
        else:
            url = (
                API
                + "?"
                + urllib.parse.urlencode(
                    {
                        "action": "parse",
                        "page": page,
                        "prop": "wikitext",
                        "redirects": 1,
                        "format": "json",
                    }
                )
            )
            if not self.ignore_robots and not self._robots_parser().can_fetch(
                USER_AGENT, url
            ):
                raise RobotsDisallowed(
                    "tfwiki.net's robots.txt disallows this client; not fetching "
                    + page
                )
            raw = self._request(url)
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
        return parse_response(raw, page)


def _file_key(page):
    safe = re.sub(r"[^A-Za-z0-9_()-]", "_", page)[:80]
    return safe + "-" + hashlib.sha256(page.encode()).hexdigest()[:8]


def parse_response(raw, page):
    """(canonical title, wikitext) from a MediaWiki ``action=parse`` response."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise FetchError(f"{page}: the response was not JSON") from exc
    if "error" in data:
        raise FetchError(f"{page}: {data['error'].get('info', 'MediaWiki error')}")
    try:
        parsed = data["parse"]
        return parsed["title"], parsed["wikitext"]["*"]
    except (KeyError, TypeError) as exc:
        raise FetchError(f"{page}: unexpected response shape") from exc


# --- reading wikitext -------------------------------------------------------
#
# A character's toys are on the page "Name_(Qualifier)/toys": a ===Toyline===
# heading, then per figure a line like
#   <ul class="iconlist">{{Bp-a1|'''Name''' (Class, 1984)}}</ul>
# an optional {{anchor|X}} before it (the "#X" of the app's figure links) and
# ":*''Label'': value" lines. Layout as recorded on 11 November 2026; there is
# no infobox. See tests/fixtures/tfwiki.


def clean(value):
    """Wikitext value to plain text."""
    value = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", value, flags=re.S)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"'{2,}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _items(value):
    parts = (
        p.strip().strip(chr(34)).strip() for p in re.split(r"[\n;,]", clean(value))
    )
    return [p for p in parts if p]


ITEM = re.compile(
    r'<ul class="iconlist">\{\{Bp-([a-z0-9]+)\|\s*(.*?)\}\}</ul>', re.I | re.S
)
HEADING = re.compile(r"^===\s*([^=].*?)\s*===\s*$")
ANCHOR = re.compile(r"\{\{anchor\|([^}|]+)\}\}", re.I)
LABEL = re.compile(r"^:+\*\s*''([^']+?)''\s*:?\s*(.*)$")
FACTIONS = {"a": "Autobot", "d": "Decepticon"}


def _slug(text):
    return re.sub(r"[\s_]+", "_", text.strip())


def _item_fields(code, body):
    """Fields from one Bp- line: name, class, year, faction."""
    m = re.match(r"(.*?)\s*\((.*)\)\s*$", body, re.S)
    name, detail = (m.group(1), m.group(2)) if m else (body, "")
    out = {"name": clean(name)}
    detail = clean(re.sub(r"<s>.*?</s>", "", detail))
    years = re.findall(r"\b(?:19|20)\d\d\b", detail)
    if years:
        out["release_year"] = int(years[0])
    parts = [p.strip() for p in detail.split(",")]
    kinds = [p for p in parts if p and not re.search(r"\b(?:19|20)\d\d\b", p)]
    if kinds:
        out["categories"] = kinds
    letters = re.sub(r"\d", "", code.lower())
    if letters in FACTIONS:  # "a1" is an Autobot; "a1d1" or "multi" is no one side
        out["faction"] = FACTIONS[letters]
    return out


BULLETS = {
    "accessories": ("accessories", "accessory"),
    "takara_id": ("takara id number", "takaratomy id number", "takara id"),
    "hasbro_id": ("hasbro id number", "hasbro id"),
}


def _bullet_fields(bullets):
    out = {}
    for label, value in bullets:
        label = label.strip().rstrip(":").strip().lower()
        for field, names in BULLETS.items():
            if label in names and field not in out:
                items = _items(value)
                if field == "accessories":
                    out[field] = items
                elif items:
                    out[field] = ", ".join(items)
    return out


def split_page(title, wikitext, fragment=None):
    """The figures on a ``/toys`` page, in page order.

    Each is {"section": a label for review, "fragment": the "#" part of its
    link, "fields": {...}}; the toyline heading is its franchise. With
    ``fragment`` only the figure whose anchor (or toyline heading) matches.
    """
    items, heading, anchor, cur = [], "", None, None
    for line in wikitext.splitlines():
        h = HEADING.match(line)
        if h:
            heading, anchor, cur = clean(h.group(1)), None, None
            continue
        a = ANCHOR.search(line)
        if a:
            anchor = a.group(1).strip()
        m = ITEM.search(line)
        if m:
            fields = _item_fields(m.group(1), m.group(2))
            cur = {
                "heading": heading,
                "fragment": _slug(anchor or heading or fields["name"]),
                "fields": fields,
                "bullets": [],
            }
            items.append(cur)
            anchor = None
            continue
        b = LABEL.match(line)
        if b and cur is not None:
            cur["bullets"].append((b.group(1), b.group(2)))
    out = []
    for it in items:
        it["fields"].update(_bullet_fields(it.pop("bullets")))
        heading = it.pop("heading")
        if heading:
            it["fields"]["franchise"] = [heading]
        it["section"] = f"{it['fields']['name']} ({heading or 'no toyline'})"
        if fragment is None or _slug(fragment).lower() == it["fragment"].lower():
            out.append(it)
    return out


def character_title(title):
    """The character page behind a ``/toys`` page."""
    return re.sub(r"/(Generations_)?toys$", "", title)


def link_name(title):
    """The TFWikiLink name for a page: the title without its "(qualifier)"."""
    return re.sub(r"\s*\([^)]*\)$", "", character_title(title)).strip()


def page_url(title):
    return WIKI + urllib.parse.quote(_slug(title), safe="()!,'_-.:/")


# --- database ---------------------------------------------------------------

NAMED = {
    "faction": (Faction, True),
    "franchise": (Franchise, False),  # needs a start year, so never created
    "tooling": (Tooling, True),
    "accessories": (Accessory, True),
    "categories": (Category, True),
}


def _find(model, name):
    return model.query.filter(db.func.lower(model.name) == name.lower()).first()


def plan_import(title, section):
    """Work out what importing one section would do.

    Returns a dict: ``figure`` (a field->value dict), ``character_link``,
    ``figure_link``, ``new`` (names of rows that would be created), ``problems``
    (why it cannot be saved) and ``existing`` (a message when the figure is
    already in the database; then nothing is to be saved).
    """
    f = section["fields"]
    char = {"name": link_name(title), "link": page_url(character_title(title))}
    fig = {
        "name": link_name(title),
        "link": f"{page_url(title)}#{section['fragment']}",
    }
    plan = {
        "section": section["section"],
        "figure": dict(f),
        "character_link": char,
        "figure_link": fig,
        "new": [],
        "problems": [],
        "existing": None,
    }
    plan["figure"]["name"] = f.get("name") or link_name(title)
    existing = TFWikiLink.query.filter_by(link=fig["link"]).first()
    if existing and Figure.query.filter_by(figure_link_id=existing.id).first():
        plan["existing"] = f"already in the collection via {fig['link']}"
        return plan
    same = Figure.query.filter(
        db.func.lower(Figure.name) == plan["figure"]["name"].lower(),
        Figure.release_year == f.get("release_year"),
    ).first()
    if same and f.get("release_year"):
        plan["existing"] = f"a figure named {same.name} ({same.release_year}) exists"
        return plan
    if not f.get("release_year"):
        plan["problems"].append("no release year found")
    if not f.get("faction"):
        plan["problems"].append("no faction found")
    for key, (model, creatable) in NAMED.items():
        names = f.get(key)
        names = [names] if isinstance(names, str) else (names or [])
        for n in names:
            if _find(model, n) is None:
                if creatable:
                    plan["new"].append(f"{model.__name__} {n}")
                else:
                    plan["problems"].append(
                        f"{model.__name__} {n!r} does not exist; add it first"
                    )
    if not TFWikiLink.query.filter_by(link=char["link"]).first():
        plan["new"].append(f"TFWikiLink {char['link']}")
    plan["new"].append(f"TFWikiLink {fig['link']}")
    return plan


def format_diff(plan):
    """The review text: every field the import would set, as additions."""
    lines = [f"=== {plan['section']}"]
    if plan["existing"]:
        return "\n".join(lines + [f"  skip: {plan['existing']}"])
    for k, v in plan["figure"].items():
        lines.append(f"+ {k}: {', '.join(v) if isinstance(v, list) else v}")
    lines.append(f"+ character: {plan['character_link']['link']}")
    lines.append(f"+ figure_link: {plan['figure_link']['link']}")
    lines += [f"+ new row: {n}" for n in plan["new"]]
    lines += [f"! cannot save: {p}" for p in plan["problems"]]
    return "\n".join(lines)


def _get_or_create(model, name):
    obj = _find(model, name)
    if obj is None:
        obj = model(name=name)
        db.session.add(obj)
    return obj


def _link(spec):
    obj = TFWikiLink.query.filter_by(link=spec["link"]).first()
    if obj is None:
        obj = TFWikiLink(name=spec["name"], link=spec["link"])
        db.session.add(obj)
    return obj


def save_import(plan):
    """Add the figure (and rows it needs). Refuses a plan with problems or an
    existing figure, so an import can never overwrite a record."""
    if plan["existing"] or plan["problems"]:
        raise ValueError("this import cannot be saved")
    f = plan["figure"]
    figure = Figure(
        name=f["name"],
        release_year=f["release_year"],
        faction=_get_or_create(Faction, f["faction"]),
        character=_link(plan["character_link"]),
        figure_link=_link(plan["figure_link"]),
        exclusive_to=f.get("exclusive_to"),
        hasbro_id=f.get("hasbro_id"),
        takara_id=f.get("takara_id"),
        franchise=[_find(Franchise, n) for n in f.get("franchise", [])],
        tooling=[_get_or_create(Tooling, n) for n in f.get("tooling", [])],
        accessories=[_get_or_create(Accessory, n) for n in f.get("accessories", [])],
        categories=[_get_or_create(Category, n) for n in f.get("categories", [])],
    )
    db.session.add(figure)
    db.session.commit()
    return figure
