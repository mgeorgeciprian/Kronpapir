import json
from datetime import date

from sources import licitatii_bv as lb
from sources.licitatii import sites
from web import business


def _it(i, url, **kw):
    return dict({"id": i, "url": url, "title": f"Cerere de ofertă {i}", "authority": "PRIMARIA COMUNEI PREJMER",
                 "published": "2026-11-20", "topic": "achizitii"}, **kw)


def test_first_run_is_baseline_then_new_items_marked():
    store = {}
    assert lb.merge(store, [_it("a", "https://x/a")], "sites", "2026-11-20") == 0
    assert store["items"]["a"]["is_new"] is False
    assert lb.merge(store, [_it("a", "https://x/a"), _it("b", "https://x/b")], "sites", "2026-11-21") == 1
    assert store["items"]["b"]["is_new"] is True and store["items"]["a"]["last_seen"] == "2026-11-21"


def test_anaf_items_leaving_the_feed_and_old_site_items_are_archived():
    store, archive = {}, {}
    lb.merge(store, [_it("s", "https://x/s", published="2026-08-01")], "sites", "2026-08-01", archive)
    lb.merge(store, [_it("n1", "https://anaf/1"), _it("n2", "https://anaf/2")], "anaf", "2026-11-20", archive)
    lb.merge(store, [_it("n1", "https://anaf/1")], "anaf", "2026-11-21", archive)
    assert set(store["items"]) == {"s", "n1"}
    assert archive["items"]["n2"]["archived_at"] == "2026-11-21"
    lb.merge(store, [], "sites", "2026-11-21", archive)
    assert "s" not in store["items"]
    assert archive["items"]["s"]["archive_reason"] == "mai vechi de 30 de zile"


def test_site_item_stays_until_its_deadline_then_is_archived_and_not_readded():
    store, archive = {}, {}
    lb.merge(store, [], "sites", "2026-11-01", archive)  # prima rulare: baseline
    title = "Cerere de ofertă reparații școală, termen limită 30.12.2026"
    lb.merge(store, [_it("d", "https://x/d", title=title)], "sites", "2026-11-20", archive)
    assert store["items"]["d"]["deadline"] == "2026-12-30"
    lb.merge(store, [_it("d", "https://x/d", title=title)], "sites", "2026-12-28", archive)  # peste 30 de zile, dar în termen
    assert "d" in store["items"]
    lb.merge(store, [_it("d", "https://x/d", title=title)], "sites", "2026-12-31", archive)
    assert "d" not in store["items"] and archive["items"]["d"]["archive_reason"] == "termen expirat"
    lb.merge(store, [_it("d", "https://x/d", title=title)], "sites", "2027-01-04", archive)
    assert "d" not in store["items"]


def test_expiry_rules():
    from sources.licitatii.expiry import deadline_in_title, expires_on
    assert deadline_in_title("Anunț achiziție mobilier – termen de depunere a ofertelor: 05.12.2026") == "2026-12-05"
    assert deadline_in_title("Anunț achiziție mobilier 05.12.2026") is None
    assert expires_on({"source": "anaf", "published": "2026-11-01"}) is None
    assert expires_on({"source": "sites", "published": "2026-11-01"}) == "2026-12-01"
    assert expires_on({"source": "sites", "published": "2026-11-27", "date_guessed": True, "first_seen": "2026-11-10"}) == "2026-12-10"


def test_run_writes_store_and_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "fetch_sites", lambda today, known: ([], {}))
    monkeypatch.setattr(lb, "fetch_anaf", lambda: ([], {}))
    lb.write_store(lb.store_path(tmp_path), {"baseline": {"anaf": "2026-11-01"}, "items": {
        "n": _it("n", "https://anaf/n", source="anaf")}})
    lb.run(data_dir=tmp_path)
    assert lb.load_store(lb.store_path(tmp_path))["items"] == {}
    assert "n" in lb.load_archive(lb.archive_path(tmp_path))["items"]


def test_site_client_uses_kronpapir_agent_and_respects_robots():
    class Resp:
        encoding = "utf-8"
        def __init__(self, status, text): self.status_code, self.text, self.headers = status, text, {"Content-Type": "text/html"}
        def raise_for_status(self): pass
    class Session:
        headers = {}
        def __init__(self): self.calls = []
        def get(self, url, timeout=None):
            self.calls.append(url)
            return Resp(200, "User-agent: *\nDisallow: /privat/\n") if url.endswith("/robots.txt") else Resp(200, "<html></html>")
    sess = Session()
    c = sites.SitesClient(session=sess, sleep=lambda s: None)
    assert "KronPapirBot" in sess.headers["User-Agent"]
    assert c.fetch("https://primarie.ro/privat/anunturi") is None
    assert c.blocked == ["https://primarie.ro/privat/anunturi"]
    assert c.fetch("https://primarie.ro/anunturi") == "<html></html>"


def test_groups_and_place_names():
    store = {"items": {
        "a": _it("a", "https://x/a", source="sites", first_seen="2026-11-20"),
        "t": _it("t", "https://x/t", source="sites", topic="terenuri", authority="PRIMARIA COMUNEI TARLUNGENI"),
        "old": _it("old", "https://x/o", source="sites", published="2026-08-01"),
        "n": _it("n", "https://anaf/n", source="anaf", authority="ANAF – valorificare bunuri"),
        "bad": _it("bad", "javascript:alert(1)", source="sites"),
    }}
    g = business.licitatii_groups(store, today=date(2026, 11, 26))
    assert [i["id"] for i in g["achizitii"]] == ["a"]
    assert g["achizitii"][0]["place"] == "Prejmer"
    assert [i["id"] for i in g["terenuri"]] == ["t"] and [i["id"] for i in g["anaf"]] == ["n"]


def test_licitatii_page_renders(tmp_path):
    from web.app import app
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"updated": "2026-11-26T07:30:00", "items": {
        "a": _it("a", "https://x/a", source="sites", published=date.today().isoformat())}}), encoding="utf-8")
    app.config["LICITATII_STORE"] = str(path)
    try:
        r = app.test_client().get("/afaceri-brasov/licitatii")
        html = r.get_data(as_text=True)
        assert r.status_code == 200 and "Cerere de ofertă a" in html and "Prejmer" in html
        assert app.test_client().get("/afaceri-brasov").status_code == 200
    finally:
        app.config.pop("LICITATII_STORE")


def test_items_older_than_14_days_are_ignored_but_undated_ones_kept():
    store = {"baseline": {"sites": "2026-11-01"}, "items": {}}
    fresh = [_it("old", "https://x/o", published="2026-11-01"),
             _it("ok", "https://x/k", published="2026-11-20"),
             _it("undated", "https://x/u", published="2026-11-26", date_guessed=True)]
    assert lb.merge(store, fresh, "sites", "2026-11-26") == 2
    assert set(store["items"]) == {"ok", "undated"}


def test_undated_baseline_items_and_button_titles_are_hidden():
    from datetime import date
    from web.business import licitatii_groups, clean_title
    items = {
        "a": {"url": "https://x.ro/1", "title": "Zilele Cristianului 2021 – Detalii", "authority": "PRIMARIA COMUNEI CRISTIAN",
              "source": "sites", "published": "2026-11-27", "date_guessed": True, "is_new": False},
        "b": {"url": "https://x.ro/2", "title": "Cerere de ofertă – reparații parc", "authority": "PRIMARIA COMUNEI CRISTIAN",
              "source": "sites", "published": "2026-11-28", "date_guessed": True, "is_new": True},
        "c": {"url": "https://x.ro/3", "title": "Deschide de aici", "authority": "PRIMARIA COMUNEI BUDILA",
              "source": "sites", "published": "2026-11-20"},
        "d": {"url": "https://x.ro/4", "title": "ANUNT DE PARTICIPARE Servicii de paza", "authority": "PRIMARIA COMUNEI HARSENI",
              "source": "sites", "published": "2026-11-18"},
    }
    g = licitatii_groups({"items": items}, today=date(2026, 11, 28))
    assert [i["url"] for i in g["achizitii"]] == ["https://x.ro/2", "https://x.ro/4"]
    assert clean_title("ANUNT DE PARTICIPARE PAZA – Vezi") == "ANUNT DE PARTICIPARE PAZA"
    assert clean_title("Achizitii directe") is None


def test_map_has_the_58_uat_and_filter_by_locality(tmp_path):
    from web.app import app
    from web.business import load_map, _anaf_place
    uats = load_map()["uat"]
    assert len(uats) == 58 and {"brasov", "sercaia", "zarnesti"} <= {u["slug"] for u in uats}
    assert _anaf_place({"title": "Pasune 3500 MP", "description": "carte funciara Zarnesti, extravilan"}, uats)["slug"] == "zarnesti"
    assert _anaf_place({"title": "Loc de parcare Brasov- subsol", "description": ""}, uats)["slug"] == "brasov"
    assert _anaf_place({"title": "Apartament", "description": "situat in Cluj"}, uats) is None
    today = date.today().isoformat()
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"items": {
        "a": {"url": "https://x/a", "title": "Cerere de ofertă pază școală", "authority": "PRIMARIA COMUNEI SERCAIA",
              "source": "sites", "published": today},
        "b": {"url": "https://x/b", "title": "Anunț de participare deszăpezire", "authority": "PRIMARIA COMUNEI PREJMER",
              "source": "sites", "published": today}}}), encoding="utf-8")
    app.config["LICITATII_STORE"] = str(path)
    try:
        c = app.test_client()
        html = c.get("/afaceri-brasov/licitatii").get_data(as_text=True)
        assert 'data-loc="sercaia"' in html and "Șercaia (1)" in html and "noindex" not in html
        r = c.get("/afaceri-brasov/licitatii?localitate=sercaia")
        assert r.status_code == 301 and r.headers["Location"].endswith("/afaceri-brasov/licitatii/sercaia")
        html = c.get("/afaceri-brasov/licitatii/sercaia").get_data(as_text=True)
        assert '<li data-loc="prejmer" hidden>' in html and '<li data-loc="sercaia">' in html
        assert "Doar <span id=\"lic-filter-name\">Șercaia" in html
        assert "noindex, follow" in html  # un singur anunț: prea puțin pentru Google
        assert '<link rel="canonical" href="https://kronpapir.ro/afaceri-brasov/licitatii">' in html
        assert "Licitații și achiziții în Șercaia | KronPapir" in html and '"DataFeed"' in html
        assert c.get("/afaceri-brasov/licitatii/nu-exista").status_code == 404
    finally:
        app.config.pop("LICITATII_STORE")


def test_menu_category_titles_are_not_notices():
    from web.business import clean_title
    assert clean_title("Dezbateri Publice") is None
    assert clean_title("Anunțuri Vânzări Terenuri") is None
    assert clean_title("Ofertă de vânzare teren extravilan nr. 2679/2026")
    assert clean_title("Anunt licitatie str. Pietii, nr. 3, CF 109819")


def test_locality_page_with_three_notices_is_indexed_and_in_sitemap(tmp_path):
    from web.app import app
    today = date.today().isoformat()
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"updated": today + "T07:05:00", "items": {
        k: {"url": f"https://x/{k}", "title": f"Cerere de ofertă numărul {k} lucrări", "authority": "PRIMARIA COMUNEI PREJMER",
            "source": "sites", "published": today} for k in ("a", "b", "c")}}), encoding="utf-8")
    app.config["LICITATII_STORE"] = str(path)
    try:
        c = app.test_client()
        html = c.get("/afaceri-brasov/licitatii/prejmer").get_data(as_text=True)
        assert '<meta name="robots" content="index, follow">' in html
        assert '<link rel="canonical" href="https://kronpapir.ro/afaceri-brasov/licitatii/prejmer">' in html
        assert "3 anunțuri acum în Prejmer" in html
        from web import business
        with app.app_context():
            assert any(e["loc"].endswith("/licitatii/prejmer") for e in business.locality_sitemap_entries())
        assert "/afaceri-brasov/licitatii/prejmer" in c.get("/sitemap-pagini.xml").get_data(as_text=True)
    finally:
        app.config.pop("LICITATII_STORE")


def test_onrc_csv(tmp_path):
    from web.app import app
    (tmp_path / "history.json").write_text(json.dumps({"radieri": {
        "2026-10": {"counties": {"Brașov": 117}, "national": 3474, "source_url": "https://www.onrc.ro/x.xlsx"}}}), encoding="utf-8")
    app.config["ONRC_DIR"] = str(tmp_path)
    try:
        r = app.test_client().get("/afaceri-brasov/date-onrc-brasov.csv")
        assert r.status_code == 200 and r.mimetype == "text/csv"
        assert r.get_data(as_text=True).splitlines() == ["luna,indicator,brasov,romania,sursa",
                                                         "2026-10,radieri,117,3474,https://www.onrc.ro/x.xlsx"]
    finally:
        app.config.pop("ONRC_DIR")


def test_article_locality_link(tmp_path):
    from web.app import app
    from web import business
    today = date.today().isoformat()
    path = tmp_path / "store.json"
    items = {f"{t}{k}": {"url": f"https://x/{t}{k}", "title": f"Cerere de ofertă numărul {k} lucrări", "authority": a,
                         "source": "sites", "published": today}
             for t, a in (("p", "PRIMARIA COMUNEI PREJMER"), ("b", "PRIMARIA MUNICIPIULUI BRASOV")) for k in range(3)}
    path.write_text(json.dumps({"updated": today + "T07:06:00", "items": items}), encoding="utf-8")
    app.config["LICITATII_STORE"] = str(path)
    try:
        with app.app_context():
            link = business.locality_link({"category": "local", "title": "Drum nou la Prejmer", "content": "<p>Lucrări în Brașov și Prejmer</p>"})
            assert link["url"] == "/afaceri-brasov/licitatii/prejmer" and link["n"] == 3
            assert business.locality_link({"category": "local", "title": "Primăria Brașov anunță", "content": ""})["name"] == "Brașov"
            assert business.locality_link({"category": "local", "title": "Ședință", "content": "în Brașov"}) is None
            assert business.locality_link({"category": "sanatate", "title": "Prejmer", "content": ""}) is None
    finally:
        app.config.pop("LICITATII_STORE")


def test_archive_page_lists_expired_by_month_and_locality_shows_recent(tmp_path):
    from web.app import app
    store, arch = tmp_path / "store.json", tmp_path / "arhiva.json"
    store.write_text(json.dumps({"items": {}}), encoding="utf-8")
    items = {f"e{k}": {"url": f"https://x/e{k}", "title": f"Cerere de ofertă reparații drum {k}", "source": "sites",
                       "authority": "PRIMARIA COMUNEI PREJMER", "published": "2026-10-01", "archived_at": "2026-11-02",
                       "archive_reason": "mai vechi de 30 de zile"} for k in range(11)}
    items["btn"] = dict(items["e0"], title="Deschide de aici", url="https://x/btn")
    items["guess"] = dict(items["e0"], url="https://x/g", date_guessed=True, is_new=False, title="Cerere de ofertă veche arhivă")
    items["dl"] = dict(items["e0"], url="https://x/dl", title="Licitație teren Hărman", authority="PRIMARIA COMUNEI HARMAN",
                       topic="terenuri", deadline="2026-12-01", archived_at="2026-12-02")
    arch.write_text(json.dumps({"updated": "2026-12-03T07:05:00", "items": items}), encoding="utf-8")
    app.config.update(LICITATII_STORE=str(store), LICITATII_ARCHIVE=str(arch))
    try:
        c = app.test_client()
        r = c.get("/afaceri-brasov/licitatii/arhiva")
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "Decembrie 2026 (1)" in html and "Noiembrie 2026 (11)" in html
        assert html.index("Decembrie 2026") < html.index("Noiembrie 2026")
        assert "termen 01.12.2026" in html and "Prejmer: 11" in html
        assert "Deschide de aici" not in html and "veche arhivă" not in html
        assert '<meta name="robots" content="index, follow">' in html
        assert "/afaceri-brasov/licitatii/arhiva" in c.get("/sitemap-pagini.xml").get_data(as_text=True)
        loc = c.get("/afaceri-brasov/licitatii/harman").get_data(as_text=True)
        assert "Încheiate recent în Hărman" in loc and "Licitație teren Hărman" in loc
        assert "Încheiate recent" not in c.get("/afaceri-brasov/licitatii").get_data(as_text=True)
    finally:
        app.config.pop("LICITATII_STORE"); app.config.pop("LICITATII_ARCHIVE")


def test_small_archive_is_noindex_and_not_in_sitemap(tmp_path):
    from web.app import app
    arch = tmp_path / "arhiva.json"
    arch.write_text(json.dumps({"items": {}}), encoding="utf-8")
    app.config["LICITATII_ARCHIVE"] = str(arch)
    try:
        c = app.test_client()
        html = c.get("/afaceri-brasov/licitatii/arhiva").get_data(as_text=True)
        assert "noindex, follow" in html and "Arhiva se umple" in html
        assert "/licitatii/arhiva" not in c.get("/sitemap-pagini.xml").get_data(as_text=True)
    finally:
        app.config.pop("LICITATII_ARCHIVE")
