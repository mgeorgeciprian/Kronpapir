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


def test_anaf_items_leaving_the_feed_are_dropped_and_old_site_items_expire():
    store = {}
    lb.merge(store, [_it("s", "https://x/s", published="2026-08-01")], "sites", "2026-08-01")
    lb.merge(store, [_it("n1", "https://anaf/1"), _it("n2", "https://anaf/2")], "anaf", "2026-11-20")
    lb.merge(store, [_it("n1", "https://anaf/1")], "anaf", "2026-11-21")
    assert set(store["items"]) == {"s", "n1"}
    lb.merge(store, [], "sites", "2026-11-21")
    assert "s" not in store["items"]


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
