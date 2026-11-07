"""Safety guard: the test suite must only ever talk to a throwaway database.

The tests empty every table, so the connection string has to be SQLite or a
database whose name ends in ``_test``. Anything else is refused.
"""

from sqlalchemy.engine import make_url


def assert_test_database(uri):
    try:
        url = make_url(uri)
    except Exception:
        raise RuntimeError("Refusing to run tests: cannot parse the database URI")
    if url.get_backend_name() == "sqlite":
        return
    if not (url.database or "").endswith("_test"):
        raise RuntimeError(
            "Refusing to run tests: database %r is not SQLite and its name does "
            "not end in _test" % (url.database,)
        )
