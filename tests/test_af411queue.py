"""The ActionFigure411 queue, its confirm page and the bookmarklet."""

import pytest

from app import app as flask_app, db
from app.af411queue import BOOKMARKLET_JS, PAGE_SIZE, bookmarklet, slug_name
from app.models import Figure
from app.pricecheck import check_af411_figure_page

PAGE = "https://www.actionfigure411.com/transformers/anniversary/20th-anniversary-optimus-prime-1234.php"


def _more(seed, name, **kw):
    first = db.session.get(Figure, seed["figure"].id)
    fig = Figure(
        name=name,
        release_year=2004,
        character_new=first.character_new,
        faction=first.faction,
        **kw,
    )
    db.session.add(fig)
    db.session.commit()
    return fig.id


def test_the_queue_lists_figures_with_no_link_and_a_search_for_each(auth_client, seed):
    done = _more(seed, "Already Linked", af411_link=PAGE)
    html = auth_client.get("/af411-queue/").get_data(as_text=True)
    assert "Optimus Prime" in html and "Already Linked" not in html
    # The search opens in a new tab and names the figure for the bookmarklet.
    assert (
        "search-results.php?g=3&amp;term=Optimus+Prime#tfc=%d" % seed["figure"].id
        in html
    )
    assert "1 figure still to do" in html
    assert done


def test_the_queue_page_has_the_bookmarklet(auth_client, seed):
    html = auth_client.get("/af411-queue/").get_data(as_text=True)
    assert 'href="javascript:(function(){' in html
    assert "/af411-queue/confirm" in html


def test_an_empty_queue_says_so(auth_client, seed):
    fig = db.session.get(Figure, seed["figure"].id)
    fig.af411_link = PAGE
    db.session.commit()
    html = auth_client.get("/af411-queue/").get_data(as_text=True)
    assert "Every figure has a link, or was skipped." in html


def test_the_queue_is_paged(auth_client, seed):
    for n in range(PAGE_SIZE + 1):
        _more(seed, "Zed %02d" % n)
    first = auth_client.get("/af411-queue/").get_data(as_text=True)
    assert "Page 1 of 2" in first and "Next" in first and "Previous" not in first
    second = auth_client.get("/af411-queue/?page=2").get_data(as_text=True)
    assert "Page 2 of 2" in second and "Previous" in second and "Next" not in second
    # A page number that is not a number is the first page.
    assert "Page 1 of 2" in auth_client.get("/af411-queue/?page=x").get_data(
        as_text=True
    )


def test_saving_a_pasted_link(auth_client, seed):
    pk = seed["figure"].id
    resp = auth_client.post("/af411-queue/%d/save" % pk, data={"link": " %s " % PAGE})
    assert resp.status_code == 302
    db.session.expire_all()
    fig = db.session.get(Figure, pk)
    assert fig.af411_link == PAGE and fig.af411_skipped is False
    assert "Every figure has a link" in auth_client.get("/af411-queue/").get_data(
        as_text=True
    )


@pytest.mark.parametrize(
    "bad,message",
    [
        ("https://example.com/x-1.php", "must be a page on actionfigure411.com"),
        (
            "https://www.actionfigure411.com/transformers/studio-series-price-guide.php",
            "own ActionFigure411 page",
        ),
        ("", "ActionFigure411 address first"),
    ],
)
def test_a_bad_link_is_refused_and_nothing_is_saved(auth_client, seed, bad, message):
    pk = seed["figure"].id
    resp = auth_client.post(
        "/af411-queue/%d/save" % pk, data={"link": bad}, follow_redirects=True
    )
    assert message in resp.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Figure, pk).af411_link is None


def test_a_link_another_figure_has_is_saved_and_noted(auth_client, seed):
    _more(seed, "Other", af411_link=PAGE)
    resp = auth_client.post(
        "/af411-queue/%d/save" % seed["figure"].id,
        data={"link": PAGE},
        follow_redirects=True,
    )
    assert "1 other figure already has this link (normal for a set)" in resp.get_data(
        as_text=True
    )
    db.session.expire_all()
    assert db.session.get(Figure, seed["figure"].id).af411_link == PAGE


def test_skip_and_bring_back(auth_client, seed):
    pk = seed["figure"].id
    auth_client.post("/af411-queue/%d/skip" % pk)
    db.session.expire_all()
    assert db.session.get(Figure, pk).af411_skipped is True
    queue = auth_client.get("/af411-queue/").get_data(as_text=True)
    assert "Every figure has a link, or was skipped." in queue
    skipped = auth_client.get("/af411-queue/?show=skipped").get_data(as_text=True)
    assert "Optimus Prime" in skipped and "1 figure skipped" in skipped
    auth_client.post("/af411-queue/%d/unskip" % pk)
    db.session.expire_all()
    assert db.session.get(Figure, pk).af411_skipped is False
    assert "Nothing is skipped." in auth_client.get(
        "/af411-queue/?show=skipped"
    ).get_data(as_text=True)


def test_skipped_pages_link_back(auth_client, seed):
    for n in range(PAGE_SIZE + 1):
        _more(seed, "Zed %02d" % n, af411_skipped=True)
    html = auth_client.get("/af411-queue/?show=skipped&page=2").get_data(as_text=True)
    assert "show=skipped" in html and "Previous" in html


def test_the_confirm_page_shows_the_figure_and_the_link(auth_client, seed):
    pk = seed["figure"].id
    html = auth_client.get(
        "/af411-queue/confirm", query_string={"figure": pk, "link": PAGE}
    ).get_data(as_text=True)
    assert "Use this ActionFigure411 page?" in html
    assert PAGE in html and "20th anniversary optimus prime" in html
    assert "Save this link" in html and "Replaces" not in html


def test_the_confirm_page_says_what_it_would_replace(auth_client, seed):
    fig = db.session.get(Figure, seed["figure"].id)
    fig.af411_link = "https://www.actionfigure411.com/transformers/old-1.php"
    db.session.commit()
    html = auth_client.get(
        "/af411-queue/confirm", query_string={"figure": fig.id, "link": PAGE}
    ).get_data(as_text=True)
    assert "Replaces" in html and "old-1.php" in html


@pytest.mark.parametrize(
    "link,message",
    [
        ("https://evil.example/x-1.php", "must be a page on actionfigure411.com"),
        ("javascript:alert(1)", "must be a page on actionfigure411.com"),
        (None, "No address was sent."),
    ],
)
def test_the_confirm_page_refuses_a_link_that_is_not_theirs(
    auth_client, seed, link, message
):
    params = {"figure": seed["figure"].id}
    if link:
        params["link"] = link
    html = auth_client.get("/af411-queue/confirm", query_string=params).get_data(
        as_text=True
    )
    assert message in html and "Save this link" not in html


def test_the_confirm_page_for_a_missing_figure_is_404(auth_client, seed):
    assert (
        auth_client.get(
            "/af411-queue/confirm", query_string={"figure": 99999, "link": PAGE}
        ).status_code
        == 404
    )


def test_saving_or_skipping_a_missing_figure_is_404(auth_client, seed):
    assert (
        auth_client.post("/af411-queue/99999/save", data={"link": PAGE}).status_code
        == 404
    )
    assert auth_client.post("/af411-queue/99999/skip").status_code == 404


def test_the_forms_need_the_csrf_token(auth_client, seed, csrf_on):
    pk = seed["figure"].id
    for path, data in (
        ("save", {"link": PAGE}),
        ("skip", {}),
    ):
        resp = auth_client.post("/af411-queue/%d/%s" % (pk, path), data=data)
        assert resp.status_code == 302
    db.session.expire_all()
    fig = db.session.get(Figure, pk)
    assert fig.af411_link is None and fig.af411_skipped is False
    page = auth_client.get("/af411-queue/", follow_redirects=True).get_data(
        as_text=True
    )
    assert "had expired" in page


def test_someone_who_cannot_edit_figures_cannot_change_the_queue(
    auth_client, seed, monkeypatch
):
    sm = flask_app.appbuilder.sm
    real = sm.has_access

    def deny_edit(permission, view, *args, **kwargs):
        if (permission, view) == ("can_edit", "FigureModelView"):
            return False
        return real(permission, view, *args, **kwargs)

    monkeypatch.setattr(sm, "has_access", deny_edit)
    pk = seed["figure"].id
    assert (
        auth_client.post("/af411-queue/%d/save" % pk, data={"link": PAGE}).status_code
        == 403
    )
    assert auth_client.post("/af411-queue/%d/skip" % pk).status_code == 403
    db.session.expire_all()
    fig = db.session.get(Figure, pk)
    assert fig.af411_link is None and fig.af411_skipped is False


def test_the_queue_needs_a_login(client, seed):
    assert client.get("/af411-queue/").status_code == 302
    assert client.post("/af411-queue/1/save", data={"link": PAGE}).status_code == 302


def test_figure_page_check():
    assert check_af411_figure_page(PAGE) == PAGE
    assert check_af411_figure_page("  ") is None


def test_slug_name():
    assert slug_name(PAGE) == "20th anniversary optimus prime"


def test_the_bookmarklet_is_one_line_with_the_confirm_address_in_it():
    code = bookmarklet("http://tfc.local:9999/af411-queue/confirm")
    assert code.startswith("javascript:(function(){")
    assert '"http://tfc.local:9999/af411-queue/confirm"' in code
    assert "__CONFIRM__" not in code
    assert "\n" not in code and "%" not in code  # a % would be read as an escape
    assert "__CONFIRM__" in BOOKMARKLET_JS
