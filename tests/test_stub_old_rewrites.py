"""Cioturile pentru rescrierile vechi: text scurt, link la sursă, backup, nimic altceva atins."""
import gzip
import json
from datetime import datetime

from editorial import stub_old_rewrites as so

NOW = datetime(2026, 11, 27, 16, 0)
LONG = "<p>" + " ".join(["Consiliul Județean a primit oferte."] * 80) + "</p>"


def old(**kw):
    a = {"id": "a1", "title": "23 oferte pentru drumuri", "url": "https://litera9.com/x", "source": "Litera9",
         "content": LONG, "type": "local",
         "meta_description": "Consiliul Județean Brașov a primit 23 de oferte pentru modernizarea a 53 km de drumuri județene. Investiție de 526 milioane lei cu finanțare europeană.",
         "excerpt": "Consiliul Județean Brașov a primit 23 de oferte..."}
    a.update(kw)
    return a


def test_stub_is_short_with_source_link():
    s = so.stub(old(), NOW)
    assert 'href="https://litera9.com/x"' in s["content"] and "Litera9" in s["content"]
    assert len(so._clean(s["content"]).split()) < 60
    assert s["format"] == "rezumat" and s["stubbed_at"].startswith("2026-11-27")
    assert s["title"] == "23 oferte pentru drumuri" and s["url"] == "https://litera9.com/x"


def test_lead_prefers_meta_and_keeps_whole_sentences():
    assert so.lead(old()).startswith("Consiliul Județean Brașov a primit 23 de oferte")
    assert so.lead(old()).endswith(".")


def test_lead_falls_back_and_strips_pe_scurt():
    a = old(meta_description="", excerpt="Pe scurtPolițiștii", content="<p>Pe scurt</p><p>Polițiștii brașoveni au încheiat Săptămâna JUPITER, o operațiune amplă.</p>")
    assert so.lead(a) == "Polițiștii brașoveni au încheiat Săptămâna JUPITER, o operațiune amplă."


def test_long_single_sentence_is_cut_at_word():
    a = old(meta_description=" ".join(["cuvânt"] * 100))
    assert so.lead(a).endswith("…") and len(so.lead(a).split()) == so.MAX_WORDS


def test_skips_duplicates_reviewed_own_and_already_done():
    assert so.needs_stub(old())
    assert not so.needs_stub(old(duplicate_of="b"))
    assert not so.needs_stub(old(reviewed_by="George", reviewed_at="2026-11-26"))
    assert not so.needs_stub(old(stubbed_at="2026-11-27"))
    assert not so.needs_stub(old(url="https://kronpapir.ro/x"))          # al nostru
    assert not so.needs_stub(old(is_editorial=True))                     # editorial: alt flux
    assert not so.needs_stub(old(source_type="date_oficiale"))


def test_run_dry_then_apply_with_backup_and_gz(tmp_path):
    proc, backups = tmp_path / "processed", tmp_path / "backups"
    proc.mkdir()
    (proc / "a1.json").write_text(json.dumps(old(), ensure_ascii=False), encoding="utf-8")
    with gzip.open(proc / "a2.json.gz", "wt", encoding="utf-8") as f:
        json.dump(old(id="a2"), f, ensure_ascii=False)
    (proc / "e.json").write_text(json.dumps(old(id="e", is_editorial=True)), encoding="utf-8")

    dry = so.run(folder=proc, backups=backups, now=NOW)
    assert dry["stub"] == 2 and not backups.exists()
    assert json.loads((proc / "a1.json").read_text(encoding="utf-8"))["content"] == LONG

    done = so.run(apply=True, folder=proc, backups=backups, now=NOW)
    assert done["stub"] == 2
    bdir = backups / "rescrieri-lungi-20261127-1600"
    assert json.loads((bdir / "a1.json").read_text(encoding="utf-8"))["content"] == LONG
    assert (bdir / "a2.json.gz").exists()
    with gzip.open(proc / "a2.json.gz", "rt", encoding="utf-8") as f:
        assert json.load(f)["format"] == "rezumat"
    assert json.loads((proc / "e.json").read_text(encoding="utf-8"))["content"] == LONG
    assert so.run(apply=True, folder=proc, backups=backups, now=NOW)["stub"] == 0  # a doua rulare: nimic


def test_drops_seo_questions_and_calls_to_action():
    a = old(meta_description="Un urs a intrat într-un hotel din Poiana Brașov, iar la 112 i s-a spus că nu e urgență. Cum ajungem aici și ce trebuie schimbat. Descoperă detaliile.")
    assert so.lead(a) == "Un urs a intrat într-un hotel din Poiana Brașov, iar la 112 i s-a spus că nu e urgență."


def test_closes_quotes_cut_by_old_bug():
    a = old(meta_description="Opera Brașov prezintă „Carmen", excerpt="Pe scurtOpera Brașov joacă „Carmen", content="<li>Opera Brașov joacă „Carmen</li>")
    assert so.lead(a) == "Opera Brașov joacă „Carmen”."


def test_utm_removed_from_link():
    s = so.stub(old(url="https://litera9.com/x/?utm_source=rss&utm_medium=rss"), NOW)
    assert 'href="https://litera9.com/x/"' in s["content"]
