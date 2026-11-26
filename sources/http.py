"""Client HTTP comun pentru surse: User-Agent identificabil, o cerere la 2 secunde, retry, timeout, cache.

Regulile vin din CLAUDE.md: respectăm robots.txt și termenii sursei, maximum o cerere la 2 secunde.
"""
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

USER_AGENT = "KronPapirBot/1.0 (+https://kronpapir.ro/despre)"
MIN_INTERVAL = 2.0


class FetchError(RuntimeError):
    pass


class PoliteClient:
    def __init__(self, cache_dir=None, cache_ttl=3600, min_interval=MIN_INTERVAL,
                 timeout=30, retries=3, backoff=5.0, sleep=time.sleep, clock=time.monotonic):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = cache_ttl
        self.min_interval = min_interval
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.requests_made = 0

    def _wait_turn(self):
        if self._last is not None:
            gap = self._clock() - self._last
            if gap < self.min_interval:
                self._sleep(self.min_interval - gap)
        self._last = self._clock()

    def _cache_path(self, method, url, body):
        if not self.cache_dir:
            return None
        key = hashlib.sha256(f"{method} {url}\n{body or ''}".encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _send(self, req):
        """Trimite o cerere; se poate înlocui în teste."""
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status, resp.read()

    def request_json(self, url, payload=None, method=None, headers=None):
        """`headers` în plus (ex. chei API): nu intră în cache-key și nici în loguri."""
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload is not None else None
        method = method or ("POST" if body is not None else "GET")
        cache = self._cache_path(method, url, body)
        if cache and cache.exists() and time.time() - cache.stat().st_mtime < self.cache_ttl:
            return json.loads(cache.read_text(encoding="utf-8"))

        extra = headers or {}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **extra}
        if body is not None:
            headers["Content-Type"] = "application/json"
        last_err = None
        for attempt in range(1, self.retries + 1):
            self._wait_turn()
            req = urllib.request.Request(url, data=body.encode() if body else None,
                                         headers=headers, method=method)
            try:
                self.requests_made += 1
                status, raw = self._send(req)
                if status != 200:
                    raise FetchError(f"HTTP {status} pentru {url}")
                data = json.loads(raw.decode("utf-8"))
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cache.with_suffix(".tmp")
                    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(cache)
                return data
            except urllib.error.HTTPError as e:
                last_err = e
                if 400 <= e.code < 500 and e.code != 429:
                    break  # eroare a noastră; nu insistăm
            except (urllib.error.URLError, TimeoutError, ValueError, FetchError, OSError) as e:
                last_err = e
            log.warning("Încercarea %d/%d a eșuat pentru %s: %s", attempt, self.retries, url, last_err)
            if attempt < self.retries:
                self._sleep(self.backoff * attempt)
        raise FetchError(f"{url}: {last_err}")
