"""Fetch page wikitext from tfwiki.net, politely.

tfwiki.net's robots.txt disallows automated clients, so nothing here runs
unless ``TFWIKI_ENABLED`` is set: an explicit opt-in, never a quiet bypass.
When it is set the rules are:

* one request at a time and at least ``MIN_DELAY`` seconds between requests,
  across every gunicorn worker (a lock file and a timestamp in the cache folder);
* a 429 or 503 stops all fetching for ``HALT_SECONDS``, with no retry;
* every response is cached on disk by page title and never fetched again unless
  ``refresh`` is asked for. Cached pages are readable even when fetching is off;
* an honest ``User-Agent`` naming this project.
"""

import fcntl
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

SITE = "https://tfwiki.net"
API = SITE + "/mediawiki/api.php"
USER_AGENT = (
    "tfc-importer/1.0 (+https://github.com/eratosthene/tfc; personal collection app)"
)
MIN_DELAY = 2.0
HALT_SECONDS = 3600


class FetchError(Exception):
    pass


class Disabled(FetchError):
    """The page is not cached and fetching from tfwiki.net is not enabled."""


class RateLimited(FetchError):
    """The site answered 429 or 503: stop, do not retry."""


class PageNotFound(FetchError):
    pass


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 503):
            raise RateLimited(f"{url}: HTTP {exc.code}; stopping") from exc
        raise FetchError(f"Could not fetch {url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"Could not fetch {url}: {exc}") from exc


def normalize_title(title):
    """A page title as MediaWiki spells it in a URL: underscores, no padding."""
    return re.sub(r"[\s_]+", "_", title.strip())


def cache_name(title):
    title = normalize_title(title)
    safe = re.sub(r"[^A-Za-z0-9_()-]", "_", title)[:80]
    return "page-%s-%s.json" % (safe, hashlib.sha256(title.encode()).hexdigest()[:8])


def parse_response(raw, title):
    """(canonical title, wikitext) from a MediaWiki ``action=parse`` response."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise FetchError(f"{title}: the response was not JSON") from exc
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        if err.get("code") == "missingtitle":
            raise PageNotFound(f"{title}: no such page")
        raise FetchError(f"{title}: {err.get('info', 'MediaWiki error')}")
    try:
        parsed = data["parse"]
        return parsed["title"], parsed["wikitext"]["*"]
    except (KeyError, TypeError) as exc:
        raise FetchError(f"{title}: unexpected response shape") from exc


class Throttle:
    """The shared politeness rules, kept in files so workers obey them together."""

    def __init__(self, folder, delay, halt_seconds, sleep, wall):
        self.folder = folder
        self.delay = delay
        self.halt_seconds = halt_seconds
        self._sleep = sleep
        self._wall = wall

    def _path(self, name):
        return os.path.join(self.folder, name)

    def _read(self, name):
        try:
            with open(self._path(name), encoding="utf-8") as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            return None

    def _write(self, name, value):
        with open(self._path(name), "w", encoding="utf-8") as f:
            f.write(repr(value))

    @contextmanager
    def slot(self):
        """Hold the one request slot: wait out the gap, then run the request.

        A RateLimited raised inside starts the halt. The time of the request is
        recorded however it ended.
        """
        os.makedirs(self.folder, exist_ok=True)
        with open(self._path("throttle.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            halted = self._read("halted-at")
            if halted is not None and self._wall() - halted < self.halt_seconds:
                raise RateLimited("tfwiki.net rate limited us earlier; not retrying")
            last = self._read("last-request")
            if last is not None:
                wait = self.delay - (self._wall() - last)
                if wait > 0:
                    self._sleep(wait)
            try:
                yield
            except RateLimited:
                self._write("halted-at", self._wall())
                raise
            finally:
                self._write("last-request", self._wall())


class Fetcher:
    """Wikitext by page title, from the cache, else (if enabled) the network.

    ``get``, ``sleep`` and ``wall`` can be replaced so tests make no network
    calls and do not wait.
    """

    def __init__(
        self,
        cache_dir,
        enabled=False,
        delay=MIN_DELAY,
        halt_seconds=HALT_SECONDS,
        get=http_get,
        sleep=time.sleep,
        wall=time.time,
    ):
        self.cache_dir = cache_dir
        self.enabled = enabled
        self._get = get
        self._throttle = Throttle(
            cache_dir, max(float(delay), MIN_DELAY), halt_seconds, sleep, wall
        )

    def cached(self, title):
        return os.path.exists(os.path.join(self.cache_dir, cache_name(title)))

    def page(self, title, refresh=False):
        """(canonical title, wikitext). Redirects are followed by the API."""
        path = os.path.join(self.cache_dir, cache_name(title))
        if not refresh and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return parse_response(f.read(), title)
        if not self.enabled:
            raise Disabled(
                f"{title} is not cached and fetching from tfwiki.net is off "
                "(set TFWIKI_ENABLED)"
            )
        url = (
            API
            + "?"
            + urllib.parse.urlencode(
                {
                    "action": "parse",
                    "page": normalize_title(title),
                    "prop": "wikitext",
                    "redirects": 1,
                    "format": "json",
                }
            )
        )
        with self._throttle.slot():
            raw = self._get(url)
        result = parse_response(raw, title)  # only a good page is cached
        tmp = path + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp, path)
        return result


def fetcher_from_config(config, **kwargs):
    """A Fetcher set up from the app's config (TFWIKI_ENABLED, TFWIKI_CACHE_DIR)."""
    return Fetcher(
        config.get("TFWIKI_CACHE_DIR", "tfwiki-cache"),
        enabled=bool(config.get("TFWIKI_ENABLED", False)),
        **kwargs,
    )
