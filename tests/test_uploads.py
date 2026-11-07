import os

from app import app as flask_app


def _folder():
    return flask_app.config["UPLOAD_FOLDER"]


def test_uploaded_file_is_served(client):
    path = os.path.join(_folder(), "route_test.txt")
    with open(path, "wb") as f:
        f.write(b"hello")
    try:
        resp = client.get("/static/uploads/route_test.txt")
        assert resp.status_code == 200
        assert resp.data == b"hello"
    finally:
        os.remove(path)


def test_missing_upload_is_404(client):
    assert client.get("/static/uploads/nope.png").status_code == 404


def test_upload_path_traversal_is_refused(client, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    monkeypatch.setitem(flask_app.config, "UPLOAD_FOLDER", str(uploads) + os.sep)
    for url in (
        "/static/uploads/../secret.txt",
        "/static/uploads/%2e%2e/secret.txt",
        "/static/uploads/..%2fsecret.txt",
    ):
        resp = client.get(url)
        assert resp.status_code in (301, 308, 404), url
        assert b"secret" not in resp.data


def test_flask_appbuilder_static_assets_are_served(client):
    resp = client.get("/static/appbuilder/css/flags/flags16.css")
    assert resp.status_code == 200


def test_upload_route_without_a_folder_is_404(client, monkeypatch):
    monkeypatch.setitem(flask_app.config, "UPLOAD_FOLDER", None)
    assert client.get("/static/uploads/anything.png").status_code == 404
