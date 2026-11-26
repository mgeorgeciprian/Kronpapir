"""PageSpeed săptămânal: rezumat, alerte, raport pe disc, cheia doar în header."""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seo import pagespeed as ps  # noqa: E402
from sources.http import FetchError  # noqa: E402


def psi(score, lcp=2100.0, cls=0.02, field=True):
    data = {"lighthouseResult": {
        "categories": {"performance": {"score": score}},
        "audits": {"largest-contentful-paint": {"numericValue": lcp},
                   "cumulative-layout-shift": {"numericValue": cls},
                   "total-blocking-time": {"numericValue": 150.4},
                   "first-contentful-paint": {"numericValue": 900.0}}}}
    if field:
        data["loadingExperience"] = {"metrics": {
            "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2500, "category": "FAST"},
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "category": "FAST"}}}
    return data


class FakeClient:
    def __init__(self, score=0.9, fail_paths=()):
        self.calls = []
        self.score = score
        self.fail_paths = fail_paths

    def request_json(self, url, payload=None, method=None, headers=None):
        self.calls.append((url, headers))
        if any(p in url for p in self.fail_paths):
            raise FetchError("HTTP 500")
        return psi(self.score)


class PageSpeedTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.out = root / "out"
        self.processed = root / "processed"
        self.processed.mkdir()
        self.now = datetime(2026, 11, 29, 5, 0, tzinfo=ps.TZ)

    def article(self, art_id, **extra):
        a = {"id": art_id, "slug": f"s-{art_id}", "date": "2026-11-20T10:00:00",
             "source_type": "date_oficiale"}
        a.update(extra)
        (self.processed / f"{art_id}.json").write_text(json.dumps(a), encoding="utf-8")

    def test_summarize_extracts_score_lab_and_field(self):
        s = ps.summarize(psi(0.874))
        self.assertEqual(s["score"], 87)
        self.assertEqual(s["lab"]["lcp_ms"], 2100)
        self.assertEqual(s["lab"]["cls"], 0.02)
        self.assertEqual(s["field"]["lcp_ms"], {"p75": 2500, "category": "FAST"})
        self.assertEqual(s["field"]["cls"]["p75"], 0.05)
        self.assertIsNone(s["field"]["inp_ms"])
        self.assertIsNone(ps.summarize(psi(0.5, field=False))["field"])

    def test_newest_indexable_article_is_tested(self):
        self.article("a", date="2026-11-25T10:00:00")
        self.article("b", date="2026-11-26T10:00:00", status="draft")
        self.article("c", date="2026-11-27T10:00:00", source_type=None, url="https://alt-ziar.ro/x")  # rescriere veche
        self.assertEqual(ps.newest_article_path(self.processed), "/stiri/s-a")

    def test_run_writes_report_and_key_only_in_header(self):
        self.article("a")
        client = FakeClient()
        report = ps.run("CHEIE-SECRETA", client=client, out_dir=self.out,
                        processed_dir=self.processed, now=self.now)
        self.assertEqual(len(client.calls), (len(ps.PAGES) + 1) * 2)
        for url, headers in client.calls:
            self.assertNotIn("CHEIE-SECRETA", url)
            self.assertEqual(headers, {"X-Goog-Api-Key": "CHEIE-SECRETA"})
        saved = json.loads((self.out / "2026-11-29.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["results"], report["results"])
        self.assertNotIn("CHEIE-SECRETA", json.dumps(saved))
        self.assertEqual(saved["alerts"], [])

    def test_failures_are_recorded_not_fatal(self):
        report = ps.run("k", client=FakeClient(fail_paths=("%2Flocal",)), out_dir=self.out,
                        processed_dir=self.processed, now=self.now)
        errors = [r for r in report["results"] if "error" in r]
        self.assertEqual({r["path"] for r in errors}, {"/local"})
        self.assertTrue(all(r.get("score") == 90 for r in report["results"] if "error" not in r))

    def test_alerts_on_drop_and_low_score(self):
        self.out.mkdir()
        prev = {"results": [{"path": "/", "strategy": "mobile", "score": 95}]}
        (self.out / "2026-11-22.json").write_text(json.dumps(prev), encoding="utf-8")
        report = ps.run("k", client=FakeClient(score=0.8), out_dir=self.out,
                        processed_dir=self.processed, now=self.now)
        self.assertIn("/ (mobile): a scăzut de la 95 la 80", report["alerts"])
        self.assertEqual(len(report["alerts"]), 1)

        low = ps.alerts([{"path": "/local", "strategy": "mobile", "score": 42}], None)
        self.assertEqual(low, ["/local (mobile): scor 42, sub 50"])

    def test_main_refuses_without_key(self):
        import os
        old = os.environ.pop("PAGESPEED_API_KEY", None)
        self.addCleanup(lambda: old is not None and os.environ.__setitem__("PAGESPEED_API_KEY", old))
        self.assertEqual(ps.main([]), 2)


if __name__ == "__main__":
    unittest.main()
