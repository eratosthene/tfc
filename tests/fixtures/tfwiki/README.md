# Recorded tfwiki.net pages

Raw `action=parse` API responses (MediaWiki 1.19), recorded on 11 November 2026
with `app.tfwiki.fetcher.Fetcher` (2 s apart, honest User-Agent, one request per
page; the folder is the fetcher's own cache, so the tests read these exactly as
the app would). Content is from TFWiki.net, licensed CC BY-SA 3.0.

| File (cache name) | Page | Used for |
|---|---|---|
| `page-Alpha_Trion_toys-*` | `Alpha Trion/toys` | the issue's first example (`#Legacy`, a 2-pack, retool, packed with) |
| `page-Alpha_Trion_(G1)-*` | `Alpha Trion` (redirect from `Alpha_Trion_(G1)`) | the moved link: `{{main|Alpha Trion/toys}}` |
| `page-Bumblebee_(Animated)_toys-*` | `Bumblebee (Animated)/toys` | a continuity name kept in the figure name |
| `page-Blackarachnia_(BW)_toys-*` | `Blackarachnia (BW)` (redirect from `/toys`) | toys on the character page; two figures under one heading |
| `page-Blaster_(FOC)-*` | `Blaster (FOC)` | the old list layout; faction prefix "Autobot Blaster" |
| `page-Boater-*` | `Boater` | a page with no `(X)` suffix |
| `page-Bruticus_(G1)-*` | `Bruticus (G1)` | a combiner with five components |
| `page-Omega_Prime-*` | `Omega Prime` | an escaped anchor (`.282001.29`) and alternate names |
| `page-Optimus_Prime_(G1)_Generations_toys-*` | `Optimus Prime (G1)/Generations toys` | the `Generations_toys` suffix, anchors, `Bp-multi` |
| `page-The_Fallen_toys-*` | `The Fallen/toys` | a figure whose name differs from the page; an unknown `Bp-pr12` side |
| `page-Template_Bp-a1-*`, `page-Template_Bp-pr12-*` | `Template:Bp-a1`, `Template:Bp-pr12` | the faction symbol is a CSS class (`autobotg1`, `megatronusbp`) |

To record another page, with `TFWIKI_ENABLED` on:
`Fetcher("tests/fixtures/tfwiki", enabled=True).page("Title")`.
