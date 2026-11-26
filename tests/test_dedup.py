"""Aceeași știre din două surse: scor, decizie, sursa adăugată, integrarea în pipeline.

Run: python -m pytest tests/test_dedup.py -q
Fără rețea: judecătorul AI e înlocuit cu unul fals.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('FLASK_SECRET_KEY', 'fake-test-secret')

from ai import costs  # noqa: E402
from ai import dedup_judge  # noqa: E402
from editorial import dedup  # noqa: E402

NOW = datetime(2026, 11, 26, 12, 0)


def art(title, text="", source="A", url=None, **kw):
    d = {"title": title, "content": text, "source": source, "url": url or f"https://{source}.ro/{abs(hash(title))}",
         "date": NOW.isoformat()}
    d.update(kw)
    return d


# Perechi reale din colectarea de pe 26 noiembrie 2026 (titluri).
SAME = [
    ("Allen Coliban este candidatul USR Brașov pentru Primăria Brașov",
     "Allen Coliban, desemnat candidatul USR Brașov pentru Primăria Brașov"),
    ("Noul Mers al Trenurilor intră în vigoare pe 13 decembrie. Călătorii au rute noi",
     "Noul Mers al Trenurilor intră în vigoare pe 13 decembrie. Trenuri noi spre Brașov"),
    ("Portalul e-SănătateaMea, indisponibil până pe 24 noiembrie",
     "Portalul e-SănătateaMea, indisponibil 5 zile pentru lucrări de mentenanță"),
]
DIFFERENT = [
    ("Castelul Bran își aprinde luminițele de sărbătoare pe 1 Decembrie",
     "„Împreună de Crăciun la Sinaia”, în decembrie. Invitat special"),
    ("Accident pe DN1 la Timișu de Sus, două mașini implicate",
     "Concert de colinde la Biserica Neagră, sâmbătă seara"),
]


class ScoreTest(unittest.TestCase):
    def score(self, a, b):
        return dedup.similarity(dedup.fingerprint(art(a)), dedup.fingerprint(art(b)))

    def test_real_duplicates_score_high(self):
        for a, b in SAME:
            self.assertGreaterEqual(self.score(a, b), dedup.MAYBE, (a, b))

    def test_different_stories_score_low(self):
        for a, b in DIFFERENT:
            self.assertLess(self.score(a, b), dedup.MAYBE, (a, b))

    def test_diacritics_and_case_do_not_matter(self):
        self.assertGreater(self.score("Ședința Consiliului Local Săcele", "sedinta consiliului local sacele"), 0.9)

    def test_lead_text_helps_when_titles_differ(self):
        text = ("Consiliul Județean Brașov a semnat joi contractul pentru modernizarea drumului județean 103A "
                "între Săcele și Întorsura Buzăului, în valoare de 48 de milioane de lei, cu termen de 18 luni.")
        a = art("CJ Brașov modernizează DJ103A", text)
        b = art("Contract semnat pentru drumul dintre Săcele și Întorsura Buzăului", text.replace("joi", "ieri"))
        self.assertGreaterEqual(dedup.similarity(dedup.fingerprint(a), dedup.fingerprint(b)), dedup.SURE)


class CheckTest(unittest.TestCase):
    def test_same_url_is_duplicate(self):
        ex = art("Titlu oarecare", url="https://x.ro/1")
        verdict, found, _, _ = dedup.check(art("Alt titlu complet", url="https://x.ro/1"), dedup.Index([ex]))
        self.assertEqual((verdict, found), ("duplicat", ex))

    def test_sure_duplicate_needs_no_judge(self):
        judge = mock.Mock()
        idx = dedup.Index([art(SAME[0][0], source="Litera9")])
        verdict, *_ = dedup.check(art(SAME[0][1], source="Monitorul"), idx, judge)
        self.assertEqual(verdict, "duplicat")
        judge.assert_not_called()

    def test_borderline_asks_judge(self):
        idx = dedup.Index([art("Dudu Georgescu a murit. Legendarul atacant avea 76 de ani")])
        cand = art("A murit Dudu Georgescu, fostul mare golgheter al clubului Dinamo")
        with mock.patch.object(dedup, "SURE", 0.99), mock.patch.object(dedup, "MAYBE", 0.05):
            judge = mock.Mock(return_value=(True, "același deces"))
            self.assertEqual(dedup.check(cand, idx, judge)[0], "duplicat")
            judge.return_value = (False, "nu")
            self.assertEqual(dedup.check(cand, idx, judge)[0], "nou")
            self.assertEqual(dedup.check(cand, idx, None)[0], "nou")  # fără judecător: nu pierdem știri

    def test_recent_skips_old_and_editorials(self):
        items = [art("nou"), art("vechi", date=(NOW - timedelta(days=10)).isoformat()),
                 art("editorial", is_editorial=True)]
        self.assertEqual([a["title"] for a in dedup.recent(items, NOW)], ["nou"])

    def test_merge_source_once(self):
        ex = art("X", url="https://a.ro/1")
        cand = art("X", source="Mediafax", url="https://m.ro/2")
        self.assertTrue(dedup.merge_source(ex, cand))
        self.assertFalse(dedup.merge_source(ex, cand))
        self.assertFalse(dedup.merge_source(ex, art("X", url="https://a.ro/1")))
        self.assertEqual(ex["also_reported_by"][0]["source"], "Mediafax")


class PipelineTest(unittest.TestCase):
    def setUp(self):
        import run_pipeline
        self.rp = run_pipeline
        self.tmp = tempfile.TemporaryDirectory()
        self.processed = Path(self.tmp.name)
        self.patch = mock.patch.object(run_pipeline, "PROCESSED_DIR", self.processed)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_duplicate_adds_source_to_published_article(self):
        pub = art(SAME[0][0], source="Litera9", url="https://litera9.ro/1", id="p1")
        (self.processed / "p1.json").write_text(json.dumps(pub), encoding="utf-8")
        idx = self.rp.load_dedup_index()
        cand = art(SAME[0][1], source="Monitorul Expres", url="https://monitorulexpres.ro/2")
        self.assertTrue(self.rp.is_duplicate(cand, idx, None))
        saved = json.loads((self.processed / "p1.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["also_reported_by"][0]["url"], "https://monitorulexpres.ro/2")
        self.assertFalse(self.rp.is_duplicate(art("Concert la Biserica Neagră"), idx, None))

    def test_distinct_stories_for_editorials(self):
        pool = [art(SAME[1][0], source="A"), art(SAME[1][1], source="B"), art("Altă știre despre buget", source="C")]
        picked = self.rp.distinct_stories(pool, 5)
        self.assertEqual([p["source"] for p in picked], ["A", "C"])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Path(self.tmp.name) / "agents.yaml"
        cfg.write_text("agents:\n  redactor-sef:\n    model: claude-opus-5-5\n    monthly_budget_usd: 1\n")
        self.patches = [mock.patch.object(costs, "AGENTS_CONFIG", cfg),
                        mock.patch.object(costs, "COSTS_DIR", Path(self.tmp.name) / "costs")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def client(self, payload, stop="end_turn"):
        c = mock.MagicMock()
        c.beta.messages.create.return_value = SimpleNamespace(
            stop_reason=stop, usage=SimpleNamespace(input_tokens=1500, output_tokens=100),
            content=[SimpleNamespace(type="text", text=json.dumps(payload))])
        return c

    def test_judge_answer_and_cost(self):
        c = self.client({"aceeasi_stire": True, "motiv": "același anunț"})
        judge = dedup_judge.make_judge(client=c)
        self.assertEqual(judge(art("a"), art("b")), (True, "același anunț"))
        self.assertGreater(costs.spent("redactor-sef", datetime.now()), 0)
        kwargs = c.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertIn("Știri duplicate", kwargs["system"])

    def test_errors_mean_different(self):
        c = self.client({}, stop="refusal")
        self.assertFalse(dedup_judge.make_judge(client=c)(art("a"), art("b"))[0])
        c.beta.messages.create.side_effect = RuntimeError("rețea")
        self.assertFalse(dedup_judge.make_judge(client=c)(art("a"), art("b"))[0])

    def test_no_judge_over_budget(self):
        (Path(self.tmp.name) / "costs").mkdir()
        (Path(self.tmp.name) / "costs" / f"redactor-sef-{datetime.now():%Y-%m}.json").write_text('{"usd": 5, "calls": 1}')
        self.assertIsNone(dedup_judge.make_judge(client=self.client({})))


if __name__ == "__main__":
    unittest.main()
