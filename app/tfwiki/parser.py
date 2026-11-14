"""Read figure sections out of tfwiki.net wikitext.

Pure functions, no network and no database. tfwiki.net (MediaWiki 1.19) has no
infobox; a character's toys are on ``Name/toys`` (or ``Name/Generations_toys``,
or under ``==Toys==`` on the character page itself). Two layouts exist, both
handled here, as recorded in tests/fixtures/tfwiki:

new  ``<ul class="iconlist">{{Bp-a1|'''Name''' (Deluxe Class, 2024)}}</ul>``
     followed by ``:*''Accessories'': ...`` bullets
old  ``*'''Name''' (Voyager, 2012)`` followed by ``**''Accessories:'' ...``

Under a ``===Toyline===`` heading, optionally preceded by ``{{anchor|X}}`` and
a ``[[File:...]]`` picture. The ``#fragment`` of a figure's link is either an
anchor or the text of a heading. Everything returned is a *suggestion* with the
text it came from, for the review step to show; nothing here decides.
"""

import re
import urllib.parse

from app.tfwiki.fetcher import SITE, normalize_title

WIKI = SITE + "/wiki/"

# Faction words that may start a figure's name ("Autobot Blaster"). The caller
# passes the real Faction names; these are only the default.
DEFAULT_FACTIONS = ("Autobot", "Decepticon", "Maximal", "Predacon")
# Single-letter Bp- codes (Bp-a1, Bp-d2, Bp-m1p1 is two sides: no single faction).
BP_FACTIONS = {"a": "Autobot", "d": "Decepticon", "m": "Maximal", "p": "Predacon"}


class ParseError(ValueError):
    pass


# --- links and anchors ------------------------------------------------------


def decode_anchor(text):
    """MediaWiki's old fragment escaping: ``.28`` is ``(`` and so on.

    The escapes are the bytes of the UTF-8 text, so a run of them is decoded
    together: ``.C3.97`` is ``\u00d7`` (not ``\u00c3`` and a control character). A
    run that is not valid UTF-8 is read as Latin-1, as before.
    """

    def run(found):
        raw = bytes(int(h, 16) for h in re.findall(r"\.([0-9A-F]{2})", found.group(0)))
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    return re.sub(r"(?:\.[0-9A-F]{2})+", run, text)


def norm(text):
    """A fragment or heading in a comparable form."""
    text = urllib.parse.unquote(text)
    return re.sub(r"[\s_]+", " ", decode_anchor(text)).strip().casefold()


def page_url(title, fragment=None):
    url = WIKI + urllib.parse.quote(normalize_title(title), safe="()!,'_-.:/&")
    if fragment:
        url += "#" + urllib.parse.quote(normalize_title(fragment), safe="()!,'_-.:&")
    return url


def parse_url(url):
    """(page title, fragment or None) from a tfwiki.net/wiki URL."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or parts.netloc.lower() not in (
        "tfwiki.net",
        "www.tfwiki.net",
    ):
        raise ParseError("Not a tfwiki.net link")
    if not parts.path.startswith("/wiki/") or len(parts.path) <= len("/wiki/"):
        raise ParseError("Not a tfwiki.net page link (expected /wiki/Page_Name)")
    title = normalize_title(urllib.parse.unquote(parts.path[len("/wiki/") :]))
    fragment = urllib.parse.unquote(parts.fragment) or None
    return title, fragment


TOYS_SUFFIX = re.compile(r"/(?:Generations[ _])?toys$", re.I)


def character_page(title):
    """The character page behind a toys page."""
    return TOYS_SUFFIX.sub("", title)


def split_title(title):
    """(name, qualifier) of a character page: ``Bumblebee (Animated)``."""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)$", character_page(title))
    return (m.group(1), m.group(2)) if m else (character_page(title), None)


LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
SKIP_NAMESPACES = ("file:", "image:", "category:", "media:")


def resolve_link(target, here):
    """(page, fragment) for a ``[[target]]`` found on page ``here``, or None."""
    target = target.strip().lstrip(":")
    if target.lower().startswith(SKIP_NAMESPACES):
        return None
    page, _, fragment = target.partition("#")
    page = normalize_title(page) if page.strip() else here
    return normalize_title(page), (fragment.strip() or None)


def links(text, here):
    """Every wikilink in ``text`` as {text, page, fragment, url, start}."""
    out = []
    for m in LINK.finditer(text):
        resolved = resolve_link(m.group(1), here)
        if resolved is None:
            continue
        page, fragment = resolved
        out.append(
            {
                "text": clean(m.group(2) or m.group(1).split("#")[0] or page),
                "page": page,
                "fragment": fragment,
                "url": page_url(page, fragment),
                "start": m.start(),
            }
        )
    return out


def toys_pointers(wikitext, here):
    """Pages a character page says hold its toys: ``{{main|Name/toys}}``."""
    out = []
    for m in re.finditer(r"\{\{main\|([^}]*)\}\}", wikitext, re.I):
        for part in m.group(1).split("|"):
            page = normalize_title(part.split("#")[0])
            if TOYS_SUFFIX.search(page) and page not in out:
                out.append(page)
    return out


# --- wikitext to text -------------------------------------------------------


def clean(value):
    """Wikitext to plain text."""
    value = re.sub(r"<ref[^>/]*>.*?</ref>|<ref[^>]*/>", "", value, flags=re.S)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"<br\s*/?>", ", ", value, flags=re.I)
    value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    value = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", value, flags=re.I)
    value = re.sub(r"\[\[:?(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", value)
    value = re.sub(r"'{2,}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def split_top_level(text, sep=","):
    """Split on ``sep`` outside parentheses."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == sep and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


# --- the page as entries ----------------------------------------------------

HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
ITEM_NEW = re.compile(r"\{\{Bp-([A-Za-z0-9]+)\|(.*)\}\}")
ITEM_OLD = re.compile(r"^\*\s*('''.*)$")
BULLET = re.compile(r"^[:*]+\s*''([^']+?)''\s*:?\s*(.*)$")
ANCHOR = re.compile(r"\{\{anchor\|([^}|]+)\}\}", re.I)
FILE = re.compile(r"\[\[(?:File|Image):([^\]|]+)", re.I)
GALLERY_FILE = re.compile(r"^(?:File|Image):([^|\n]+)", re.I)
SPACER = re.compile(
    r"^\s*(\{\{-+\}\}|\{\{clear\}\}|<br ?/?>|<gallery.*|</gallery>)?\s*$", re.I
)


def _is_lead(line):
    return bool(
        SPACER.match(line)
        or ANCHOR.search(line)
        and not ITEM_NEW.search(line)
        or FILE.match(line.strip())
        or GALLERY_FILE.match(line.strip())
    )


def _files(lines):
    """File names in ``lines``: ``[[File:X|...]]`` links, then gallery lines."""
    text = "\n".join(lines)
    names = [m.group(1).strip() for m in FILE.finditer(text)]
    return names + [
        m.group(1).strip()
        for m in (GALLERY_FILE.match(ln.strip()) for ln in lines)
        if m
    ]


def entries(wikitext, title):
    """Every figure entry on a toys page, in page order.

    Each is a dict: ``heading`` (the ===toyline===), ``subheading``,
    ``anchors``, ``header`` (the first line, with the name), ``code`` (Bp-
    template code or None), ``bullets`` [(label, value)], ``paragraphs``
    (prose lines), ``components`` (the ``:{{Bp-..}}`` parts of a multi-pack),
    ``picture`` (first File name or None) and ``lines`` (the raw block), and
    ``heading_ids``: the wiki's anchor ids for the toyline and sub-heading, which
    number a repeated heading (``Name``, ``Name_2``) across the whole page.

    A toyline heading with no such figure line under it (a character whose toys
    are described in prose, one section per toyline) gives one entry for the
    section, with an empty ``header`` and ``code`` None.

    Toylines are ``===level 3===`` headings under a ``==Toys==`` heading; a page
    with no such heading (a long toys page where every toyline is its own
    ``==level 2==``) is read whole, with level 2 as the toyline.
    """
    lines = wikitext.splitlines()
    start, end, has_toys = _toys_range(lines)
    top = 3 if has_toys else 2  # the heading level of a toyline
    ids = heading_ids(lines)
    starts, heads, where = [], {}, {}
    heading = sub = ""
    hline = sline = None  # the lines of the current toyline and sub-heading
    for i in range(start, end):
        line = lines[i]
        h = HEADING.match(line)
        if h:
            level = len(h.group(1))
            if level == top:
                heading, sub, hline, sline = clean(h.group(2)), "", i, None
            elif level > top:
                sub, sline = clean(h.group(2)), i
            heads[i] = (level, heading, sub)
            continue
        if line.lstrip().startswith(":") and ITEM_NEW.search(line):
            continue  # a part of the multi-pack above
        if ITEM_NEW.search(line) or ITEM_OLD.match(line):
            starts.append((i, heading, sub))
            where[i] = (hline, sline)
    out = []
    for n, (i, heading, sub) in enumerate(starts):
        floor = starts[n - 1][0] + 1 if n else start
        floor = max([floor] + [j + 1 for j in heads if j < i])
        lead, j = [], i - 1
        while j >= floor and _is_lead(lines[j]):
            lead.append(lines[j])
            j -= 1
        lead.reverse()
        stop = starts[n + 1][0] if n + 1 < len(starts) else end
        stop = min([stop] + [j for j in heads if i < j < stop])
        found = [ids[x] for x in where[i] if x is not None]
        out.append((i, _entry(lines[i:stop], lead, heading, sub, title, found)))
    for i, (level, heading, _sub) in heads.items():
        if level != top or not has_toys:  # prose sections only under ==Toys==
            continue
        stop = min(
            [j for j, (lvl, _h, _s) in heads.items() if j > i and lvl <= top] + [end]
        )
        if any(i < s < stop for s, _h, _sub2 in starts):
            continue
        block = lines[i + 1 : stop]
        if any(line.strip() and not SPACER.match(line) for line in block):
            out.append((i, _entry(block, [], heading, "", title, [ids[i]])))
    return [entry for _i, entry in sorted(out, key=lambda pair: pair[0])]


def heading_ids(lines):
    """{line number: the wiki's anchor id} for every heading on the page.

    MediaWiki makes a repeated heading's id unique by numbering it: the first
    ``Star Wars Transformers`` is ``Star_Wars_Transformers`` and the second (a toyline
    under ``==Toys==``, after one under ``==Fiction==``) is
    ``Star_Wars_Transformers_2``, so a link to the second needs the whole page counted.
    """
    seen, out = {}, {}
    for i, line in enumerate(lines):
        h = HEADING.match(line)
        if h:
            base = normalize_title(clean(h.group(2)))
            seen[base] = seen.get(base, 0) + 1
            out[i] = base if seen[base] == 1 else "%s_%d" % (base, seen[base])
    return out


def _toys_range(lines):
    begin = None
    for i, line in enumerate(lines):
        h = HEADING.match(line)
        if h and len(h.group(1)) == 2:
            if begin is not None:
                return begin, i, True
            if clean(h.group(2)).lower() == "toys":
                begin = i + 1
    if begin is not None:
        return begin, len(lines), True
    return 0, len(lines), False


def _entry(block, lead, heading, sub, title, heading_ids=()):
    first = block[0]
    new = ITEM_NEW.search(first)
    old = ITEM_OLD.match(first)
    skip = 1 if (new or old) else 0  # a section has no header line
    entry = {
        "heading": heading,
        "subheading": sub,
        "heading_ids": list(heading_ids),
        "anchors": [m.group(1).strip() for line in lead for m in ANCHOR.finditer(line)],
        "code": new.group(1).lower() if new else None,
        "header": new.group(2) if new else old.group(1) if old else "",
        "bullets": [],
        "paragraphs": [],
        "components": [],
        "lines": block,
    }
    pictures = _files(lead)
    for line in block[skip:]:
        part = ITEM_NEW.search(line)
        if part and line.lstrip().startswith(":"):
            entry["components"].append(
                {
                    "text": clean(part.group(2)),
                    "links": links(part.group(2), title),
                }
            )
            continue
        b = BULLET.match(line)
        if b and (skip or _field_label(b.group(1))):
            entry["bullets"].append((b.group(1), b.group(2)))
        elif line.strip() and not line.startswith(("{{", "<", "*", "=")):
            entry["paragraphs"].append(line.lstrip(": "))
    pictures = pictures or _files(block)
    entry["picture"] = pictures[0] if pictures else None
    return entry


def _field_label(label):
    """True if ``label`` names a field we read (Accessories, Hasbro ID...). In a
    prose section an italic sentence also looks like ``''label'': value``, so only
    these count as bullets there."""
    label = label.strip().rstrip(":").strip().lower()
    return any(label in names for names in FIELD_LABELS.values())


def same_fragment(a, b):
    """True if two fragments or headings name the same section, escapes decoded
    and separators unified, but with their capitals: the wiki's anchors and
    headings are case-sensitive."""

    def plain(text):
        return re.sub(r"[\s_]+", " ", decode_anchor(urllib.parse.unquote(text))).strip()

    return plain(a) == plain(b)


# --- disambiguation pages ---------------------------------------------------

DISAMBIG_ITEM = re.compile(
    r"^\{\{disamb\|(?:y=(?:\[\[[^\]]*\]\]|[^|])*\|)?\s*\[\[([^\]|#]+)", re.I
)


def is_disambiguation(wikitext):
    return bool(re.search(r"\{\{disambig\}\}", wikitext, re.I))


def disambiguation_targets(wikitext):
    """The pages a disambiguation page lists as its namesakes: the first link of
    each ``{{disamb|y=1987|[[Name (G1)|Name]], the ...}}`` line. Its gallery and its
    "not to be confused with" list are not namesakes."""
    out = []
    for line in wikitext.splitlines():
        found = DISAMBIG_ITEM.match(line.strip())
        if found:
            page = normalize_title(found.group(1))
            if page not in out:
                out.append(page)
    return out


def matches(entry, fragment):
    """How a ``#fragment`` picks this entry: 'anchor', 'heading' or None."""
    want = norm(fragment)
    if any(norm(a) == want for a in entry["anchors"]):
        return "anchor"
    names = [entry["heading"], entry["subheading"]] + entry["heading_ids"]
    if want in (norm(n) for n in names):
        return "heading"
    return None


# --- one entry to fields ----------------------------------------------------

YEAR = re.compile(r"\b(?:19|20)\d\d\b")


def _name_part(header):
    """The first ``'''Name''' (details)`` of an item's text."""
    m = re.match(r"\s*(.*?'''.*?''')\s*(?:\((.*)\))?", header, re.S)
    return (m.group(1), m.group(2) or "") if m else (header, "")


def _names_and_detail(header):
    """(names, detail) of ``'''A''' (x) / '''B''' (y)``; detail is the first paren."""
    names, details = [], []
    for chunk in re.split(r"\s/\s(?='''| ?\[\[)", header):
        text, detail = _name_part(chunk)
        name = clean(text)
        if name:
            names.append(name)
        details.append(detail)
    return names, details


def year_and_class(detail):
    """(release year, class words) from ``Deluxe Class, [[2024]]``."""
    detail = re.sub(r"<s>.*?</s>", "", detail, flags=re.S)
    text = clean(detail)
    years = YEAR.findall(text)
    parts = [
        p.strip()
        for p in text.split(",")
        if p.strip() and not YEAR.search(p) and "?" not in p
    ]
    return (int(years[0]) if years else None), parts


def strip_faction_prefix(name, factions=DEFAULT_FACTIONS):
    """(name without a leading faction word, that faction or None).

    Only a known faction is removed: ``Autobot Blaster`` becomes ``Blaster``,
    ``Animated Universe Bumblebee`` is left alone.
    """
    for faction in sorted(factions, key=len, reverse=True):
        m = re.match(r"^%s\s+(.+)$" % re.escape(faction), name, re.I)
        if m:
            return m.group(1).strip(), faction
    return name, None


def faction_from_code(code):
    """A faction suggestion from a Bp- code, or None (unknown or two sides)."""
    if code is None:
        return None
    m = re.fullmatch(r"([a-z])\d+", code)
    return BP_FACTIONS.get(m.group(1)) if m else None


def bullet_class(template_wikitext):
    """The CSS class a ``Template:Bp-xx`` gives its item (its faction symbol)."""
    m = re.search(r'<li class="([^"]+)"', template_wikitext)
    return m.group(1) if m else None


def faction_from_class(css_class, factions=DEFAULT_FACTIONS):
    """Suggest a faction from a Bp- CSS class (``autobotg1`` is Autobot)."""
    if not css_class:
        return None
    for faction in sorted(factions, key=len, reverse=True):
        if css_class.lower().startswith(faction.lower()):
            return faction
    return None


FIELD_LABELS = {
    "accessories": ("accessories", "accessory"),
    "takara_id": ("takara id number", "takaratomy id number", "takara id"),
    "hasbro_id": ("hasbro id number", "hasbro id"),
}


def bullet_fields(bullets):
    out = {}
    for label, value in bullets:
        label = label.strip().rstrip(":").strip().lower()
        for field, names in FIELD_LABELS.items():
            if label in names and field not in out:
                items = split_top_level(clean(value))
                if field == "accessories":
                    out["accessories_list"] = items
                    out[field] = ", ".join(items)
                elif items:
                    out[field] = ", ".join(items)
    return out


SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[\"'])")
KEYWORD = re.compile(
    r"\b(re-?deco|re-?tool|re-?mold|re-?paint|re-?color|re-?issue|re-?release)"
    r"(?:ed|s)?\b",
    re.I,
)
OF_AFTER = r"^[\]\s\w/,'-]*?\b(?:of|from)\b"
TOOLING_OF = {
    "tool": "Retool",
    "mold": "Retool",
    "deco": "Redeco",
    "paint": "Redeco",
    "color": "Redeco",
    "issue": "Reissue",
    "release": "Reissue",
}
# A character page "Name (Continuity)" or a toys page; "Hasbro Pulse" is neither.
FIGURE_PAGE = re.compile(r"\([^()]+\)$|/(?:Generations[ _])?toys$", re.I)
PACK_CONTEXT = re.compile(r"\b(?:pack\w*|set|box|included|includes)\b", re.I)
PACK_WORDS = re.compile(
    r"\b(?:with|alongside|along with|accompanied by|packaged|packed|included)\b", re.I
)


def _sentences(paragraphs):
    for para in paragraphs:
        for s in SENTENCE.split(para):
            if s.strip():
                yield s.strip()


def _figure_links(sentence, here, after=0):
    return [
        link
        for link in links(sentence, here)
        if link["fragment"] and link["start"] >= after
    ]


def history(entry, here):
    """(tooling suggestion, ancestors) from a sentence like "a retool of X".

    The first sentence that says redeco, retool, reissue ... "of" or "from" a
    figure gives both: ``tooling`` is {values, evidence} and the ancestor is
    the first figure link after the "of". A sentence like "was also retooled
    into Y" (a descendant) has no "of" and is not used. Later sentences
    (often about a bundled minion's mold) are ignored. Both are suggestions.
    """
    for sentence in _sentences(entry["paragraphs"]):
        keywords = list(KEYWORD.finditer(sentence))
        for kw in keywords:
            m = re.search(OF_AFTER, sentence[kw.end() : kw.end() + 80])
            if not m:
                continue
            values = []
            for k in keywords:
                value = TOOLING_OF[re.sub(r"^re-?", "", k.group(1).lower())]
                if value not in values:
                    values.append(value)
            ancestors = []
            found = _figure_links(sentence, here, kw.end() + m.end())
            if found:
                ancestors.append(
                    {
                        "name": found[0]["text"],
                        "link": found[0]["url"],
                        "evidence": sentence,
                    }
                )
            return {"values": values, "evidence": sentence}, ancestors
    return None, []


def packed_with(entry, here, own_fragment_urls):
    """Figures named after "with", "alongside", ... in a sentence about a pack."""
    out = []
    for sentence in _sentences(entry["paragraphs"]):
        word = PACK_WORDS.search(sentence)
        if not word or not PACK_CONTEXT.search(sentence):
            continue
        for link in _figure_links(sentence, here, word.end()):
            if link["start"] - word.end() > 150 or not FIGURE_PAGE.search(link["page"]):
                continue
            if link["url"] in own_fragment_urls or link["url"] in [
                p["link"] for p in out
            ]:
                continue
            out.append(
                {"name": link["text"], "link": link["url"], "evidence": sentence}
            )
    return out


def figure_fields(entry, here, factions=DEFAULT_FACTIONS, own_urls=()):
    """The suggestions for one entry, each with where it came from."""
    names, details = _names_and_detail(entry["header"])
    year, classes = year_and_class(details[0] if details else "")
    if year is None:
        for d in details[1:]:
            year, _ = year_and_class(d)
            if year:
                break
    name, prefix = strip_faction_prefix(names[0] if names else "", factions)
    tooling, ancestors = history(entry, here)
    is_pack = any(re.search(r"pack|set\b", c, re.I) for c in classes) or bool(
        entry["components"]
    )
    faction = None
    if prefix:
        faction = {"value": prefix, "source": "name prefix"}
    elif faction_from_code(entry["code"]):
        faction = {
            "value": faction_from_code(entry["code"]),
            "source": "Bp-%s" % entry["code"],
        }
    fields = {
        "name": name,
        "names": [strip_faction_prefix(n, factions)[0] for n in names],
        "release_year": year,
        "classes": classes,
        "is_pack": is_pack,
        "faction": faction,
        "bp_code": entry["code"],
        "tooling": tooling,
        "ancestors": ancestors,
        "packed_with": packed_with(entry, here, own_urls),
        "components": [
            {"name": c["text"], "link": c["links"][0]["url"] if c["links"] else None}
            for c in entry["components"]
        ],
        "toyline": entry["heading"] or None,
        "anchors": entry["anchors"],
        "picture": picture(entry["picture"]),
        "accessories": "",
        "accessories_list": [],
    }
    fields.update(bullet_fields(entry["bullets"]))
    return fields


def picture(filename):
    if not filename:
        return None
    name = normalize_title(filename)
    return {
        "file": name,
        "page": WIKI + urllib.parse.quote("File:" + name, safe="()!,'_-.:"),
        "url": WIKI + "Special:FilePath/" + urllib.parse.quote(name, safe="()!,'_-."),
    }


def character(title):
    """The character a toys page belongs to."""
    name, qualifier = split_title(title)
    return {
        "name": name,
        "qualifier": qualifier,
        "page": character_page(title),
        "link": page_url(character_page(title)),
    }


# --- the lead sentence of a character page ----------------------------------

FAMILY_LINK = re.compile(r"\[\[([^\]|#]+?) continuity family(?:\|[^\]]*)?\]\]", re.I)
# "the [[Transformers: Shattered Glass (franchise)|Shattered Glass]] [[continuity family]]"
LABELLED_FAMILY = re.compile(
    r"\[\[[^\]|]+\|([^\]]+)\]\]\s*\[\[continuity family\]\]", re.I
)
PORTION = re.compile(
    r"\b(?:from|in) the (.+?) (?:portion|era|segment|section) of the\s*$", re.I
)


def _mask_links(text):
    """``text`` with each [[wikilink]] blanked out, same length: a "!" or "." in
    a link target (``Fight! Super Robot...``) is not the end of a sentence."""
    return re.sub(r"\[\[.*?\]\]", lambda m: "x" * len(m.group(0)), text)


def lead(wikitext, factions=DEFAULT_FACTIONS):
    """What a character page's first sentence says: ``Omega Prime is an
    [[Autobot]] [[combiner]] from the [[Robots in Disguise continuity family]]``.

    Only a sentence of the form "X is/are ... continuity family" counts, so a later
    paragraph that merely mentions a family is not mistaken for it. Returns
    {sentence, family, faction, portion} with the parts that were found, or None.
    These are suggestions.
    """
    wanted = {f.lower(): f for f in factions}
    for line in wikitext.splitlines()[:80]:
        matches = [
            (m.start(), m.end(), m.group(1).strip())
            for pattern in (FAMILY_LINK, LABELLED_FAMILY)
            for m in pattern.finditer(line)
        ]
        if not matches:
            continue
        first, last, family = min(matches)
        masked = _mask_links(line)
        begin = max([m.end() for m in SENTENCE.finditer(masked[:first])] or [0])
        start = line[begin:first]
        if not re.search(r"\b(?:is|are)\b", clean(start)):
            continue
        stop = SENTENCE.search(masked, last)
        found = {
            "sentence": clean(line[begin : stop.start() if stop else len(line)]),
            "family": family,
        }
        for link in LINK.finditer(start):
            if link.group(1).strip().lower() in wanted:
                found["faction"] = wanted[link.group(1).strip().lower()]
                break
        portion = PORTION.search(clean(start + "x")[:-1].rstrip() + " ")
        if portion:
            found["portion"] = portion.group(1).strip()
        return found
    return None
