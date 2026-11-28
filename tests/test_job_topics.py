from web import job_topics as t

JOBS = [
    {"id": 1, "title": "Șofer autocamion", "locality": "Făgăraș", "domain": "Servicii transport / curierat",
     "experience": "Fără experiență - 0 ani", "work_type": "Cu normă întreagă", "positions": 2,
     "salary_min": 4500, "salary_type": "brut", "employer_name": "ALFA SRL"},
    {"id": 2, "title": "Muncitor necalificat la asamblarea pieselor", "locality": "Făgăraș",
     "domain": "Producție / Logistică", "experience": "Experiență puțină - mai puțin de 3 ani",
     "work_type": "Cu normă parțială", "positions": 1},
    {"id": 3, "title": "Inginer constructor", "locality": "Brașov", "domain": "Construcții / Instalații",
     "experience": "Experiență medie - între 3 și 5 ani", "positions": 1},
    {"id": 4, "title": "Ospătar", "locality": "Poiana Brașov", "domain": "Restaurante", "positions": 3},
]


def ids(slug):
    return [j["id"] for j in t.resolve(slug, JOBS)[1]]


def test_topics_match_expected_jobs():
    assert ids("sofer") == [1]
    assert ids("fara-experienta") == [1]
    assert ids("muncitor-necalificat") == [2]
    assert ids("part-time") == [2]
    assert ids("productie") == [2]
    assert ids("inginer") == [3]
    assert ids("constructii") == [3]
    assert ids("turism-restaurante") == [4]


def test_localities_slugged_and_brasov_reserved():
    assert t.slugify("Poiana Brașov") == "poiana-brasov"
    assert ids("fagaras") == [1, 2]
    assert ids("poiana-brasov") == [4]
    assert t.resolve("brasov", JOBS) == (None, None)
    assert t.resolve("necunoscut", JOBS) == (None, None)


def test_threshold_and_summary():
    assert not t.indexable(4) and t.indexable(5)
    info, sel = t.resolve("fagaras", JOBS)
    s = t.summary(info, sel)
    assert s["offers"] == 2 and s["positions"] == 3
    assert s["median_brut"] is None  # sub 3 salarii nu dăm mediană
    assert s["places"] == []  # pagina de localitate nu-și repetă localitatea
