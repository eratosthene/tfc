"""The ancestors and pack-mates of a figure, as the text the Figure form uses.

One reference per line, ``Name | https://tfwiki.net/wiki/...``. Order is kept.
"""

NAME_LENGTH = 255
LINK_LENGTH = 500


def parse_references(text):
    """[(name, link)] from the lines of ``text``. Blank lines are skipped.

    Raises ValueError, naming the line, for anything the table cannot hold.
    """
    found = []
    for number, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        name, bar, link = line.rpartition("|")
        name, link = name.strip(), link.strip()
        if not bar or not name or not link:
            raise ValueError("Line %d: write it as  Name | link" % number)
        if not link.startswith(("http://", "https://")):
            raise ValueError(
                "Line %d: the link must start with http:// or https://" % number
            )
        if len(name) > NAME_LENGTH or len(link) > LINK_LENGTH:
            raise ValueError("Line %d is too long." % number)
        found.append((name, link))
    return found


def format_references(references):
    return "\n".join("%s | %s" % (r.name, r.link) for r in references)
