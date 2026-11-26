"""Pozele ilustrative: alegerea după subiect și localitate, licența afișată, og:image.

Run: python -m pytest tests/test_stock_photos.py -q
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editorial import presentation as pres  # noqa: E402
from editorial import stock_photos as sp  # noqa: E402


def tag_of(title, **kw):
    return sp.choose(dict({"id": "x1", "title": title}, **kw))["tags"]


class ManifestTest(unittest.TestCase):
    def test_every_photo_exists_and_has_license(self):
        manifest = json.loads(sp.MANIFEST.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest), 30)
        for key, m in manifest.items():
            self.assertTrue((sp.FOTO_DIR / m["file"]).exists(), key)
            self.assertTrue(m["license"] and m["source_url"].startswith("https://commons.wikimedia.org/"), key)
            if m["license"].startswith("CC BY"):
                self.assertTrue(m["author"] and m["license_url"], key)
        tags = {t for m in manifest.values() for t in m["tags"]}
        for needed in ("brasov", "sacele", "tarlungeni", "politie", "pompieri", "ambulanta"):
            self.assertIn(needed, tags)


class ChooseTest(unittest.TestCase):
    def test_topics(self):
        self.assertIn("politie", tag_of("Polițiștii brașoveni au reținut doi suspecți de furt"))
        self.assertIn("pompieri", tag_of("Incendiu puternic într-o hală din Ghimbav"))
        self.assertIn("ambulanta", tag_of("Accident pe DN1, între Brașov și Predeal"))
        self.assertIn("justitie", tag_of("Tribunalul Brașov a decis arestarea"))

    def test_politics_is_not_police(self):
        self.assertNotIn("politie", tag_of("Politica locală: ședința Consiliului Județean"))

    def test_places(self):
        self.assertIn("sacele", tag_of("Străzi noi asfaltate în Săcele"))
        self.assertIn("tarlungeni", tag_of("Apă curentă la Zizin"))
        self.assertIn("rasnov", tag_of("Festival la Râșnov"))

    def test_topic_beats_place(self):
        self.assertIn("politie", tag_of("Furt dintr-un magazin din Săcele"))

    def test_generic_fallback_and_stable_choice(self):
        art = {"id": "abc", "title": "Ședința de joi"}
        self.assertIn("brasov", sp.choose(art)["tags"])
        self.assertEqual(sp.choose(art)["key"], sp.choose(dict(art))["key"])

    def test_domestic_violence_is_police(self):
        self.assertIn("politie", tag_of("313 sesizări de violență domestică la Brașov"))

    def test_place_only_from_title(self):
        self.assertIn("brasov", tag_of("Ghimbav rămâne fără autobuze", keywords=["Codlea"]))

    def test_non_local_news(self):
        self.assertIsNone(sp.choose({"id": "1", "title": "Israel amenință", "type": "international"}))
        self.assertIsNone(sp.choose({"id": "1", "title": "UE amână raportarea", "type": "national", "category": "economie"}))
        self.assertIn("politie", sp.choose({"id": "1", "title": "Poliția a reținut un hoț", "type": "national"})["tags"])
        self.assertIsNone(sp.choose({"id": "1", "title": "Opinie", "is_editorial": True, "type": "editorial"}))

    def test_needs_illustration(self):
        self.assertFalse(sp.needs_illustration({"title": "Accident grav la Codlea"}))
        self.assertTrue(sp.needs_illustration({"title": "Locuri de muncă la AJOFM"}))


class PresentationTest(unittest.TestCase):
    def test_own_image_wins(self):
        art = {"id": "1", "title": "Furt", "image": "/static/ilustratii/1.svg"}
        self.assertEqual(pres.display_image(art), "/static/ilustratii/1.svg")
        self.assertIsNone(pres.stock_photo(art))

    def test_external_image_replaced_by_stock(self):
        art = {"id": "1", "title": "Furt la Săcele", "image": "https://altsite.ro/poza.jpg"}
        self.assertTrue(pres.display_image(art).startswith("/static/images/foto/politie"))
        self.assertTrue(pres.og_image(art).startswith("https://kronpapir.ro/static/images/foto/politie"))

    def test_svg_illustration_uses_stock_for_social(self):
        art = {"id": "1", "title": "Apă la Zizin", "image": "/static/ilustratii/1.svg"}
        self.assertTrue(pres.og_image(art).startswith("https://kronpapir.ro/static/images/foto/tarlungeni"))


if __name__ == "__main__":
    unittest.main()
