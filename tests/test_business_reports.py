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
    assert r["domains"][-1] == ("Altele", 1) and r["employers"][0] == ("Acme SRL", 3)


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


def test_health_index_states_and_formula():
    stats = {"inmatriculari": {"counties": {"Brașov": {"ytd": 3481, "ytd_prev": 4362}}, "national": {"ytd": 107620, "ytd_prev": 126757}},
             "insolvente": {"counties": {"Brașov": {"ytd": 169, "ytd_prev": 123}}, "national": {"ytd": 6008, "ytd_prev": 5318}},
             "radieri": {"counties": {"Brașov": {"ytd": 2056, "ytd_prev": 2166}}, "national": {"ytd": 64655, "ytd_prev": 68486}}}
    h = {x["key"]: x for x in rep.health_index({"stats": stats})}
    assert (h["insolvente"]["value"], h["insolvente"]["prev"], h["insolvente"]["national"]) == (48.5, 28.2, 55.8)
    assert h["insolvente"]["state"] == "rau"  # +72% față de anul trecut
    assert h["radieri"]["value"] == 59.1 and h["radieri"]["state"] == "atentie"
    assert h["insolvente"]["formula"] == "169 insolvențe / 3481 înmatriculări × 1000"


def test_sparkline_and_paired_bars():
    sp = str(charts.sparkline([("2026-08", 259), ("2026-09", 211), ("2026-10", 198)], "Înmatriculări"))
    assert 'class="kp-spark"' in sp and "De la 259 în aug 26 la 198 în oct 26" in sp
    assert str(charts.sparkline([("2026-10", 1)], "x")) == ""
    pb = str(charts.paired_hbars([("SRL-uri", 1725, 2784)], "t", "d", series=("2026", "2025")))
    assert ">1.725<" in pb and ">2.784<" in pb


def test_hero_and_insights_from_onrc_rows():
    rows = [{"key": "inmatriculari", "ytd": 3481, "ytd_prev": 4362, "change": -20.2},
            {"key": "radieri", "ytd": 2056, "ytd_prev": 2166, "change": -5.1},
            {"key": "insolvente", "ytd": 169, "ytd_prev": 123, "change": 37.4, "national_change": 13.0}]
    h = rep.hero(rows)
    assert h["per10"] == 6 and h["closed_pct"] == 59 and h["net"] == 1425
    forms = [{"form": "SRL", "label": "SRL-uri", "ytd": 1725, "change": -38.0},
             {"form": "PFA", "label": "PFA-uri", "ytd": 1632, "change": 13.8}]
    ins = rep.insights(rows, forms, {"mine": {"rank": 6, "value": 59.2}, "of": 41})
    assert [i["key"] for i in ins] == ["insolvente", "forme", "loc"]
    assert ins[0]["value"] == "+37%" and "2,9 ori" in ins[0]["text"] and ins[0]["tone"] == "rau"
    assert ins[1]["value"] == "PFA +14%" and "1.725" in ins[1]["text"]
    assert rep.hero([]) is None


def test_insights_skip_small_or_missing():
    rows = [{"key": "insolvente", "ytd": 12, "ytd_prev": 10, "change": 20.0}]
    assert rep.insights(rows, [], None) == []
