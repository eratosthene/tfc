import pytest

VIEWS = [
    ("figuremodelview", "figure"),
    ("franchisemodelview", "franchise"),
    ("factionmodelview", "faction"),
    ("toolingmodelview", "tooling"),
    ("accessorymodelview", "accessory"),
    ("categorymodelview", "category"),
    ("tfwikilinkmodelview", "character"),
]


def test_index_counts(auth_client, seed):
    resp = auth_client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Autobot" in html
    assert "Generation 1" in html


@pytest.mark.parametrize("view,key", VIEWS)
def test_list_and_show_logged_in(auth_client, seed, view, key):
    assert auth_client.get("/%s/list/" % view).status_code == 200
    pk = seed[key].id
    assert auth_client.get("/%s/show/%s" % (view, pk)).status_code == 200


@pytest.mark.parametrize("view,key", VIEWS)
def test_anonymous_redirected_to_login(client, seed, view, key):
    for path in ("/%s/list/" % view, "/%s/show/%s" % (view, seed[key].id)):
        resp = client.get(path)
        assert resp.status_code == 302
        assert "/login/" in resp.headers["Location"]


def test_404_template(auth_client):
    resp = auth_client.get("/no/such/page")
    assert resp.status_code == 404
    assert "<html" in resp.get_data(as_text=True).lower()


def test_404_handler_is_registered_on_the_flask_app(auth_client):
    # Registered on the Flask app itself, not through the deprecated
    # appbuilder.app (which logs a warning at import time).
    from app import app as flask_app
    from app.views import page_not_found

    assert page_not_found in flask_app.error_handler_spec[None][404].values()
    resp = auth_client.get("/no/such/page")
    assert resp.status_code == 404
    assert "Page not found" in resp.get_data(as_text=True)
