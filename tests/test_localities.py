from web import localities as L

UATS = [{"slug": s, "title": t} for s, t in [
    ("sacele", "Săcele"), ("sinca", "Șinca"), ("sinca-noua", "Șinca Nouă"), ("cristian", "Cristian"),
    ("bod", "Bod"), ("recea", "Recea"), ("poiana-marului", "Poiana Mărului"), ("victoria", "Victoria")]]


def _m(title, content=""):
    L._patterns.clear()
    return L.mentions({"title": title, "content": content}, UATS)


def test_finds_name_without_diacritics_and_in_body():
    assert _m("Accident la Sacele", "")[0] == ["sacele"]
    assert _m("Concurs de angajare", "<p>Spitalul Municipal Săcele angajează.</p>")[1] == ["sacele"]


def test_longer_name_wins():
    t, _ = _m("Drum nou la Șinca Nouă")
    assert t == ["sinca-noua"]
    t, _ = _m("Școala din Șinca se renovează")
    assert t == ["sinca"]


def test_ambiguous_names_need_context():
    assert _m("Cristian Popescu a câștigat concursul") == ([], [])
    assert _m("Apă rece: vremea se răcește") == ([], [])
    assert _m("Victoria echipei de handbal") == ([], [])
    assert _m("Canalizare nouă în comuna Bod")[0] == ["bod"]
    assert _m("Incendiu la o fermă din Cristian")[0] == ["cristian"]
    assert _m("Spital nou la Victoria")[0] == ["victoria"]


def test_lowercase_word_is_not_a_place():
    assert _m("O zi recea de noiembrie") == ([], [])


def test_multiword_name():
    assert _m("Poiana Mărului, sat european de tineret")[0] == ["poiana-marului"]


def test_indexable_thresholds():
    assert L.indexable(10, 0, 0)
    assert not L.indexable(9, 0, 0)
    assert L.indexable(5, 5, 0)
    assert L.indexable(5, 0, L.MIN_TENDERS)
    assert not L.indexable(4, 50, 50)


def test_routes(tmp_path):
    from web.app import app
    c = app.test_client()
    r = c.get("/stiri-brasov")
    assert r.status_code == 301 and r.headers["Location"].endswith("/local")
    assert c.get("/stiri-nu-exista").status_code == 404
    r = c.get("/stiri-sacele")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<h1 class=\"section-title\">Știri Săcele</h1>" in html
    assert "CollectionPage" in html


def test_favicon_and_unknown_category():
    from web.app import app
    c = app.test_client()
    assert c.get("/favicon.ico").status_code == 200
    assert c.get("/categorie/nu-exista").status_code == 404
    html = c.get("/categorie/sport").get_data(as_text=True)
    assert "Sport Brașov" in html and html.count('name="description"') == 1
