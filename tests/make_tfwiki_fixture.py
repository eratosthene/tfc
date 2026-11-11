"""Writes tests/fixtures/tfwiki/*.json. The wikitext is SYNTHETIC: written by
hand in the MediaWiki action=parse response shape, not recorded from tfwiki.net
(its robots.txt disallows automated clients). Replace with recordings once the
site's owners allow it."""

import json
import os

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "tfwiki")
PRIME = """'''Optimus Prime''' leads the Autobots.

== Generation 1 ==
{{toyinfobox
| name = Optimus Prime
| year = 1984<ref>Catalog</ref>
| franchise = [[Generation 1]]
| faction = [[Autobot]]s
| tooling = Prime tooling
| accessories = [[Ion blaster|Blaster]]<br>Axe
| class = Leader
| hasbro id = 1234
| takara = C-001
| exclusive to = Toys R Us
}}
Text.

== Masterpiece ==
{{ToyInfobox
| name = MP Optimus Prime
| released = 2003 (Japan)
| line = Masterpiece
| faction = Autobot
}}

== Notes ==
No infobox here.
"""
BAD = """== Mystery ==
{{toyinfobox
| name = Mystery
| line = Nonexistent line
}}
"""


def resp(title, text):
    return json.dumps({"parse": {"title": title, "pageid": 1, "wikitext": {"*": text}}})


os.makedirs(HERE, exist_ok=True)
for name, (t, x) in {
    "Optimus_Prime_(G1)": ("Optimus Prime (G1)", PRIME),
    "Mystery": ("Mystery", BAD),
}.items():
    open(os.path.join(HERE, name + ".json"), "w").write(resp(t, x))
open(os.path.join(HERE, "missing.json"), "w").write(
    json.dumps(
        {
            "error": {
                "code": "missingtitle",
                "info": "The page you specified doesn't exist.",
            }
        }
    )
)
open(os.path.join(HERE, "robots_blocked.txt"), "w").write(
    "User-agent: *\nDisallow: /\n"
)
open(os.path.join(HERE, "robots_open.txt"), "w").write(
    "User-agent: *\nCrawl-delay: 1\nDisallow: /wiki/Special:\n"
)
