from datetime import date

from web import business_reports as rep
from web import charts


def test_plural_follows_romanian_de_rule():
    assert rep.plural(1, "teren", "terenuri") == "1 teren"
    assert rep.plural(3, "teren", "terenuri") == "3 terenuri"
    assert rep.plural(20, "teren", "terenuri") == "20 de terenuri"
    assert rep.plural(105, "teren", "terenuri") == "105 terenuri"
    assert rep.plural(238, "ofertă", "oferte") == "238 de oferte"


def test_series_keeps_only_real_months():
    hist = {"radieri": {"2026-09": {"counties": {"Brașov": 126}}, "2026-08": {"counties": {"Brașov": 148}},
                        "2026-07": {"counties": {"Cluj": 9}}}}
    assert rep.series(hist, "radieri") == [("2026-08", 148), ("2026-09", 126)]


def test_headline_ignores_small_counts():
    rows = [{"key": "inmatriculari", "label": "x", "change": -20.2, "ytd": 3481, "ytd_prev": 4362},
            {"key": "insolvente", "label": "y", "change": 37.4, "ytd": 169, "ytd_prev": 123},
            {"key": "suspendari", "label": "z", "change": 300.0, "ytd": 12, "ytd_prev": 3}]
    assert rep.headline(rows)["key"] == "insolvente"


def test_registrations_per_1000_ranks_and_keeps_own_county():
    stats = {"inmatriculari": {"counties": {n: {"ytd": v} for n, v in
                                            (("A", 100), ("B", 50), ("Brașov", 10), ("București", 999))}},
             "activi": {"counties": {n: {"total": 1000} for n in ("A", "B", "Brașov", "București")}}}
    r = rep.registrations_per_1000({"stats": stats}, top=2)
    assert [x["name"] for x in r["rows"]] == ["A", "B", "Brașov"] and r["mine"]["rank"] == 3 and r["of"] == 3


def test_jobs_report_keeps_brut_and_net_apart():
    jobs = [{"positions": 2, "domain": "IT", "locality": "Brașov", "employer_name": "ACME SRL",
             "salary_min": 5000, "salary_type": "brut", "experience": "Fără experiență - 0 ani", "date_posted": "2026-11-26"},
            {"positions": 1, "domain": "Altele", "locality": "Săcele", "employer_name": "ACME SRL",
             "salary_min": 3000, "salary_type": "net", "date_posted": "2026-10-01"},
            {"positions": 1, "domain": "IT", "locality": "Brașov", "salary_min": 4000, "salary_type": "brut"}]
    r = rep.jobs_report(jobs, today=date(2026, 11, 27))
    assert r["median_brut"] == 4500 and r["n_brut"] == 2 and r["median_net"] == 3000
    assert r["positions"] == 4 and r["no_experience"] == 1 and r["new_week"] == 1
    assert r["domains"][-1] == ("Altele", 1) and r["employers"][0] == ("Acme Srl", 3)


def test_charts_are_accessible_fixed_size_svg():
    svg = str(charts.monthly_bars([("2026-08", 148), ("2026-09", 126), ("2026-10", 117)], "Radieri", "desc"))
    assert svg.startswith('<svg class="kp-chart" viewBox="0 0 640 220" role="img" aria-label="Radieri"')
    assert "<title>Radieri</title><desc>desc</desc>" in svg and "oct 26" in svg and ">117<" in svg
    div = str(charts.diverging([("insolvențe", 37.4, 13.0), ("radieri", -5.1, -5.6)], "t", "d"))
    assert "▲ +37,4%" in div and "▼ −5,1%" in div
    assert str(charts.hbars([], "t", "d")) == ""
    assert "&lt;b&gt;" in str(charts.hbars([("<b>", 3, False)], "t", "d"))


def test_hub_renders_reports(tmp_path):
    import json
    from web.app import app
    onrc = tmp_path / "onrc"
    onrc.mkdir()
    counties = lambda v: {"Brașov": v, "Cluj": v}
    stats = {k: {"counties": {"Brașov": {"ytd": 300, "ytd_prev": 200, "month": 30},
                              "Cluj": {"ytd": 100, "ytd_prev": 100, "month": 10}},
                 "national": {"ytd": 1000, "ytd_prev": 900}} for k in ("inmatriculari", "radieri", "insolvente")}
    stats["activi"] = {"counties": {"Brașov": {"total": 1000, "total_prev": 900, "pf": 1, "pj": 2},
                                    "Cluj": {"total": 1000}}, "national": {}}
    (onrc / "latest.json").write_text(json.dumps({"period_end": "2026-10-31", "fetched_at": "2026-11-27T07:20:00",
                                                  "stats": stats}), encoding="utf-8")
    months = [f"2026-{m:02d}" for m in range(1, 11)]
    (onrc / "history.json").write_text(json.dumps({"inmatriculari": {m: {"counties": counties(10 + i)} for i, m in enumerate(months)}}),
                                       encoding="utf-8")
    app.config["ONRC_DIR"] = str(onrc)
    try:
        html = app.test_client().get("/afaceri-brasov").get_data(as_text=True)
        assert 'id="evolutie"' in html and "Înmatriculări pe lună" in html
        assert 'id="judete"' in html and "Firme noi la 1.000" in html
        assert "<title>Afaceri în Brașov, oct. 2026: firme și licitații | KronPapir</title>" in html
        assert '"distribution"' in html and "<h3>Insolvențe firme Brașov</h3>" in html
        assert '"variableMeasured"' in html and '"license"' not in html
        assert 'id="panel-rad"' not in html  # radieri fără istoric: graficul nu apare
    finally:
        app.config.pop("ONRC_DIR")


def test_onrc_history_accumulates_months(tmp_path):
    from sources import onrc
    p = lambda end, v: {"period_end": end, "source_url": "u", "national": {"month": 9, "total": 9},
                        "counties": {"Brașov": {"month": v, "total": v * 10}}}
    onrc.update_history(tmp_path, {"radieri": p("2026-09-30", 126), "activi": p("2026-09-30", 5)})
    h = onrc.update_history(tmp_path, {"radieri": p("2026-10-31", 117)})
    assert sorted(h["radieri"]) == ["2026-09", "2026-10"]
    assert h["radieri"]["2026-10"]["counties"]["Brașov"] == 117 and h["activi"]["2026-09"]["counties"]["Brașov"] == 50
    html = '<a href="/statistici/2025/martie/Radieri.xlsx">x</a><a href="/statistici/2026/ianuarie/Radieri.xls">y</a>'
    assert [f[:2] for f in onrc.list_files(html, "radieri")] == [(2025, 3), (2026, 1)]
