"""Raportul lunar AJOFM: cifre, text, ciornă, comparație cu luna trecută.

Run: python -m pytest tests/test_ajofm_report.py -q
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('FLASK_SECRET_KEY', 'fake-test-secret')

from editorial import store as editorial_store  # noqa: E402
from reports import ajofm_report as rep  # noqa: E402

TODAY = date(2026, 11, 26)


def job(i, **kw):
    base = {"id": i, "title": "Ajutor bucătar", "active": True, "valid_through": "2026-12-31",
            "locality": "Brașov", "domain": "Turism / Alimentație", "employer_name": f"FIRMA {i % 4} SRL",
            "employer_cui": str(i % 4), "positions": 2, "salary_min": 4000 + 100 * i, "salary_type": "brut",
            "experience": "Fără experiență - 0 ani", "education": "Gimnazial - ȘCOALĂ GENERALĂ",
            "contract_type": "Cu durată nedeterminată", "work_regime": "Sediu", "eu_citizens": False,
            "date_posted": "2026-11-10"}
    base.update(kw)
    return base


def make_store(n=30, extra=()):
    jobs = [job(i) for i in range(n)] + list(extra)
    return {"fetched_at": "2026-11-26T05:40:00+02:00", "jobs": {str(j["id"]): j for j in jobs}}


class ComputeTest(unittest.TestCase):
    def test_counts_only_active_jobs(self):
        store = make_store(extra=[job(100, active=False), job(101, valid_through="2026-11-01")])
        s = rep.compute(store, TODAY)
        self.assertEqual(s["offers"], 30)
        self.assertEqual(s["positions"], 60)
        self.assertEqual(s["employers"], 4)

    def test_missing_positions_count_as_one(self):
        s = rep.compute(make_store(extra=[job(200, positions=None, title="Paznic")]), TODAY)
        self.assertEqual(s["positions"], 61)
        paznic = next(o for o in s["occupations"] if o["name"] == "Paznic")
        self.assertEqual(paznic["positions"], 1)

    def test_salary_median_needs_enough_offers(self):
        s = rep.compute(make_store(n=30), TODAY)
        self.assertEqual(s["salary_gross"]["count"], 30)
        self.assertEqual(s["salary_gross"]["median"], 4000 + 100 * 14.5)
        self.assertIsNone(s["salary_net"])

    def test_titles_get_diacritics(self):
        s = rep.compute(make_store(extra=[job(300, title="Conducator auto", positions=500)]), TODAY)
        self.assertEqual(s["occupations"][0]["name"], "Conducător auto")


class RenderTest(unittest.TestCase):
    def test_text_and_fields(self):
        art = rep.render(rep.compute(make_store(), TODAY))
        self.assertEqual(art["id"], "ajofm-raport-2026-11")
        self.assertEqual(art["source_type"], "date_oficiale")
        self.assertIn("60 de posturi libere", art["title"])
        self.assertIn("30 de oferte active", art["content"])
        self.assertIn("mediere.anofm.ro", art["content"])
        self.assertIn("/locuri-de-munca-brasov?loc=Bra%C8%99ov", art["content"])
        self.assertNotIn("luna trecută", art["content"])

    def test_compares_with_previous_month(self):
        prev = {"positions": 50, "offers": 25}
        art = rep.render(rep.compute(make_store(), TODAY), prev)
        self.assertIn("cu 10 posturi mai multe decât luna trecută (20%)", art["content"])

    def test_escapes_employer_names(self):
        art = rep.render(rep.compute(make_store(extra=[job(400, employer_name="<b>X</b>", positions=99)]), TODAY))
        self.assertNotIn("<b>X</b>", art["content"])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        (self.data / "jobs").mkdir(parents=True)
        self.patches = [mock.patch.object(editorial_store, "DRAFTS_DIR", root / "drafts"),
                        mock.patch.object(editorial_store, "PROCESSED_DIR", root / "processed")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write_store(self, store):
        (self.data / "jobs" / "ajofm_brasov.json").write_text(json.dumps(store), encoding="utf-8")

    def test_saves_draft_and_snapshot(self):
        self.write_store(make_store())
        art, saved = rep.run(data_dir=self.data, today=TODAY)
        self.assertTrue(saved)
        draft = editorial_store.get_draft(art["id"])
        self.assertEqual(draft["status"], "draft")
        self.assertFalse((editorial_store.PROCESSED_DIR / f"{art['id']}.json").exists())
        snap = json.loads((self.data / "jobs" / "reports" / "2026-11.json").read_text())
        self.assertEqual(snap["positions"], 60)

    def test_uses_previous_snapshot(self):
        self.write_store(make_store())
        (self.data / "jobs" / "reports").mkdir()
        (self.data / "jobs" / "reports" / "2026-10.json").write_text(json.dumps({"positions": 60, "offers": 30}))
        art, _ = rep.run(data_dir=self.data, today=TODAY)
        self.assertIn("la fel ca luna trecută", art["content"])

    def test_dry_run_writes_nothing(self):
        self.write_store(make_store())
        _, saved = rep.run(data_dir=self.data, today=TODAY, dry_run=True)
        self.assertFalse(saved)
        self.assertFalse((self.data / "jobs" / "reports").exists())
        self.assertEqual(editorial_store.list_drafts(), [])

    def test_refuses_when_too_few_jobs(self):
        self.write_store(make_store(n=5))
        with self.assertRaises(RuntimeError):
            rep.run(data_dir=self.data, today=TODAY)

    def test_does_not_overwrite_published_report(self):
        self.write_store(make_store())
        editorial_store.PROCESSED_DIR.mkdir(parents=True)
        (editorial_store.PROCESSED_DIR / "ajofm-raport-2026-11.json").write_text("{}")
        _, saved = rep.run(data_dir=self.data, today=TODAY)
        self.assertFalse(saved)
        self.assertEqual(editorial_store.list_drafts(), [])


if __name__ == "__main__":
    unittest.main()
