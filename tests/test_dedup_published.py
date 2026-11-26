"""Dublurile deja publicate: grupare, articolul păstrat, marcarea, 301 și ascunderea din liste."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('FLASK_SECRET_KEY', 'fake-test-secret')

from editorial import dedup_published as dp  # noqa: E402
from editorial import presentation as pres  # noqa: E402
from editorial import store as editorial_store  # noqa: E402

A = {"id": "a1", "slug": "coliban-2028", "title": "Coliban candidează din nou în 2028, după ce Boghiu pierde cursa internă",
     "content": "x" * 500, "source": "Mediafax", "url": "https://m.ro/1", "date": "2026-11-21T10:00:00"}
B = {"id": "b2", "slug": "coliban-2028-b", "title": "Coliban candidează din nou în 2028, Boghiu pierde votul intern",
     "content": "y" * 450, "source": "G4Media", "url": "https://g4.ro/2", "date": "2026-11-22T10:00:00"}
C = {"id": "c3", "slug": "concert", "title": "Concert de colinde la Biserica Neagră", "content": "z",
     "source": "X", "url": "https://x.ro/3", "date": "2026-11-22T10:00:00"}


class ClusterTest(unittest.TestCase):
    def test_groups_and_keeper(self):
        groups = dp.clusters([A, B, C])
        self.assertEqual(len(groups), 1)
        self.assertEqual({a["id"] for a in groups[0][0]}, {"a1", "b2"})
        self.assertEqual(dp.keeper(groups[0][0])["id"], "a1")  # primul publicat

    def test_much_longer_later_article_wins(self):
        short = dict(A, content="x" * 100)
        self.assertEqual(dp.keeper([short, B])["id"], "b2")


class MarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patch = mock.patch.object(editorial_store, "PROCESSED_DIR", self.dir)
        self.patch.start()
        for a in (A, B, C):
            (self.dir / f"{a['id']}.json").write_text(json.dumps(a), encoding="utf-8")

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def read(self, i):
        return json.loads((self.dir / f"{i}.json").read_text(encoding="utf-8"))

    def test_apply_marks_duplicate_and_credits_source(self):
        with mock.patch("editorial.dedup.recent", side_effect=lambda arts, **kw: arts):
            dp.main(["--apply"])
        self.assertEqual(self.read("b2")["duplicate_of"]["slug"], "coliban-2028")
        self.assertEqual(self.read("a1")["also_reported_by"][0]["source"], "G4Media")
        self.assertNotIn("duplicate_of", self.read("a1"))
        self.assertNotIn("duplicate_of", self.read("c3"))
        self.assertTrue(pres.should_noindex(self.read("b2")))

    def test_dry_run_and_skip(self):
        with mock.patch("editorial.dedup.recent", side_effect=lambda arts, **kw: arts):
            dp.main([])
            self.assertNotIn("duplicate_of", self.read("b2"))
            dp.main(["--apply", "--skip", "b2"])
        self.assertNotIn("duplicate_of", self.read("b2"))


class WebTest(unittest.TestCase):
    def test_duplicate_page_redirects_and_is_hidden(self):
        from web import app as webapp
        dup = dict(B, duplicate_of={"id": "a1", "slug": "coliban-2028"})
        with mock.patch.object(webapp, "_cached_processed_articles", return_value=[A, dup]):
            client = webapp.app.test_client()
            r = client.get("/stiri/coliban-2028-b")
            self.assertEqual(r.status_code, 301)
            self.assertTrue(r.headers["Location"].endswith("/stiri/coliban-2028"))
            self.assertEqual([a["id"] for a in webapp.load_articles()], ["a1"])
            self.assertEqual(len(webapp.load_articles(all_types=True)), 2)


if __name__ == "__main__":
    unittest.main()
