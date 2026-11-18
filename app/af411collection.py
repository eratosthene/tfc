"""Copy links and averages from ActionFigure411's My Collection page.

Nothing here contacts ActionFigure411. A bookmarklet, run in the user's own
browser on their My Collection page, reads the rows already on the page (each
has the figure's page address, its recent sold average and the user's Note, where
the user put the tfc figure's id) and shows them as text to copy. The text is
pasted into this view, which matches each row to a figure, shows what it would
change, and saves only what is ticked.
"""

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, request, url_for
from flask_appbuilder import BaseView, expose, has_access
from sqlalchemy import select

from app import appbuilder, db
from app.addfigure import CsrfOnly
from app.af411queue import one_line
from app.models import Figure
from app.pricecheck import check_af411_figure_page

MAX_ROWS = 5000
# A Note that is just figure ids, with or without "tfc" in front: ActionFigure411
# lists a retail box (a 3-pack is one entry), while tfc has each figure in it, so a
# box's Note may hold several ids ("199, 200, 201").
NOTE_IDS = re.compile(r"^(?:tfc\s*#?\s*)?\d+(?:\s*[,;/+&\s]\s*\d+)*$", re.IGNORECASE)

# Run on the My Collection page: reads every figure row and shows the result in a
# box, already selected, and copies it too when the browser allows. Nothing is
# sent anywhere.
COLLECT_JS = """
(function(){
var g="",out=[];
document.querySelectorAll("tr").forEach(function(r){
var h=r.querySelector("td[colspan]");
if(h&&!r.classList.contains("figureRow")){g=h.textContent.replace(/\\s*\\(\\d+\\/\\d+\\)\\s*$/,"").trim();return}
if(!r.classList.contains("figureRow"))return;
var a=r.querySelector("a[href$='.php']");
var e=r.querySelector("[user_figure_id]");
var t=r.querySelector("[note_in]");
var td=r.querySelectorAll("td");
var q=r.querySelector(".quantity"),c=r.querySelector(".condition"),m=r.querySelector(".amount");
if(!a)return;
out.push({af:r.getAttribute("data-figure-id"),l:a.href,n:a.textContent.trim(),g:g,q:q?q.textContent.trim():"",c:c?c.textContent.trim():"",p:e?e.getAttribute("price_in"):"",v:e?e.getAttribute("variation_in"):"",t:t?t.getAttribute("note_in"):"",r:td[7]?td[7].textContent.trim():"",a:m?m.textContent.trim():""})});
var s=JSON.stringify({v:1,rows:out});
if(!out.length){alert("No figures found on this page. Open My Collection first.");return}
var d=document.createElement("div");
d.style.cssText="position:fixed;top:10px;right:10px;z-index:99999;background:#fff;color:#000;border:2px solid #333;padding:10px;width:360px;font:14px sans-serif";
var p=document.createElement("div");
p.textContent="tfc: "+out.length+" figures read. Copy them, then paste them into tfc.";
d.appendChild(p);
var ta=document.createElement("textarea");
ta.value=s;ta.readOnly=true;ta.style.cssText="width:340px;height:80px;margin:6px 0";
d.appendChild(ta);
var b=document.createElement("button");
b.textContent="Close";
b.onclick=function(){d.remove()};
d.appendChild(b);
document.body.appendChild(d);
ta.focus();ta.select();
try{navigator.clipboard.writeText(s).then(function(){p.textContent="tfc: "+out.length+" figures copied. Paste them into tfc."},function(){})}catch(e){}
})();
"""


def collect_bookmarklet():
    return "javascript:" + one_line(COLLECT_JS)


def money(text):
    """A Decimal from "$1,234.56" (or 12.5), or None if there is no amount."""
    cleaned = re.sub(r"[\s$,]", "", str(text or ""))
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value >= Decimal("100000000"):
        return None
    return value.quantize(Decimal("0.01"))


def norm(name):
    return " ".join((name or "").casefold().split())


def _clean_row(raw, number, problems):
    if not isinstance(raw, dict):
        problems.append("Row %d is not a figure." % number)
        return None
    text = {k: str(raw.get(k) or "").strip()[:500] for k in "lngqcptrav"}
    try:
        link = check_af411_figure_page(text["l"])
    except ValueError as error:
        problems.append("Row %d (%s): %s" % (number, text["n"] or "?", error))
        return None
    if not link or not text["n"]:
        problems.append("Row %d has no address or name." % number)
        return None
    note_ids = []
    if NOTE_IDS.match(text["t"]):
        for found in re.findall(r"\d+", text["t"]):
            if int(found) not in note_ids:
                note_ids.append(int(found))
    return {
        "link": link,
        "name": text["n"],
        "group": text["g"],
        "quantity": text["q"],
        "condition": text["c"],
        "note": text["t"],
        "note_ids": note_ids,
        "retail": money(text["r"]),
        "average": money(text["a"]),
    }


def parse_paste(text):
    """([rows], [problems]) from what the bookmarklet copied."""
    try:
        data = json.loads(text or "")
    except ValueError:
        return [], [
            "That is not what the bookmarklet copies. Run it again and paste all of it."
        ]
    rows = data.get("rows") if isinstance(data, dict) and data.get("v") == 1 else None
    if not isinstance(rows, list) or not rows:
        return [], ["No figures were found in that text."]
    if len(rows) > MAX_ROWS:
        return [], ["That is more than %d figures." % MAX_ROWS]
    problems = []
    cleaned = [_clean_row(raw, n, problems) for n, raw in enumerate(rows, 1)]
    return [r for r in cleaned if r], problems


def match_rows(rows):
    """Each row with the figures it belongs to, how that was found, the other
    figures it could be, and anything the user should look at.

    The Note holding figure ids is trusted first (several for a box that holds
    several figures); otherwise the name has to match exactly one figure.
    """
    figures = {
        fid: (name, link)
        for fid, name, link in db.session.execute(
            select(Figure.id, Figure.name, Figure.af411_link)
        )
    }
    by_name = {}
    for fid, (name, _link) in figures.items():
        by_name.setdefault(norm(name), []).append(fid)
    results = []
    for row in rows:
        entry = {
            "row": row,
            "figure_ids": [],
            "basis": "",
            "candidates": [],
            "warnings": [],
            "notes": [],
        }
        known = [i for i in row["note_ids"] if i in figures]
        if known:
            entry["figure_ids"], entry["basis"] = known, "Note"
            gone = [i for i in row["note_ids"] if i not in figures]
            if gone:
                entry["warnings"].append(
                    "No figure has the id %s." % ", ".join(map(str, gone))
                )
        else:
            if row["note"]:
                entry["warnings"].append(
                    "The Note %r is not a figure's id here." % row["note"]
                )
            found = by_name.get(norm(row["name"]), [])
            if len(found) == 1:
                entry["figure_ids"], entry["basis"] = found, "name"
            else:
                entry["candidates"] = found
        results.append(entry)
    links = {}
    for entry in results:
        for fid in entry["figure_ids"]:
            links.setdefault(fid, set()).add(entry["row"]["link"])
    for entry in results:
        row, ids = entry["row"], entry["figure_ids"]
        entry["figure_names"] = [(i, figures[i][0]) for i in ids]
        if len(ids) == 1 and norm(figures[ids[0]][0]) != norm(row["name"]):
            entry["warnings"].append(
                "The figure here is called %r." % figures[ids[0]][0]
            )
        for fid in ids:
            if len(links[fid]) > 1:
                entry["warnings"].append(
                    "More than one ActionFigure411 page points at figure %d." % fid
                )
            current = figures[fid][1]
            if current and current != row["link"]:
                entry["warnings"].append(
                    "Figure %d already has a different link, which this would replace."
                    % fid
                )
        if len(ids) > 1:
            entry["notes"].append(
                "%d figures share this box. The average is for the whole box and "
                "is saved on each, so a total must count a box once." % len(ids)
            )
        entry["candidate_names"] = [(c, figures[c][0]) for c in entry["candidates"]]
        average, retail = row["average"], row["retail"]
        if average is not None and retail:
            if average == retail:
                entry["notes"].append(
                    "The average is the retail price (probably no recent sales)."
                )
            elif average >= retail * 3 or average * 3 <= retail:
                entry["notes"].append("The average is far from the retail price.")
        entry["checked"] = bool(ids) and not entry["warnings"]
    used = {i for e in results for i in e["figure_ids"]}
    missing = [
        (fid, name)
        for fid, (name, _link) in sorted(
            figures.items(), key=lambda i: i[1][0].casefold()
        )
        if fid not in used
    ]
    return results, missing


def apply_form(form):
    """Save the ticked rows of the preview. Returns (figures changed, problems).

    The id box of a row may hold several ids; each figure gets the row's link and
    average.
    """
    count = form.get("count", "")
    count = int(count) if count.isdigit() and int(count) <= MAX_ROWS else 0
    changed, problems, seen = 0, [], {}
    for i in range(count):
        if not form.get("use%d" % i):
            continue
        name = form.get("name%d" % i, "?")
        ids = [int(n) for n in re.findall(r"\d+", form.get("figure%d" % i, ""))]
        figures = [db.session.get(Figure, n) for n in dict.fromkeys(ids)]
        if not figures or None in figures:
            problems.append(
                "%s: no figure has the id %r." % (name, form.get("figure%d" % i, ""))
            )
            continue
        try:
            link = check_af411_figure_page(form.get("link%d" % i))
        except ValueError as error:
            problems.append("%s: %s" % (name, error))
            continue
        if link is None:
            problems.append("%s: no address." % name)
            continue
        clash = [f for f in figures if seen.get(f.id, link) != link]
        if clash:
            problems.append(
                "%s: another row already set a different link on %s."
                % (name, clash[0].name)
            )
            continue
        average = money(form.get("average%d" % i))
        for figure in figures:
            seen[figure.id] = link
            figure.af411_link, figure.af411_skipped = link, False
            if average is not None:
                figure.af411_average, figure.af411_average_on = average, date.today()
            changed += 1
    db.session.commit()
    return changed, problems


class Af411ImportView(BaseView):
    route_base = "/af411-import"
    default_view = "start"

    def _render(self, step, **kwargs):
        return self.render_template(
            "af411import.html",
            step=step,
            csrf_form=CsrfOnly(),
            bookmarklet=collect_bookmarklet(),
            **kwargs,
        )

    @expose("/")
    @has_access
    def start(self):
        return self._render("paste", problems=[], text="")

    @expose("/preview", methods=["POST"])
    @has_access
    def preview(self):
        if not CsrfOnly().validate_on_submit():
            flash(
                "That page had expired, so nothing was done. Please try again.",
                "warning",
            )
            return redirect(url_for("Af411ImportView.start"))
        text = request.form.get("data", "")
        rows, problems = parse_paste(text)
        if not rows:
            return self._render("paste", problems=problems, text=text)
        entries, missing = match_rows(rows)
        return self._render(
            "preview", problems=problems, entries=entries, missing=missing
        )

    @expose("/apply", methods=["POST"])
    @has_access
    def apply(self):
        if not CsrfOnly().validate_on_submit():
            flash(
                "That page had expired, so nothing was done. Please try again.",
                "warning",
            )
            return redirect(url_for("Af411ImportView.start"))
        if not appbuilder.sm.has_access("can_edit", "FigureModelView"):
            abort(403)
        changed, problems = apply_form(request.form)
        for problem in problems:
            flash(problem, "danger")
        if changed:
            flash(
                "Saved the ActionFigure411 link and average on %d figures." % changed,
                "success",
            )
        elif not problems:
            flash("Nothing was ticked, so nothing was saved.", "info")
        return redirect(url_for("Af411QueueView.queue"))
