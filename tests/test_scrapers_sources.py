"""Surse reparate: date din text, data din listă, articole fără dată, titlu vs. corp (Digi24), configurația.

Run: python -m pytest tests/test_scrapers_sources.py -q
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import base_scraper, coherence  # noqa: E402
from scrapers.base_scraper import Article  # noqa: E402
from scrapers.rss_scraper import RSSscraper  # noqa: E402
from scrapers.web_scraper import WebScraper, parse_ro_date  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def response(text, status=200, ctype="text/html"):
    r = SimpleNamespace(text=text, status_code=status, headers={"Content-Type": ctype},
                        apparent_encoding="utf-8", encoding=None)

    def raise_for_status():
        if status >= 400:
            raise base_scraper.requests.HTTPError(f"{status}")
    r.raise_for_status = raise_for_status
    return r


class ParseDateTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_ro_date("2026-11-26T18:36:18+02:00"), datetime(2026, 11, 26, 18, 36, 18))
        self.assertEqual(parse_ro_date("Data publicării: 26.11.2026"), datetime(2026, 11, 26))
        self.assertEqual(parse_ro_date("17/11/2026 Rețeaua de hidranți"), datetime(2026, 11, 17))
        self.assertEqual(parse_ro_date("Publicat la26 noiembrie 2026"), datetime(2026, 11, 26))
        self.assertEqual(parse_ro_date("3 Noiembrie 2026"), datetime(2026, 11, 3))

    def test_relative(self):
        now = datetime(2026, 11, 26, 18, 0)
        self.assertEqual(parse_ro_date("Acum\xa01 zi, 8 ore", now), now - timedelta(days=1, hours=8))
        self.assertEqual(parse_ro_date("Acum 35 minute", now), now - timedelta(minutes=35))

    def test_no_date(self):
        self.assertIsNone(parse_ro_date("26 noi"))
        self.assertIsNone(parse_ro_date(""))
        self.assertIsNone(parse_ro_date("31.02.2026"))


LIST_RASNOV = """<html><body><div class="posts-image-wrapper"><div class="row">
<div class="col-12 col-lg-4"><a href="/stiri/hidranti">17/11/2026 Rețeaua de hidranți se extinde</a></div>
<div class="col-12 col-lg-4"><a href="/stiri/fara-data">Fără dată în listă</a></div>
</div></div><a href="/contact">Contact</a></body></html>"""
ART = """<html><body><div class="page-header-title"><h1>{title}</h1></div><h1>Meniu</h1>
<div class="page-content-wrapper"><div class="col-md-12"><p>{body}</p></div></div></body></html>"""

RASNOV = {"id": "primaria_rasnov", "name": "Primăria Râșnov", "url": "https://www.primariarasnov.ro",
          "homepage": "https://www.primariarasnov.ro/stiri", "type": "scrape", "max_pages": 1,
          "article_url_pattern": "/stiri/[^/]+$", "rate_limit_delay": 0,
          "selectors": {"article_links": "div.posts-image-wrapper a[href*='/stiri/']",
                        "listing_item": "div.posts-image-wrapper div.col-12",
                        "title": "div.page-header-title h1, h1",
                        "content": "div.page-content-wrapper div.col-md-12", "date": "span.post-date"}}


class WebScraperDatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(base_scraper.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def scraper(self, cfg, routes):
        sc = WebScraper(dict(cfg), data_dir=Path(self.tmp.name))
        sc.session.get = lambda url, headers=None, **kw: routes.get(url) or response("", 404)
        return sc

    def test_listing_date_used_and_undated_article_skipped(self):
        base = "https://www.primariarasnov.ro"
        sc = self.scraper(RASNOV, {
            base + "/stiri": response(LIST_RASNOV),
            base + "/stiri/hidranti": response(ART.format(title="Rețeaua de hidranți se extinde",
                                                         body="Patru hidranți noi în Râșnov.")),
            base + "/stiri/fara-data": response(ART.format(title="Fără dată", body="Text.")),
        })
        arts = sc.scrape()
        self.assertEqual([a.url for a in arts], [base + "/stiri/hidranti"])
        self.assertEqual(arts[0].date, datetime(2026, 11, 17))
        self.assertEqual(arts[0].title, "Rețeaua de hidranți se extinde")  # primul h1, nu și „Meniu”

    def test_require_date_can_be_turned_off(self):
        base = "https://www.primariarasnov.ro"
        sc = self.scraper(dict(RASNOV, require_date=False), {
            base + "/stiri": response(LIST_RASNOV),
            base + "/stiri/fara-data": response(ART.format(title="Fără dată", body="Text.")),
        })
        self.assertEqual([a.url for a in sc.scrape()], [base + "/stiri/fara-data"])

    def test_meta_published_time_fallback(self):
        cfg = {"id": "cjcv", "name": "CJ Covasna", "url": "https://www.cjcv.ro", "rate_limit_delay": 0,
               "homepage": "https://www.cjcv.ro/ro/stiri.html", "max_pages": 1,
               "article_url_pattern": r"/ro/[^/]+\.html$",
               "selectors": {"article_links": "h2.pb-title a", "title": "h1", "content": "p",
                             "date": "span.nu-exista"}}
        html = ('<html><head><meta property="article:published_time" content="2026-10-23T00:00:00+03:00">'
                '</head><body><h1>Pregătiri pentru iarnă</h1><p>Drumurile județene.</p></body></html>')
        sc = self.scraper(cfg, {
            "https://www.cjcv.ro/ro/stiri.html": response(
                '<h2 class="pb-title"><a href="/ro/iarna.html">Iarnă</a></h2><a href="/ro/stiri_pagina2.html">2</a>'),
            "https://www.cjcv.ro/ro/iarna.html": response(html),
        })
        arts = sc.scrape()
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].date, datetime(2026, 10, 23))


GENZ = "Generația Z schimbă scena politică mondială. Tinerii se îndreaptă spre extreme"
SPORT = ("Alex Chipciu: M-a scuipat și m-a înjurat un hominid. Dacă îl prindeam, îl omoram! "
         "Descarcă aplicația Digi Sport. Fotbalistul a povestit incidentul de după meci. ") * 8
GENZ_BODY = ("Mii de tineri din Generația Z se pregătesc să protesteze. Sondajele arată că tinerii "
             "schimbă scena politică, iar unii se îndreaptă spre extrema stângă, alții spre extrema dreaptă. ") * 6


class CoherenceTest(unittest.TestCase):
    def test_wrong_body_is_mismatch(self):
        self.assertTrue(coherence.is_mismatch(GENZ, SPORT))
        self.assertFalse(coherence.is_mismatch(GENZ, GENZ_BODY))

    def test_short_excerpt_is_not_judged(self):
        # extrasele scurte din RSS (G4Media, Mediafax) folosesc alte cuvinte decât titlul
        self.assertFalse(coherence.is_mismatch(GENZ, "<p>Mii de oameni au ieșit în stradă.</p>"))

    def test_short_title_is_not_judged(self):
        self.assertIsNone(coherence.title_overlap("HCL 218", SPORT))
        self.assertFalse(coherence.is_mismatch("HCL 218", SPORT))

    def test_run_skips_mismatched_article_and_does_not_mark_it(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = {"id": "digi24", "name": "Digi24", "url": "https://www.digi24.ro", "rate_limit_delay": 0}
        sc = WebScraper(cfg, data_dir=Path(tmp.name))
        good = Article(GENZ, GENZ_BODY, "Digi24", "https://www.digi24.ro/a-1")
        bad = Article(GENZ, SPORT, "Digi24", "https://www.digi24.ro/a-2")
        sc.scrape = lambda: [good, bad]
        stats = sc.run()
        self.assertEqual((stats["articles_saved"], stats["mismatched"]), (1, 1))
        self.assertFalse(sc.is_duplicate(bad))  # se reia după repararea selectorului


DIGI_PAGE = """<html><body><h1>{title}</h1>
<div class="article article-alt"><div class="article-content">{sport}</div></div>
<div class="entry data-app-meta data-app-meta-article"><p>{body}</p></div></body></html>"""


class Digi24Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(base_scraper.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = {s["id"]: s for s in yaml.safe_load(open(ROOT / "config/sources.yaml"))["sources"]}["digi24"]

    def entry(self):
        return {"title": GENZ, "link": "https://www.digi24.ro/stiri/genz-1", "summary": "Tinerii protestează."}

    def test_selector_takes_article_text_not_recommended_cards(self):
        sc = RSSscraper(dict(self.cfg, rate_limit_delay=0), data_dir=Path(self.tmp.name))
        page = DIGI_PAGE.format(title=GENZ, sport=SPORT, body=GENZ_BODY)
        sc.session.get = lambda url, headers=None, **kw: response(page)
        art = sc._parse_rss_entry(self.entry())
        self.assertIn("Generația Z", art.content)
        self.assertNotIn("Chipciu", art.content)

    def test_rss_falls_back_to_summary_when_page_body_is_another_story(self):
        cfg = dict(self.cfg, rate_limit_delay=0, selectors=dict(self.cfg["selectors"], content="div.article-content"))
        sc = RSSscraper(cfg, data_dir=Path(self.tmp.name))
        page = DIGI_PAGE.format(title=GENZ, sport=SPORT, body=GENZ_BODY)
        sc.session.get = lambda url, headers=None, **kw: response(page)
        art = sc._parse_rss_entry(self.entry())
        self.assertEqual(art.content, "Tinerii protestează.")


class SourcesConfigTest(unittest.TestCase):
    def test_enabled_scrape_sources_have_link_selector_and_homepage_under_url(self):
        sources = yaml.safe_load(open(ROOT / "config/sources.yaml"))["sources"]
        for s in sources:
            if not s.get("enabled"):
                continue
            if s["type"] == "rss":
                self.assertTrue(s.get("rss_url"), s["id"])
                continue
            sel = s.get("selectors", {})
            self.assertTrue(sel.get("article_links") or sel.get("article_link"), s["id"])
            # linkurile articolelor trebuie să înceapă cu `url` (altfel scraperul le aruncă pe toate)
            self.assertTrue((s.get("homepage") or s["url"]).startswith(s["url"].rstrip("/")), s["id"])
            self.assertFalse(s["url"].endswith((".html", "/stiri", "/anunturi/")), s["id"])


if __name__ == "__main__":
    unittest.main()
