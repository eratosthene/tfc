"""Safety guard: the test suite must only ever talk to mongomock."""


def _hosts(settings):
    settings = settings or {}
    host = settings.get("host") or settings.get("HOST") or ""
    return [host] if isinstance(host, str) else list(host)


def assert_mongomock(settings):
    hosts = _hosts(settings)
    if not hosts or not all(str(h).startswith("mongomock://") for h in hosts):
        raise RuntimeError(
            "Refusing to run tests: MONGODB_SETTINGS host %r is not mongomock://"
            % (hosts,)
        )
