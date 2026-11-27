import json
from pathlib import Path

import pytest

from reports import onrc_report
from sources import onrc
from web import business


def _rows(header, sub, data):
    rows = {2: header, 3: sub}
    for i, r in enumerate(data, 4):
        rows[i] = r
    return rows


def test_parse_flow_sheet():
    header = {0: "Județ", 2: "Nr. total radieri în perioada 01.01.2026 - 31.10.2026",
              3: "Nr. total radieri în perioada 01.01.2025 - 31.10.2025", 4: "DINAMICA",
              5: "Nr. total radieri în perioada 01.10.2026 - 31.10.2026"}
    rows = {1: {0: "Radieri în perioada ..."}, 2: header,
            3: {0: "Braşov", 2: "2056", 3: "2166", 4: "-5.08 %", 5: "117"},
            4: {0: "Cluj", 2: "10", 3: "20", 5: "1"},
            5: {0: "Total", 2: "64655", 3: "68486", 5: "3474"}}
    end, counties, national = onrc.parse_county_sheet(rows, "radieri")
    assert end == "2026-10-31"
    assert counties["Brașov"] == {"ytd": 2056, "ytd_prev": 2166, "month": 117}
    assert national == {"ytd": 64655, "ytd_prev": 68486, "month": 3474}


def test_parse_registrations_with_forms():
    header = {0: "Județ", 2: "Nr. înmatriculări în perioada 01.01.2026 - 31.10.2026",
              5: "Nr. înmatriculări în perioada 01.01.2025 - 31.10.2025", 8: "Dinamica",
              9: "Nr. înmatriculări în perioada 01.10.2026 - 31.10.2026",
              11: "Nr. total înmatriculări în perioada 01.10.2026 - 31.10.2026"}
    sub = {2: "PFA", 3: "SRL", 4: "Total general", 5: "PFA", 6: "SRL", 7: "Total general", 9: "PFA", 10: "SRL"}
    rows = {2: header, 3: sub, 4: {0: "Braşov", 2: "1632", 3: "1725", 4: "3481", 5: "1434", 6: "2784",
                                   7: "4362", 8: "-20.20 %", 9: "100", 10: "91", 11: "198"}}
    end, counties, _ = onrc.parse_county_sheet(rows, "inmatriculari")
    bv = counties["Brașov"]
    assert (bv["ytd"], bv["ytd_prev"], bv["month"]) == (3481, 4362, 198)
    assert bv["forms"] == {"PFA": 1632, "SRL": 1725}
    assert bv["forms_prev"]["SRL"] == 2784


def test_parse_active_stock():
    header = {0: "Judet", 1: "Număr profesionişti activi la 31.10.2026", 3: "Număr profesionişti activi la 31.10.2026",
              4: "Număr profesionişti activi la 31.10.2025", 6: "Număr profesionişti activi la 31.10.2025", 7: "Dinamica"}
    sub = {1: "Persoane fizice (IF, II, PFA)", 2: "Persoane juridice", 4: "Persoane fizice (IF)", 5: "Persoane juridice"}
    rows = {2: header, 3: sub, 4: {0: "Braşov", 1: "14180", 2: "44176", 3: "58356", 4: "12793", 5: "43946", 6: "56739"}}
    _, counties, _ = onrc.parse_county_sheet(rows, "activi")
    assert counties["Brașov"] == {"pf": 14180, "pj": 44176, "total": 58356,
                                  "pf_prev": 12793, "pj_prev": 43946, "total_prev": 56739}


def test_find_latest_file():
    html = ('<a href="/statistici/2026/septembrie/Radieri.xls">x</a>'
            '<a href="/statistici/2026/octombrie/Radieri.xls">x</a>'
            '<a href="/statistici/2025/decembrie/Radieri.xls">x</a>'
            '<a href="/statistici/2026/noiembrie/Dizolvări.xls">x</a>')
    assert onrc.find_latest_file(html, "radieri") == (2026, 10, "/statistici/2026/octombrie/Radieri.xls")


def test_pct_and_format():
    assert business.pct_change(3481, 4362) == -20.2
    assert business.pct_change(5, 0) is None
    assert business.fmt_pct(-20.2) == "−20,2%"
    assert business.fmt_pct(37.4) == "+37,4%"
    assert business.fmt_int(58356) == "58.356"


def test_romanian_de():
    assert onrc_report.num(169, "firme") == "169 de firme"
    assert onrc_report.num(115, "firme") == "115 firme"
    assert onrc_report.num(12, "firme") == "12 firme"
    assert onrc_report.num(100, "firme") == "100 de firme"
    assert onrc_report.num(1425, "dizolvări") == "1.425 de dizolvări"


def _payload():
    c = lambda ytd, prev, m: {"ytd": ytd, "ytd_prev": prev, "month": m}
    counties = lambda bv, cj: {"Brașov": bv, "Cluj": cj, "București": c(9000, 9500, 900)}
    return {"period_end": "2026-10-31", "stats": {
        "inmatriculari": {"counties": counties(dict(c(3481, 4362, 198), forms={"SRL": 1725, "PFA": 1632},
                                                    forms_prev={"SRL": 2784, "PFA": 1434}), c(5270, 6170, 300)),
                          "national": c(107620, 126757, 6645)},
        "radieri": {"counties": counties(c(2056, 2166, 117), c(900, 950, 80)), "national": c(64655, 68486, 3474)},
        "insolvente": {"counties": counties(c(169, 123, 24), c(327, 354, 30)), "national": c(6008, 5318, 742)},
        "activi": {"counties": {"Brașov": {"pf": 14180, "pj": 44176, "total": 58356, "pf_prev": 12793, "pj_prev": 43946, "total_prev": 56739},
                                "Cluj": {"total": 96314, "total_prev": 90000}}, "national": {}},
    }}


def test_report_numbers_all_come_from_data():
    payload = _payload()
    article = onrc_report.render(payload)
    assert onrc_report.verify(article, payload) == []
    assert "insolvențe" in article["title"] and "37,4%" in article["title"]
    assert article["source_type"] == "date_oficiale"


def test_report_verify_catches_invented_number():
    payload = _payload()
    article = onrc_report.render(payload)
    article["content"] += "<p>Au fost 4.444 de firme noi în Făgăraș.</p>"
    assert onrc_report.verify(article, payload) == ["4.444"]


def test_rank_excludes_bucharest():
    assert business.rank(_payload()["stats"], "inmatriculari") == (2, 2)


def test_hub_renders(tmp_path):
    from web.app import app
    (tmp_path / "latest.json").write_text(json.dumps(dict(_payload(), fetched_at="2026-11-26T18:00:00")), encoding="utf-8")
    app.config["ONRC_DIR"] = str(tmp_path)
    try:
        r = app.test_client().get("/afaceri-brasov")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "3.481" in html and "+37,4%" in html and '"@type": "Dataset"' in html
    finally:
        app.config.pop("ONRC_DIR")


def test_primaria_groups_and_page(tmp_path):
    from datetime import date as _d
    store = {"updated": "2026-11-27T05:50:00", "source": "https://www.brasovcity.ro/x", "items": {
        "hcl-1": {"kind": "hcl", "title": "PROIECT DE HOTĂRÂRE privind taxele locale", "url": "https://www.brasovcity.ro/a",
                  "status": "În dezbatere publică", "published": "2026-11-20", "deadline": "2026-12-05", "files": [], "n_files": 0, "notes": "Propuneri la registratura@brasovcity.ro"},
        "hcl-2": {"kind": "hcl", "title": "PROIECTUL DE HOTĂRÂRE privind PUZ", "url": "https://www.brasovcity.ro/b",
                  "status": "În dezbatere publică", "published": "2026-11-01", "deadline": "2026-11-11", "files": [], "n_files": 0, "notes": ""},
        "hcl-3": {"kind": "hcl", "title": "Proiect de hotărâre privind bugetul", "url": "https://www.brasovcity.ro/c",
                  "status": "Aprobat prin HCL", "published": "2026-03-01", "deadline": None, "files": [], "n_files": 0, "notes": ""},
        "licitatie-1": {"kind": "licitatie", "title": "Licitația publică privind închirierea", "url": "https://www.brasovcity.ro/d",
                        "status": "deschis", "published": None, "deadline": "2027-01-08", "files": [], "n_files": 0, "notes": ""},
        "licitatie-2": {"kind": "licitatie", "title": "Licitație veche", "url": "https://www.brasovcity.ro/e",
                        "status": "deschis", "published": None, "deadline": "2026-06-29", "files": [], "n_files": 0, "notes": ""}}}
    g = business.primaria_groups(store, today=_d(2026, 11, 27))
    assert [d["url"][-1] for d in g["hcl_open"]] == ["a"] and g["hcl_open"][0]["days_left"] == 8
    assert g["hcl_open"][0]["title"].startswith("Proiect de hotărâre privind taxele")
    assert [d["url"][-1] for d in g["hcl_waiting"]] == ["b"]
    assert [d["url"][-1] for d in g["hcl_decided"]] == ["c"]
    assert [d["url"][-1] for d in g["lic_open"]] == ["d"] and [d["url"][-1] for d in g["lic_past"]] == ["e"]
    from web.app import app
    p = tmp_path / "store.json"
    p.write_text(json.dumps(store), encoding="utf-8")
    app.config["BRASOVCITY_STORE"] = str(p)
    try:
        html = app.test_client().get("/afaceri-brasov/primaria-brasov").get_data(as_text=True)
        assert "Hotărârile Consiliului Local Brașov" in html and "Licitația publică privind închirierea" in html
        assert '"@type": "ItemList"' in html and "index, follow" in html
        hub = app.test_client().get("/afaceri-brasov").get_data(as_text=True)
        assert "/afaceri-brasov/primaria-brasov" in hub and 'id="anaf"' in hub
    finally:
        app.config.pop("BRASOVCITY_STORE")
