"""Ilustratorul: curățarea SVG, alegerea articolelor, plafonul de cost, salvarea.

Run: python -m pytest tests/test_illustrator.py -q
Fără rețea: clientul Claude e înlocuit cu unul fals.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai import illustrator as ill  # noqa: E402
from editorial import presentation as pres  # noqa: E402
from editorial import store as editorial_store  # noqa: E402

GOOD_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">'
            '<defs><filter id="p"><feTurbulence baseFrequency="0.8"/></filter></defs>'
            '<rect width="1200" height="675" fill="#f7f3ea"/>'
            '<g filter="url(#p)"><path d="M0 0 L10 10" stroke="#2b2b2b"/><line x1="0" y1="0" x2="5" y2="5"/>'
            '<circle cx="5" cy="5" r="2"/></g></svg>')
NOW = datetime(2026, 11, 26, 12, 0)


class SanitizeTest(unittest.TestCase):
    def test_keeps_drawing(self):
        out = ill.sanitize_svg(GOOD_SVG)
        self.assertIn("<path", out)
        self.assertIn('filter="url(#p)"', out)

    def test_strips_dangerous_content(self):
        bad = GOOD_SVG.replace("</svg>", '<script>alert(1)</script><image href="https://x/y.png"/>'
                               '<text>Hi</text><foreignObject/><rect onload="x()" fill="url(https://evil)"/></svg>')
        out = ill.sanitize_svg(bad)
        for s in ("script", "image", "text>", "foreignObject", "onload", "evil"):
            self.assertNotIn(s, out)

    def test_rejects_doctype_and_garbage(self):
        with self.assertRaises(ValueError):
            ill.sanitize_svg('<!DOCTYPE svg [<!ENTITY a "b">]>' + GOOD_SVG)
        with self.assertRaises(ValueError):
            ill.sanitize_svg("nu e svg")
        with self.assertRaises(ValueError):
            ill.sanitize_svg('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        with self.assertRaises(ValueError):
            ill.sanitize_svg(GOOD_SVG.replace("</svg>", "<g/>" * 40000 + "</svg>"))

    def test_metadata_marks_ai(self):
        out = ill.add_metadata(ill.sanitize_svg(GOOD_SVG), "Schiță: un autobuz")
        self.assertIn("<title>Schiță: un autobuz</title>", out)
        self.assertIn(ill.CREDIT, out)


def fake_message(svg=GOOD_SVG, alt="Schiță în creion: o stradă", stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, usage=SimpleNamespace(input_tokens=1000, output_tokens=5000),
                           content=[SimpleNamespace(type="text", text=json.dumps({"svg": svg, "alt": alt}))])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.processed = root / "processed"
        self.processed.mkdir()
        cfg = root / "agents.yaml"
        cfg.write_text("alert_threshold: 0.8\nagents:\n  ilustrator:\n    model: claude-sonnet-5-5\n"
                       "    monthly_budget_usd: 1\n", encoding="utf-8")
        self.patches = [
            mock.patch.object(editorial_store, "PROCESSED_DIR", self.processed),
            mock.patch.object(ill, "OUT_DIR", root / "ilustratii"),
            mock.patch.object(ill, "COSTS_DIR", root / "costs"),
            mock.patch.object(ill, "AGENTS_CONFIG", cfg),
        ]
        for p in self.patches:
            p.start()
        self.client = mock.MagicMock()
        self.client.beta.messages.stream.return_value.__enter__.return_value.get_final_message.return_value = fake_message()
        self.create = self.client.beta.messages.stream

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def add(self, aid, **kw):
        art = {"id": aid, "title": f"Titlu {aid}", "content": "<p>Text</p>", "date": f"2026-11-{aid[-2:]}",
               "reviewed_by": "George", "reviewed_at": "2026-11-26T10:00:00"}
        art.update(kw)
        (self.processed / f"{aid}.json").write_text(json.dumps(art), encoding="utf-8")

    def read(self, aid):
        return json.loads((self.processed / f"{aid}.json").read_text(encoding="utf-8"))

    def test_illustrates_articles_without_own_image(self):
        self.add("a-10", image="https://brasovstiri.ro/poza.jpg")
        self.add("a-11", image="/static/images/proprie.jpg")
        stats = ill.run(limit=5, client=self.client, now=NOW)
        self.assertEqual(stats["done"], 1)
        art = self.read("a-10")
        self.assertEqual(art["image"], "/static/ilustratii/a-10.svg")
        self.assertEqual(art["image_original"], "https://brasovstiri.ro/poza.jpg")
        self.assertEqual(art["image_credit"], ill.CREDIT)
        self.assertTrue((ill.OUT_DIR / "a-10.svg").exists())
        self.assertEqual(pres.safe_image(art), "/static/ilustratii/a-10.svg")
        # poza sursei a fost trimisă ca referință
        content = self.create.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(content[0]["source"]["url"], "https://brasovstiri.ro/poza.jpg")

    def test_only_articles_we_publish(self):
        self.add("a-20", reviewed_by="", reviewed_at="")                       # neverificat: nu
        self.add("a-21", reviewed_by="", reviewed_at="", source_type="date_oficiale")  # date oficiale: da
        self.add("a-22", title="Poliția a reținut un hoț în Săcele")           # poza cu poliția ajunge
        ids = [a["id"] for _, a in ill.candidates()]
        self.assertEqual(ids, ["a-21"])

    def test_newest_first_and_limit(self):
        for d in ("a-01", "a-05", "a-09"):
            self.add(d)
        ill.run(limit=2, client=self.client, now=NOW)
        self.assertIn("image", self.read("a-09"))
        self.assertIn("image", self.read("a-05"))
        self.assertNotIn("image", self.read("a-01"))

    def test_bad_svg_marks_failed_and_is_not_retried(self):
        self.add("a-12")
        self.create.return_value.__enter__.return_value.get_final_message.return_value = fake_message(svg="<p>nu</p>")
        stats = ill.run(client=self.client, now=NOW)
        self.assertEqual(stats["failed"], 1)
        self.assertIn("illustration_failed", self.read("a-12"))
        self.assertEqual(ill.candidates(), [])

    def test_budget_stops_the_run(self):
        self.add("a-13")
        self.add("a-14")
        # 1000 in + 5000 out pe Sonnet = 0,052 USD; plafon 1 USD -> blocăm din start după prag
        (ill.COSTS_DIR).mkdir()
        (ill.COSTS_DIR / "ilustrator-2026-11.json").write_text('{"usd": 1.0, "calls": 20}')
        with self.assertRaises(ill.BudgetExceeded):
            ill.run(client=self.client, now=NOW)
        self.create.assert_not_called()

    def test_cost_is_recorded(self):
        self.add("a-15")
        ill.run(client=self.client, now=NOW)
        ledger = json.loads((ill.COSTS_DIR / "ilustrator-2026-11.json").read_text())
        self.assertAlmostEqual(ledger["usd"], 0.052)
        self.assertEqual(ledger["calls"], 1)

    def test_dry_run_calls_nothing(self):
        self.add("a-16")
        stats = ill.run(dry_run=True, client=self.client, now=NOW)
        self.assertEqual(stats["todo"], 1)
        self.create.assert_not_called()


class OgImageTest(unittest.TestCase):
    def test_svg_illustration_not_used_for_social_previews(self):
        art = {"image": "/static/ilustratii/x.svg"}
        self.assertNotIn(".svg", pres.og_image(art))

    def test_prompt_has_no_frontmatter(self):
        prompt = ill.load_prompt()
        self.assertFalse(prompt.startswith("---"))
        self.assertIn("schiță în creion", prompt)


if __name__ == "__main__":
    unittest.main()
