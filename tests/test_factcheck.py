"""Fact-check-ul rescrierilor: cifre din sursă, date personale, decizia, reîncercarea, stocarea.

Run: python -m pytest tests/test_factcheck.py -q
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('FLASK_SECRET_KEY', 'fake-test-secret')

from ai import costs  # noqa: E402
from ai import factcheck_llm  # noqa: E402
from editorial import factcheck as fc  # noqa: E402
from editorial import store as editorial_store  # noqa: E402

NOW = datetime(2026, 11, 26)
SOURCE = ("Consiliul Local Săcele a aprobat joi un buget de 1.204.500 lei pentru asfaltarea a 12 străzi. "
          "Lucrările încep pe 15 martie și durează 90 de zile. Rata de execuție a fost 87,5%.")


def rw(content, title="Săcele asfaltează 12 străzi", **kw):
    d = {"id": "r1", "title": title, "content": f"<p>{content}</p>", "excerpt": "", "url": "https://s.ro/1",
         "category": "local", "seo_title": title}
    d.update(kw)
    return d


class DeterministicTest(unittest.TestCase):
    def test_numbers_from_source_pass_in_any_format(self):
        det = fc.deterministic(SOURCE, rw("Buget de 1204500 lei, 90 de zile, începe pe 15 martie 2026, execuție 87.5%."), NOW)
        self.assertEqual(det["erori"], [])

    def test_invented_number_is_blocking(self):
        det = fc.deterministic(SOURCE, rw("Un ocol adaugă 60-80 de kilometri."), NOW)
        self.assertEqual({e["valoare"] for e in det["erori"]}, {"60", "80"})

    def test_number_glued_to_word_in_source_passes(self):
        src = "termenul de plată a chiriei pentru locurile de parcare este15 decembrie 2026."
        det = fc.deterministic(src, rw("Chiria se plătește până la 15 decembrie.", title="Chiria parcărilor"), NOW)
        self.assertEqual(det["erori"], [])

    def test_long_numbers_written_differently_in_source_pass(self):
        det = fc.deterministic("Informații la 0268-405000.", rw("Informații: 0268 405 000.", title="Informații"), NOW)
        self.assertFalse([e for e in det["erori"] if e["tip"] == "numar_inexistent"])

    def test_small_numbers_and_112_only_warn(self):
        det = fc.deterministic(SOURCE, rw("Durează 3 zile. Sunați la 112."), NOW)
        self.assertEqual(det["erori"], [])
        self.assertEqual(det["avertismente"][0]["tip"], "numar_mic_nesursat")

    def test_contact_data_blocks(self):
        det = fc.deterministic(SOURCE + " 0722 123 456", rw("Sunați la 0722 123 456 sau ion@exemplu.ro."), NOW)
        self.assertEqual({e["tip"] for e in det["erori"]}, {"date_personale_telefon", "date_personale_email"})

    def test_sedilla_fixed(self):
        a = rw("Şedinţa a avut loc.")
        self.assertEqual(fc.fix_sedilla(a), 1)
        self.assertIn("Ședința", a["content"])


class DecideTest(unittest.TestCase):
    ok = {"erori": [], "avertismente": []}

    def test_rules(self):
        llm = {"scor": 9, "erori_blocante": [], "subiect_sensibil": False}
        self.assertEqual(fc.decide(rw("x"), self.ok, llm)[0], "published")
        self.assertEqual(fc.decide(rw("x"), self.ok, dict(llm, scor=7))[0], "draft")
        self.assertEqual(fc.decide(rw("x"), self.ok, dict(llm, subiect_sensibil=True))[0], "draft")
        self.assertEqual(fc.decide(rw("x", category="accidente"), self.ok, llm)[0], "draft")
        self.assertEqual(fc.decide(rw("x"), self.ok, None)[0], "draft")
        bad = dict(llm, erori_blocante=[{"tip": "nume_inexistent", "valoare": "Ion Pop", "motiv": "nu e în sursă"}])
        self.assertEqual(fc.decide(rw("x"), self.ok, bad)[0], "rejected")
        self.assertEqual(fc.decide(rw("x"), {"erori": [{"tip": "numar_inexistent", "valoare": "60"}],
                                             "avertismente": []}, llm)[0], "rejected")


class FakeRewriter:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def rewrite_article(self, raw):
        self.calls.append(raw)
        out = self.outputs.pop(0)
        return dict(out, id=f"r{len(self.calls)}") if out else None


class RouteTest(unittest.TestCase):
    def setUp(self):
        import run_pipeline
        self.rp = run_pipeline
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(run_pipeline, "PROCESSED_DIR", root / "processed"),
                        mock.patch.object(editorial_store, "PROCESSED_DIR", root / "processed"),
                        mock.patch.object(editorial_store, "DRAFTS_DIR", root / "drafts")]
        for p in self.patches:
            p.start()
        (root / "processed").mkdir()
        self.raw = {"title": "Asfaltare", "content": SOURCE, "url": "https://s.ro/1", "source": "Săceleanul"}
        self.checker = mock.Mock()
        self.checker.check.return_value = {"scor": 9, "erori_blocante": [], "subiect_sensibil": False,
                                           "recomandari": [], "model": "claude-sonnet-5-5"}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_good_rewrite_is_published_with_fact_check(self):
        art, decision = self.rp.rewrite_and_route(self.raw, FakeRewriter([rw("Buget de 1.204.500 lei.")]), self.checker)
        self.assertEqual(decision, "published")
        saved = json.loads((self.rp.PROCESSED_DIR / "r1.json").read_text())
        self.assertEqual(saved["fact_check"]["scor"], 9)
        self.assertEqual(saved["status"], "published")

    def test_invented_number_retries_with_feedback_then_publishes(self):
        rewriter = FakeRewriter([rw("Un detector costă 50-100 de lei."), rw("Buget de 1.204.500 lei.")])
        art, decision = self.rp.rewrite_and_route(self.raw, rewriter, self.checker)
        self.assertEqual(decision, "published")
        self.assertIn("„50”", rewriter.calls[1]["_factcheck_feedback"])
        self.assertEqual(art["fact_check"]["incercari"], 2)

    def test_twice_wrong_is_rejected_and_not_published(self):
        rewriter = FakeRewriter([rw("60 km"), rw("70 km")])
        art, decision = self.rp.rewrite_and_route(self.raw, rewriter, self.checker)
        self.assertEqual(decision, "rejected")
        self.assertFalse(any(self.rp.PROCESSED_DIR.iterdir()))
        self.assertEqual(editorial_store.get_draft(art["id"])["status"], "rejected")
        self.checker.check.assert_not_called()  # cifrele greșite opresc verificarea plătită

    def test_sensitive_goes_to_draft(self):
        self.checker.check.return_value["subiect_sensibil"] = True
        _, decision = self.rp.rewrite_and_route(self.raw, FakeRewriter([rw("Buget de 1.204.500 lei.")]), self.checker)
        self.assertEqual(decision, "draft")
        self.assertEqual(len(editorial_store.list_drafts()), 1)

    def test_drafts_count_as_seen(self):
        self.rp.rewrite_and_route(self.raw, FakeRewriter([rw("60 km"), rw("70 km")]), self.checker)
        self.assertEqual(len(self.rp.seen_article_files()), 1)


class LLMTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = Path(self.tmp.name) / "agents.yaml"
        cfg.write_text("agents:\n  editor-fact-check:\n    model: claude-sonnet-5-5\n    monthly_budget_usd: 1\n")
        self.patches = [mock.patch.object(costs, "AGENTS_CONFIG", cfg),
                        mock.patch.object(costs, "COSTS_DIR", Path(self.tmp.name) / "costs")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_parses_and_clamps_score(self):
        c = mock.MagicMock()
        c.beta.messages.create.return_value = SimpleNamespace(
            stop_reason="end_turn", usage=SimpleNamespace(input_tokens=3000, output_tokens=400),
            content=[SimpleNamespace(type="text", text=json.dumps(
                {"scor": 14, "erori_blocante": [], "subiect_sensibil": False, "motiv_sensibil": "", "recomandari": []}))])
        out = factcheck_llm.FactChecker(client=c).check({"content": SOURCE}, rw("x"))
        self.assertEqual(out["scor"], 10)
        self.assertIn("Rescrierile de presă", c.beta.messages.create.call_args.kwargs["system"])

    def test_failure_returns_none(self):
        c = mock.MagicMock()
        c.beta.messages.create.side_effect = RuntimeError("x")
        self.assertIsNone(factcheck_llm.FactChecker(client=c).check({"content": SOURCE}, rw("x")))


if __name__ == "__main__":
    unittest.main()


class CorrectionTest(unittest.TestCase):
    def test_admin_correction_is_public_and_updates_date(self):
        from web import app as webapp
        from editorial import presentation as pres
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)
        art = {"id": "c1", "slug": "buget-sacele", "title": "Buget Săcele", "content": "<p>12 milioane</p>",
               "category": "economie", "type": "local", "date": "2026-11-20T10:00:00", "source": "X"}
        (d / "c1.json").write_text(json.dumps(art), encoding="utf-8")
        with mock.patch.object(webapp, "DATA_DIR", d), \
             mock.patch.object(webapp, "_cached_processed_articles", side_effect=lambda: [
                 json.loads((d / "c1.json").read_text(encoding="utf-8"))]):
            c = webapp.app.test_client()
            with c.session_transaction() as s:
                s["admin_logged_in"] = True
            c.post("/admin/articol/editeaza/c1", data={"title": "Buget Săcele", "category": "economie", "type": "local",
                                                     "content": "<p>1,2 milioane</p>", "source": "X",
                                                     "correction": "Suma corectă e 1,2 milioane de lei, nu 12."})
            saved = json.loads((d / "c1.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["corrections"][0]["text"], "Suma corectă e 1,2 milioane de lei, nu 12.")
            self.assertTrue(saved["updated"] > "2026-11-20")
            html = c.get("/stiri/buget-sacele").get_data(as_text=True)
            self.assertIn("Actualizare (", html)
            self.assertIn("nu 12.", html)
        tmp.cleanup()
        self.assertEqual(pres.ro_datetime("2026-11-26T16:20:05"), "26 noiembrie 2026, ora 16:20")


class SourcesPageTest(unittest.TestCase):
    def test_sources_page_lists_enabled_sources_and_counts(self):
        from web import app as webapp
        arts = [{"id": "1", "title": "a", "source": "BizBrașov", "date": datetime.now().isoformat()},
                {"id": "2", "title": "b", "source": "BizBrașov", "date": datetime.now().isoformat(),
                 "duplicate_of": {"id": "1"}}]
        with mock.patch.object(webapp, "_cached_processed_articles", return_value=arts):
            html = webapp.app.test_client().get("/surse").get_data(as_text=True)
        self.assertIn("Monitorul Expres", html)
        self.assertIn("<td>1</td>", html)
        self.assertIn("am comasat astfel 1 articol dublat", html)
        self.assertIn("mediere.anofm.ro", html)


class FormatTest(unittest.TestCase):
    def test_prompt_by_source_kind(self):
        from ai.rewriter import ArticleRewriter
        rw_ = ArticleRewriter.__new__(ArticleRewriter)
        raw = {"title": "T", "content": SOURCE, "source": "BizBrașov", "url": "https://b.ro/1"}
        p_pub = rw_._build_prompt(raw)
        p_off = rw_._build_prompt(dict(raw, source="Primăria Brașov", source_kind="oficial"))
        self.assertIn("REZUMAT SCURT", p_pub)
        self.assertIn("80–150 de cuvinte", p_pub)
        self.assertIn("comunicat sau un anunț oficial", p_off)
        self.assertNotIn("36.000", p_off)  # fără cifre de populație care ajungeau în articole
        self.assertIn("CORECTURĂ", rw_._build_prompt(dict(raw, _factcheck_feedback="scoate 60")))

    def test_summary_too_long_is_blocking(self):
        long = rw(" ".join(["cuvânt"] * 200), format="rezumat")
        det = fc.deterministic(SOURCE, long, NOW)
        self.assertEqual(det["erori"][0]["tip"], "rezumat_prea_lung")
        self.assertIn("scurtează", fc.feedback(det, None))

    def test_source_kind_from_config(self):
        import run_pipeline as rp
        self.assertEqual(rp.source_kind({"source": "Primăria Brașov"}), "oficial")
        self.assertEqual(rp.source_kind({"source": "BizBrașov"}), "publicatie")
        self.assertEqual(rp.source_kind({"source": "Necunoscut"}), "publicatie")


class OfficialRouteTest(RouteTest):
    def test_official_source_becomes_official_data(self):
        raw = dict(self.raw, source="Primăria Brașov")
        art, decision = self.rp.rewrite_and_route(raw, FakeRewriter([rw("Buget de 1.204.500 lei.")]), self.checker)
        self.assertEqual(decision, "published")
        self.assertEqual(art["source_type"], "date_oficiale")
        from editorial import presentation as pres
        self.assertFalse(pres.should_noindex(art))
        self.assertIn("date oficiale", pres.byline(art)["text"])


class FairOrderTest(unittest.TestCase):
    def test_docs_first_then_round_robin_newest_first(self):
        import run_pipeline
        arts = ([{"source": "Digi24", "date": f"2026-11-27T1{i}:00", "t": f"d{i}"} for i in range(4)]
                + [{"source": "News BV", "date": "2026-11-27T09:00", "t": "n1"},
                   {"source": "News BV", "date": "2026-11-26T09:00", "t": "n2"},
                   {"source": "Primăria Brașov", "doc_type": "hcl", "date": "2026-11-20", "t": "hcl"},
                   {"source": "Bună Ziua Brașov", "date": "", "t": "b1"}])
        order = [a["t"] for a in run_pipeline.fair_order(arts)]
        self.assertEqual(order[:4], ["hcl", "d3", "n1", "b1"])
        self.assertEqual(order[4:6], ["d2", "n2"])
        self.assertEqual(sorted(order), sorted(a["t"] for a in arts))
