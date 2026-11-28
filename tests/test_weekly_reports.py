from datetime import date

from reports import jobs_weekly as J
from reports import licitatii_weekly as W


def _job(i, day, **kw):
    j = {"id": i, "title": f"Ocupatia {i}", "employer_name": "ALFA CONSTRUCT SRL", "locality": "Făgăraș",
         "domain": "Construcții / Instalații", "salary_min": 4325.0 + i, "salary_type": "brut", "positions": 2,
         "experience": "Fără experiență", "date_posted": day, "valid_through": "2027-01-31", "active": True,
         "slug": f"{i}-ocupatia-{i}-fagaras"}
    j.update(kw)
    return j


def test_week_bounds_is_previous_monday_to_sunday():
    assert J.week_bounds(date(2026, 11, 30)) == (date(2026, 11, 23), date(2026, 11, 29))
    assert J.week_bounds(date(2026, 12, 2)) == (date(2026, 11, 23), date(2026, 11, 29))


def test_jobs_report_numbers_verified_and_private_names_dropped():
    jobs = {str(i): _job(i, "2026-11-2%d" % (3 + i % 5)) for i in range(12)}
    jobs["99"] = _job(99, "2026-11-25", employer_name="POPESCU ION")  # persoană fizică: nu apare în text
    jobs["old"] = _job(100, "2026-11-10")
    stats = J.compute({"jobs": jobs}, date(2026, 11, 23), date(2026, 11, 29), date(2026, 11, 30))
    assert stats["offers"] == 13
    art = J.render(stats, {"fagaras"})
    assert "POPESCU" not in art["content"]
    assert '/locuri-de-munca-brasov/fagaras' in art["content"]
    assert J.verify(art, stats) == []
    art["content"] += "<p>Un număr inventat: 98765.</p>"
    assert J.verify(art, stats) == ["98765"]


def test_jobs_report_title_and_span():
    assert J.fmt_span(date(2026, 11, 23), date(2026, 11, 29)) == "23 și 29 noiembrie 2026"
    assert J.fmt_span(date(2026, 11, 30), date(2026, 12, 6)) == "30 noiembrie și 6 decembrie 2026"


def _site(i, published, **kw):
    it = {"id": f"s{i}", "url": f"https://primaria.ro/a{i}.pdf", "title": f"Anunt achizitie lucrari {i}",
          "authority": "PRIMARIA COMUNEI SERCAIA", "topic": "achizitii", "source": "sites",
          "published": published, "first_seen": "2026-11-27", "date_guessed": False, "is_new": False}
    it.update(kw)
    return it


def test_tenders_new_excludes_undated_baseline_and_verifies():
    items = {f"s{i}": _site(i, "2026-11-26") for i in range(3)}
    items["old"] = _site(9, "2026-11-27", date_guessed=True, is_new=False)  # găsit la prima vizită, fără dată
    items["fresh"] = _site(10, "2026-11-30", date_guessed=True, is_new=True, first_seen="2026-11-30")
    c = W.collect({"items": items}, {"items": {}}, date(2026, 11, 30))
    titles = {it["title"] for it in c["new_sites"]}
    assert "Anunt achizitie lucrari 9" not in titles and "Anunt achizitie lucrari 10" in titles
    art, n = W.render(c, date(2026, 11, 30))
    assert n == 4
    assert W.verify(art, c) == []
    assert "(24–30 noiembrie)" in art["title"]


def test_tenders_too_few_items_not_published(tmp_path):
    import json
    (tmp_path / "business" / "licitatii").mkdir(parents=True)
    (tmp_path / "business" / "licitatii" / "store.json").write_text(json.dumps({"items": {}}))
    try:
        W.run(data_dir=tmp_path, today=date(2026, 11, 30), dry_run=True)
    except RuntimeError as e:
        assert "nu fac raportul" in str(e)
    else:
        raise AssertionError("trebuia să refuze")
