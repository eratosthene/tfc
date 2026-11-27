"""The ActionFigure411 queue: the figures that have no ActionFigure411 page saved.

Nothing here contacts ActionFigure411 (its bot protection turns the app away).
Each row opens the site's search in the user's own browser; the page is then
either pasted in, or picked by the bookmarklet below, which runs in the user's
browser on the results page and sends the chosen address back to the confirm
page. A saved page is what the figure's price-check links use, and a figure with
no page there can be skipped.
"""

import json
from urllib.parse import urlparse

from flask import abort, flash, redirect, request, url_for
from flask_appbuilder import BaseView, expose, has_access
from sqlalchemy import select

from app import appbuilder, db
from app.addfigure import CsrfOnly
from app.models import Figure
from app.pricecheck import af411_search_url, check_af411_figure_page

PAGE_SIZE = 25

# Run on an ActionFigure411 search results page opened from a queue row (the row
# adds #tfc=<figure id> to the address). It lists the figure pages it finds on
# the page; the one picked opens the confirm page, with nothing saved yet.
BOOKMARKLET_JS = """
(function(){
var C=__CONFIRM__;
var m=/tfc=(\\d+)/.exec(location.hash);
if(!m){alert("Open this page with a Search button on the tfc queue.");return}
var by={};
document.querySelectorAll("a[href]").forEach(function(a){
var u;try{u=new URL(a.href)}catch(e){return}
if(!/(^|\\.)actionfigure411\\.com$/.test(u.hostname)||!/-\\d+\\.php$/.test(u.pathname))return;
var k=u.origin+u.pathname;
var i=a.querySelector("img");
var t=(a.textContent||"").trim()||(i&&i.alt)||"";
if(!by[k])by[k]={link:k,name:t};else if(t.length>by[k].name.length)by[k].name=t});
var f=Object.keys(by).map(function(k){return by[k]});
function go(l){window.open(C+"?figure="+m[1]+"&link="+encodeURIComponent(l),"_blank")}
if(!f.length){alert("No figure pages found on this page.");return}
if(f.length==1){go(f[0].link);return}
var d=document.createElement("div");
d.style.cssText="position:fixed;top:10px;right:10px;z-index:99999;background:#fff;color:#000;border:2px solid #333;padding:10px;max-width:420px;max-height:90vh;overflow:auto;font:14px sans-serif";
var h=document.createElement("div");
h.textContent="Which one is it? (tfc)";
h.style.fontWeight="bold";
d.appendChild(h);
f.forEach(function(x){
var b=document.createElement("button");
b.textContent=x.name||x.link;
b.style.cssText="display:block;min-width:320px;margin:6px 0;padding:6px;text-align:left;cursor:pointer";
b.onclick=function(){go(x.link);d.remove()};
d.appendChild(b)});
var c=document.createElement("button");
c.textContent="Cancel";
c.onclick=function(){d.remove()};
d.appendChild(c);
document.body.appendChild(d)})();
"""


def one_line(js):
    """A script as one line, for a bookmark's address. Every line of it must end
    where a statement can, and it must hold no %, which a browser would read as
    the start of an escape."""
    return "".join(line.strip() for line in js.strip().splitlines())


def bookmarklet(confirm_url):
    """The bookmark's address: the script on one line, with the confirm page's
    address filled in."""
    code = one_line(BOOKMARKLET_JS)
    return "javascript:" + code.replace("__CONFIRM__", json.dumps(confirm_url))


def slug_name(link):
    """A readable name from a page address, for the confirm page to show."""
    slug = urlparse(link).path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return slug.rsplit("-", 1)[0].replace("-", " ")


class Af411QueueView(BaseView):
    route_base = "/af411-queue"
    default_view = "queue"

    def _render(self, step, **kwargs):
        return self.render_template(
            "af411queue.html", step=step, csrf_form=CsrfOnly(), **kwargs
        )

    def _figure(self, pk):
        figure = db.session.get(Figure, pk)
        if figure is None:
            abort(404)
        return figure

    def _can_edit(self):
        if not appbuilder.sm.has_access("can_edit", "FigureModelView"):
            abort(403)

    def _expired(self):
        flash(
            "That page had expired, so nothing was done. Please try again.", "warning"
        )
        return redirect(url_for("Af411QueueView.queue"))

    @expose("/")
    @has_access
    def queue(self):
        skipped = request.args.get("show") == "skipped"
        page = request.args.get("page", "")
        page = int(page) if page.isdigit() and int(page) > 0 else 1
        where = (Figure.af411_link.is_(None), Figure.af411_skipped.is_(skipped))
        total = db.session.scalar(select(db.func.count(Figure.id)).where(*where))
        figures = db.session.scalars(
            select(Figure)
            .where(*where)
            .order_by(Figure.name, Figure.id)
            .limit(PAGE_SIZE)
            .offset((page - 1) * PAGE_SIZE)
        ).all()
        return self._render(
            "queue",
            figures=figures,
            skipped=skipped,
            page=page,
            pages=max(1, -(-total // PAGE_SIZE)),
            total=total,
            search_url=lambda f: af411_search_url(f) + "#tfc=%d" % f.id,
            bookmarklet=bookmarklet(url_for("Af411QueueView.confirm", _external=True)),
        )

    @expose("/confirm")
    @has_access
    def confirm(self):
        figure = db.session.get(Figure, request.args.get("figure", "0"))
        if figure is None:
            abort(404)
        link, problem = None, None
        try:
            link = check_af411_figure_page(request.args.get("link"))
            problem = None if link else "No address was sent."
        except ValueError as error:
            problem = str(error)
        return self._render(
            "confirm",
            figure=figure,
            link=link,
            problem=problem,
            slug=slug_name(link) if link else "",
        )

    @expose("/<int:pk>/save", methods=["POST"])
    @has_access
    def save(self, pk):
        if not CsrfOnly().validate_on_submit():
            return self._expired()
        self._can_edit()
        figure = self._figure(pk)
        try:
            link = check_af411_figure_page(request.form.get("link"))
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("Af411QueueView.queue"))
        if not link:
            flash("Paste the figure's ActionFigure411 address first.", "warning")
            return redirect(url_for("Af411QueueView.queue"))
        others = db.session.scalar(
            select(db.func.count(Figure.id)).where(
                Figure.af411_link == link, Figure.id != pk
            )
        )
        if others:
            flash(
                "%s already %s this link (normal for a set)."
                % (
                    "1 other figure" if others == 1 else "%d other figures" % others,
                    "has" if others == 1 else "have",
                ),
                "info",
            )
        figure.af411_link = link
        figure.af411_skipped = False
        db.session.commit()
        flash("Saved the ActionFigure411 link for %s." % figure.name, "success")
        return redirect(url_for("Af411QueueView.queue"))

    def _set_skipped(self, pk, value):
        if not CsrfOnly().validate_on_submit():
            return self._expired()
        self._can_edit()
        figure = self._figure(pk)
        figure.af411_skipped = value
        db.session.commit()
        flash(
            "%s %s the queue." % (figure.name, "left" if value else "is back in"),
            "info",
        )
        return redirect(url_for("Af411QueueView.queue"))

    @expose("/<int:pk>/skip", methods=["POST"])
    @has_access
    def skip(self, pk):
        return self._set_skipped(pk, True)

    @expose("/<int:pk>/unskip", methods=["POST"])
    @has_access
    def unskip(self, pk):
        return self._set_skipped(pk, False)
