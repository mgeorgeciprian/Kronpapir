"""Documente oficiale brasovcity.ro: parsare, ce e deschis, decizii HCL, articol brut, fact-check.

Run: python -m pytest tests/test_brasovcity.py -q    (fără rețea: client fals)
"""
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from editorial import factcheck as fc  # noqa: E402
from sources import brasovcity as bc  # noqa: E402

NOW = datetime(2026, 11, 26, 6, 0)


def hcl_card(slug, status, day="20 Noi 2026", period="în perioada 20.11.2026 – 05.12.2026"):
    return f"""<article class="card"><span class="btn btn-primary btn-sm">{day}</span>
    <span class="btn btn-secondary btn-sm">{status}</span>
    <h2><a href="/consiliul-local/proiecte-de-hotarare-dezbatere-publica/{slug}/ID{slug}">PROIECT DE HOTĂRÂRE privind {slug}</a></h2>
    <blockquote><ul><li><a href="/file-zone/proiecte/hotarare/{slug}/01. Anunt dezbatere publica.pdf">01. Anunt dezbatere publica</a></li>
    <li><a href="/file-zone/proiecte/hotarare/{slug}/02. Proiect HCL.pdf">02. Proiect HCL</a></li></ul></blockquote>
    <p>Propunerile se pot depune {period}, prin e-mail la adresa contact@pietepublice.ro</p></article>"""


TENDER = """<div class="accordion-item"><h2 class="accordion-header"><button><span>08-01-2027 ora 12:00</span></button></h2>
<div class="accordion-body"><p>Termenul limită de depunere a ofertelor: 08.01.2027 ora 12:00</p>
<a href="/primaria/anunt-licitatie/3335">Vezi în pagină separată</a>
<p>Licitația publică privind închirierea unor imobile proprietatea privată a Municipiului Brașov</p>
<p>Punct(e) de contact: ION POPESCU</p><p>spațiu de locuit, Str. Gheorghe Barițiu nr. 9, ap. 4, 17,02 mp.</p></div></div>
<div class="accordion-item"><h2 class="accordion-header"><button><span>26-10-2026 ora 12:00</span> - termen expirat</button></h2>
<div class="accordion-body"><a href="/primaria/anunt-achizitie-procedura-proprie/1">Vezi în pagină separată</a>
<p>Denumire contract: Studiu de fezabilitate grădinița 17</p></div></div>"""


class FakeClient:
    def __init__(self, pages):
        self.pages, self.requests_made, self.urls = pages, 0, []

    def request_bytes(self, url, **kw):
        self.requests_made += 1
        self.urls.append(url)
        if url.endswith(".pdf"):
            return b"%PDF fake"
        return self.pages.get(url, "<html></html>").encode()


class ParseTest(unittest.TestCase):
    def test_hcl_card(self):
        item = bc.parse_hcl_page(hcl_card("taxe-2027", "În dezbatere publică"))[0]
        self.assertEqual(item["published"], date(2026, 11, 20))
        self.assertEqual(item["deadline"], date(2026, 12, 5))
        self.assertEqual(item["status"], "În dezbatere publică")
        self.assertIn("%20", item["files"][0][1])  # spațiile din numele PDF-ului sunt codate
        self.assertTrue(bc.is_open(item, NOW.date()))

    def test_closed_and_old_projects(self):
        approved = bc.parse_hcl_page(hcl_card("a", "Aprobat prin HCL"))[0]
        self.assertFalse(bc.is_open(approved, NOW.date()))
        stale = bc.parse_hcl_page(hcl_card("b", "În dezbatere publică", day="08 Ian 2024", period=""))[0]
        self.assertFalse(bc.is_open(stale, NOW.date()))
        past = bc.parse_hcl_page(hcl_card("c", "În dezbatere publică", period="în perioada 2.11.2026 – 11.11.2026"))[0]
        self.assertFalse(bc.is_open(past, NOW.date()))

    def test_tenders(self):
        items = bc.parse_tender_page(TENDER, "licitatie")
        self.assertEqual(items[0]["title"], "Licitația publică privind închirierea unor imobile proprietatea privată a Municipiului Brașov")
        self.assertEqual(items[0]["deadline"], date(2027, 1, 8))
        self.assertTrue(bc.is_open(items[0], NOW.date()))
        self.assertFalse(bc.is_open(items[1], NOW.date()))

    def test_contact_names_are_removed(self):
        self.assertNotIn("POPESCU", bc.scrub("Punct(e) de contact: ION POPESCU\nAlt rând"))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.pdf = mock.patch.object(bc, "pdf_to_text", return_value="Text proiect. " * 40)
        self.pdf.start()

    def tearDown(self):
        self.pdf.stop()
        self.tmp.cleanup()

    def client(self, hcl_status):
        return FakeClient({bc.HCL_URL: hcl_card("taxe", hcl_status) + hcl_card("puz", "Aprobat prin HCL"),
                           bc.TENDER_PAGES["licitatie"]: TENDER, bc.TENDER_PAGES["achizitie"]: ""})

    def raws(self):
        d = self.data / "articles" / "brasovcity_docs"
        return [json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.json")] if d.exists() else []

    def test_first_run_publishes_open_items_and_records_states(self):
        stats = bc.run(data_dir=self.data, client=self.client("În dezbatere publică"), now=NOW)
        self.assertEqual(stats["salvate"], 2)  # proiectul în dezbatere + licitația deschisă
        kinds = sorted(r["doc_type"] for r in self.raws())
        self.assertEqual(kinds, ["hcl", "licitatie"])
        hcl = next(r for r in self.raws() if r["doc_type"] == "hcl")
        self.assertEqual(hcl["source"], "Primăria Brașov")
        self.assertEqual(hcl["relevant_until"], "2026-12-05")
        self.assertIn("contact@pietepublice.ro", hcl["content"])
        lic = next(r for r in self.raws() if r["doc_type"] == "licitatie")
        self.assertNotIn("POPESCU", lic["content"])
        # al doilea apel: nimic nou
        self.assertEqual(bc.run(data_dir=self.data, client=self.client("În dezbatere publică"), now=NOW)["salvate"], 0)

    def test_status_change_becomes_decision_story(self):
        bc.run(data_dir=self.data, client=self.client("În dezbatere publică"), now=NOW)
        stats = bc.run(data_dir=self.data, client=self.client("Aprobat prin HCL"), now=NOW)
        self.assertEqual(stats["decizii"], 1)
        dec = next(r for r in self.raws() if r["doc_type"] == "hcl_decizie")
        self.assertTrue(dec["title"].startswith("Aprobat prin HCL:"))
        self.assertIn("nu precizează data ședinței", dec["content"])
        # o singură dată
        self.assertEqual(bc.run(data_dir=self.data, client=self.client("Aprobat prin HCL"), now=NOW)["decizii"], 0)

    def test_already_approved_on_first_run_is_not_announced(self):
        bc.run(data_dir=self.data, client=self.client("În dezbatere publică"), now=NOW)
        self.assertFalse(any("puz" in r["url"] for r in self.raws()))


class PipelineBitsTest(unittest.TestCase):
    def test_deadline_keeps_document_fresh(self):
        import run_pipeline as rp
        self.assertFalse(rp.is_stale({"date": "2026-10-01T00:00:00", "relevant_until": "2027-01-08"}, NOW))
        self.assertTrue(rp.is_stale({"date": "2026-11-26T00:00:00", "relevant_until": "2026-11-20"}, NOW))

    def test_institutional_contacts_allowed_only_for_official_sources(self):
        src = "Propunerile se trimit la contact@pietepublice.ro sau la 0268 405 000."
        art = {"title": "x", "content": "<p>Scrieți la contact@pietepublice.ro sau sunați la 0268 405 000.</p>",
               "excerpt": "", "url": "https://b.ro"}
        self.assertEqual(fc.deterministic(src, art, NOW, official=True)["erori"], [])
        self.assertEqual(len(fc.deterministic(src, art, NOW, official=False)["erori"]), 2)
        other = dict(art, content="<p>Sunați la 0722 999 888.</p>")
        tips = {e["tip"] for e in fc.deterministic(src, other, NOW, official=True)["erori"]}
        self.assertIn("date_personale_telefon", tips)  # un telefon care nu e în documentul oficial


if __name__ == "__main__":
    unittest.main()


class SpacedDecimalsTest(unittest.TestCase):
    def test_official_spaced_decimals_match(self):
        art = {"title": "x", "content": "<p>Are 9,16 mp.</p>", "excerpt": "", "url": "u"}
        self.assertEqual(fc.deterministic("suprafață de 9, 16 mp", art, NOW)["erori"], [])


class StoreTest(unittest.TestCase):
    def test_store_keeps_all_documents_and_status_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            mk = lambda st: FakeClient({bc.HCL_URL: hcl_card("taxe", st) + hcl_card("puz", "Aprobat prin HCL"),
                                        bc.TENDER_PAGES["licitatie"]: TENDER, bc.TENDER_PAGES["achizitie"]: ""})
            with mock.patch.object(bc, "pdf_to_text", return_value="Text proiect. " * 40):
                bc.run(data_dir=data, client=mk("În dezbatere publică"), now=NOW)
                store = json.loads(bc.store_path(data).read_text(encoding="utf-8"))
                self.assertEqual({i["kind"] for i in store["items"].values()}, {"hcl", "licitatie"})
                taxe = next(i for i in store["items"].values() if "taxe" in i["url"])
                self.assertIsNone(taxe["first_seen"])  # prima rulare: nu știm de când există
                self.assertEqual(taxe["deadline"], "2026-12-05")
                bc.run(data_dir=data, client=mk("Aprobat prin HCL"), now=NOW)
                taxe = next(i for i in json.loads(bc.store_path(data).read_text(encoding="utf-8"))["items"].values()
                            if "taxe" in i["url"])
                self.assertEqual(taxe["status_since"], NOW.date().isoformat())
                self.assertEqual(taxe["status_prev"], "În dezbatere publică")
                lic = next(i for i in json.loads(bc.store_path(data).read_text(encoding="utf-8"))["items"].values()
                           if i["kind"] == "licitatie")
                self.assertNotIn("POPESCU", lic["notes"])


class RedactTest(unittest.TestCase):
    def test_private_initiator_is_hidden_companies_stay(self):
        self.assertEqual(bc.redact_private("PUZ str Merilor FN, initiator NISTOR VIORICA RODICA"),
                         "PUZ str Merilor FN, initiator: persoană fizică")
        for keep in ("PUZ, inițiator SC MADEX S.R.L.", "nr 28 - inițiator Fundația HOSPICE Casa Speranței",
                     "având ca inițiator PREMS – TECHNOLOGICAL PRODUCTS S.A.", "beneficiari SC West Garden Braşov"):
            self.assertEqual(bc.redact_private(keep), keep)
        self.assertEqual(bc.redact_private("Ghidul solicitantului pentru finanțare"), "Ghidul solicitantului pentru finanțare")
