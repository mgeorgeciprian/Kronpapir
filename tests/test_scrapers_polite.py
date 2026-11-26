"""Scraperele: User-Agent identificabil, robots.txt, pagini 404 cu conținut, selectorul de linkuri, data.

Run: python -m pytest tests/test_scrapers_polite.py -q
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import base_scraper  # noqa: E402
from scrapers.web_scraper import WebScraper  # noqa: E402

LIST_HTML = """<html><body>
<a href="/detalii-articol/general/strada-sforii/MzgwMDA">Sforii</a>
<a href="/detalii-articol/general/strada-sforii/MzgwMDA">Sforii (dublură)</a>
<a href="/contact">Contact</a>
<a href="https://altsite.ro/detalii-articol/x">extern</a></body></html>"""
ART_HTML = """<html><body><h1>Încep lucrările la strada Sforii</h1>
<span class="anunt-data">Data publicării: 26.11.2026</span>
<div class="continut-anunt"><p>Lucrările încep luni.</p></div></body></html>"""


def response(text, status=200, ctype="text/html"):
    r = SimpleNamespace(text=text, status_code=status, headers={"Content-Type": ctype}, apparent_encoding="utf-8",
                        encoding=None)

    def raise_for_status():
        if status >= 400:
            raise base_scraper.requests.HTTPError(f"{status}")
    r.raise_for_status = raise_for_status
    return r


CONFIG = {"id": "primaria_brasov", "name": "Primăria Brașov", "url": "https://www.brasovcity.ro",
          "homepage": "https://www.brasovcity.ro/noutati/", "type": "scrape", "max_pages": 1,
          "article_url_pattern": "/detalii-articol/", "accept_error_status": [404], "rate_limit_delay": 0,
          "selectors": {"article_links": "a[href*='/detalii-articol/']", "title": "h1",
                        "content": "div.continut-anunt", "date": "span.anunt-data"}}


class PoliteScraperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sleep = mock.patch.object(base_scraper.time, "sleep")
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.tmp.cleanup()

    def scraper(self, routes):
        sc = WebScraper(dict(CONFIG), data_dir=Path(self.tmp.name))
        calls = []

        def get(url, headers=None, **kw):
            calls.append((url, headers))
            return routes.get(url) or response("", 404)
        sc.session.get = get
        return sc, calls

    def test_finds_articles_accepts_404_and_parses_date(self):
        url = "https://www.brasovcity.ro/detalii-articol/general/strada-sforii/MzgwMDA"
        sc, calls = self.scraper({"https://www.brasovcity.ro/noutati/": response(LIST_HTML),
                                  url: response(ART_HTML, 404)})
        arts = sc.scrape()
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].title, "Încep lucrările la strada Sforii")
        self.assertEqual(arts[0].date.date(), datetime(2026, 11, 26).date())
        self.assertTrue(all(h["User-Agent"] == base_scraper.USER_AGENT for u, h in calls))
        self.assertGreaterEqual(sc.rate_limit_delay, 2)

    def test_robots_disallow_is_respected(self):
        robots = response("User-agent: KronPapirBot\nDisallow: /noutati/\n", ctype="text/plain")
        sc, calls = self.scraper({"https://www.brasovcity.ro/robots.txt": robots,
                                  "https://www.brasovcity.ro/noutati/": response(LIST_HTML)})
        self.assertEqual(sc.scrape(), [])
        self.assertNotIn("https://www.brasovcity.ro/noutati/", [u for u, _ in calls])

    def test_real_404_without_accept_is_error(self):
        cfg = dict(CONFIG, accept_error_status=[])
        sc = WebScraper(cfg, data_dir=Path(self.tmp.name))
        sc.session.get = lambda url, **kw: response("<html>nu</html>", 404)
        self.assertIsNone(sc.fetch_page("https://www.brasovcity.ro/x"))


class StaleTest(unittest.TestCase):
    def test_old_story_is_stale(self):
        import run_pipeline as rp
        now = datetime(2026, 11, 26, 12)
        self.assertTrue(rp.is_stale({"date": (now - timedelta(days=10)).isoformat()}, now))
        self.assertFalse(rp.is_stale({"date": (now - timedelta(hours=5)).isoformat()}, now))
        self.assertFalse(rp.is_stale({"date": "fără dată"}, now))


if __name__ == "__main__":
    unittest.main()
