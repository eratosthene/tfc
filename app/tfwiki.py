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
USER_AGENT = "tfc-importer/1.0 (personal collection app; one page at a time)"
MIN_DELAY = 1.0
ROBOTS_TTL = 24 * 3600


class FetchError(Exception):
    pass


class RobotsDisallowed(FetchError):
    pass


def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
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
    ):
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
        if self._last is not None:
            wait = self.delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            return self._get(url)
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

        key = hashlib.sha256(page.encode()).hexdigest()[:16]
        path = self._cache_path(f"page-{key}.json")
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
            if not self._robots_parser().can_fetch(USER_AGENT, url):
                raise RobotsDisallowed(
                    "tfwiki.net's robots.txt disallows this client; not fetching "
                    + page
                )
            raw = self._request(url)
            with open(path, "w", encoding="utf-8") as f:
                f.write(raw)
        return parse_response(raw, page)


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


def _split_top(text, sep):
    """Split on ``sep`` outside [[ ]] and {{ }}."""
    parts, depth, cur, i = [], 0, [], 0
    while i < len(text):
        two = text[i : i + 2]
        if two in ("[[", "{{"):
            depth += 1
            cur.append(two)
            i += 2
        elif two in ("]]", "}}"):
            depth -= 1
            cur.append(two)
            i += 2
        elif text[i] == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(text[i])
            i += 1
    parts.append("".join(cur))
    return parts


def find_templates(text):
    """Every top-level ``{{name|...}}`` as (name, {field: raw value})."""
    found, i = [], 0
    while True:
        start = text.find("{{", i)
        if start < 0:
            return found
        depth, j = 0, start
        while j < len(text):
            two = text[j : j + 2]
            if two == "{{":
                depth += 1
                j += 2
            elif two == "}}":
                depth -= 1
                j += 2
                if depth == 0:
                    break
            else:
                j += 1
        if depth != 0:
            return found  # unbalanced braces: ignore the rest
        parts = _split_top(text[start + 2 : j - 2], "|")
        fields = {}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                fields[re.sub(r"[\s_]+", " ", k).strip().lower()] = v.strip()
        found.append((parts[0].strip(), fields))
        i = j


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
    return [p.strip() for p in re.split(r"[\n;,]", clean(value)) if p.strip()]


# Each Figure field and the infobox parameter names it can come from.
ALIASES = {
    "name": ("name", "title"),
    "release_year": ("year", "release year", "released", "release"),
    "franchise": ("franchise", "line", "series"),
    "faction": ("faction", "allegiance"),
    "tooling": ("tooling",),
    "accessories": ("accessories", "accessory"),
    "categories": ("category", "categories", "class", "size class"),
    "exclusive_to": ("exclusive to", "exclusive", "retailer"),
    "hasbro_id": ("hasbro id", "hasbro", "hasbro sku"),
    "takara_id": ("takara id", "takara", "takara sku"),
}
LIST_FIELDS = ("franchise", "tooling", "accessories", "categories")


def map_infobox(fields):
    """Map an infobox's parameters to Figure fields (plain values, no rows)."""
    out = {}
    for target, names in ALIASES.items():
        raw = next((fields[n] for n in names if fields.get(n)), None)
        if raw is None:
            continue
        if target in LIST_FIELDS:
            value = _items(raw)
        elif target == "release_year":
            m = re.search(r"\b(19|20)\d\d\b", clean(raw))
            value = int(m.group(0)) if m else None
        else:
            value = clean(raw)
        if value:
            out[target] = value
    return out


def is_infobox(name):
    n = re.sub(r"[\s_]+", "", name.lower())
    return n.startswith("toyinfobox") or n.startswith("infobox")


def split_page(title, wikitext, fragment=None):
    """Figure sections of a page: [{"section", "fields"}], one per infobox.

    A heading ``== Name ==`` starts a section. An infobox before any heading is
    the section named after the page. With ``fragment`` (as in a link's ``#``
    part) only that section is returned.
    """
    pieces = re.split(r"^=+\s*(.*?)\s*=+\s*$", wikitext, flags=re.M)
    sections = [(title, pieces[0])]
    sections += list(zip(pieces[1::2], pieces[2::2]))
    out = []
    for heading, body in sections:
        heading = clean(heading)
        for name, fields in find_templates(body):
            if is_infobox(name) and (
                fragment is None or _slug(heading) == _slug(fragment)
            ):
                out.append({"section": heading, "fields": map_infobox(fields)})
                break
    return out


def _slug(text):
    return re.sub(r"[\s_]+", "_", text.strip())


def link_name(title):
    """The TFWikiLink name for a page: the title without its "(qualifier)"."""
    return re.sub(r"\s*\([^)]*\)$", "", title).strip()


def page_url(title):
    return WIKI + urllib.parse.quote(_slug(title), safe="()!,'_-.:")


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
    base = page_url(title)
    char = {"name": link_name(title), "link": base}
    fig = {"name": link_name(title), "link": f"{base}#{_slug(section['section'])}"}
    plan = {
        "section": section["section"],
        "figure": {k: v for k, v in f.items()},
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
