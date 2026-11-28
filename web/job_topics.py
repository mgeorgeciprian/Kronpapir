"""Paginile de căutare pentru joburi: „locuri de muncă Făgăraș”, „locuri de muncă fără experiență Brașov” etc.

Fiecare pagină e o listă filtrată din ofertele AJOFM active, cu un text scurt generat din cifre
(nimic inventat). O pagină intră în index și în sitemap doar dacă are cel puțin MIN_INDEX oferte;
sub prag rămâne accesibilă, dar cu noindex, ca Google să nu vadă pagini subțiri.
"""
import re
import unicodedata
from statistics import median

MIN_INDEX = 5


def _fold(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", _fold(name)).strip("-")


def _title_has(*words):
    rx = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(_fold(w)) for w in words) + r")")
    return lambda j: bool(rx.search(_fold(j.get("title") or j.get("occupation"))))


def _domain_in(*names):
    wanted = {_fold(n) for n in names}
    return lambda j: _fold(j.get("domain")) in wanted


def _any(*preds):
    return lambda j: any(p(j) for p in preds)


# slug, H1 (cuvântul cheie), denumirea scurtă în linkuri, filtrul
TOPICS = [
    ("fara-experienta", "Locuri de muncă fără experiență în Brașov", "Fără experiență",
     lambda j: _fold(j.get("experience")).startswith("fara experienta")),
    ("muncitor-necalificat", "Locuri de muncă pentru muncitori necalificați în Brașov", "Muncitor necalificat",
     _title_has("necalificat")),
    ("sofer", "Locuri de muncă pentru șoferi în Brașov", "Șofer",
     _title_has("șofer", "conducător auto", "curier", "livrator")),
    ("constructii", "Locuri de muncă în construcții în Brașov", "Construcții",
     _domain_in("Construcții / Instalații")),
    ("productie", "Locuri de muncă în producție și logistică în Brașov", "Producție și logistică",
     _domain_in("Producție / Logistică", "Productie mobila", "Fabricarea articolelor de imbracaminte")),
    ("turism-restaurante", "Locuri de muncă în turism și restaurante în Brașov", "Turism și restaurante",
     _domain_in("Turism / Alimentație", "Restaurante")),
    ("medical", "Locuri de muncă în sănătate și asistență socială în Brașov", "Sănătate și asistență socială",
     _domain_in("Medicină / Sănătate /Psihoterapie", "Asistenta socială")),
    ("paza", "Locuri de muncă în pază și protecție în Brașov", "Pază și protecție",
     _any(_domain_in("Armată / Pază/ Protecție", "Servicii de paza și protectie"), _title_has("agent de securitate", "paznic"))),
    ("vanzari", "Locuri de muncă în vânzări și comerț în Brașov", "Vânzări și comerț",
     _any(_domain_in("Comert", "Retail", "Vânzări"), _title_has("vânzător", "agent vânzări", "agent comercial"))),
    ("inginer", "Locuri de muncă pentru ingineri în Brașov", "Ingineri",
     _any(_domain_in("Inginerie"), _title_has("inginer"))),
    ("part-time", "Locuri de muncă part-time în Brașov", "Part-time",
     lambda j: "partial" in _fold(j.get("work_type"))),
]

# Slug-uri care nu pot fi localități: topicurile și „brasov” (municipiul ar concura cu pagina
# principală pentru „locuri de muncă Brașov”; filtrul ?loc=Brașov rămâne pe hub).
RESERVED = {t[0] for t in TOPICS} | {"brasov"}


def localities(jobs):
    """{slug: nume} pentru localitățile cu cel puțin o ofertă, fără municipiul Brașov."""
    out = {}
    for j in jobs:
        name = j.get("locality")
        if name:
            slug = slugify(name)
            if slug and slug not in RESERVED:
                out.setdefault(slug, name)
    return out


def resolve(slug, jobs):
    """(info, joburi) pentru un slug de pagină, sau (None, None) dacă nu există."""
    for t_slug, h1, short, pred in TOPICS:
        if slug == t_slug:
            return {"slug": slug, "kind": "topic", "h1": h1, "short": short,
                    "keyword": h1.replace("Locuri de muncă", "locuri de muncă", 1)}, [j for j in jobs if pred(j)]
    name = localities(jobs).get(slug)
    if name:
        h1 = f"Locuri de muncă în {name}"
        return {"slug": slug, "kind": "loc", "h1": h1, "short": name, "place": name,
                "keyword": f"locuri de muncă {name}"}, [j for j in jobs if j.get("locality") == name]
    return None, None


def all_pages(jobs):
    """Toate paginile cu cel puțin o ofertă: [(info, n_oferte)], topicurile întâi, apoi localitățile."""
    pages = []
    for t_slug, *_ in TOPICS:
        info, sel = resolve(t_slug, jobs)
        if sel:
            pages.append((info, len(sel)))
    locs = sorted(localities(jobs).items(), key=lambda kv: kv[1])
    for slug, _ in locs:
        info, sel = resolve(slug, jobs)
        if sel:
            pages.append((info, len(sel)))
    return pages


def indexable(n):
    return n >= MIN_INDEX


def summary(info, jobs):
    """Cifrele paginii, pentru introducere: oferte, posturi, salariu median, angajatori, localități."""
    from web.business_reports import _company
    positions = sum(j.get("positions") or 0 for j in jobs)
    brut = [j["salary_min"] for j in jobs if j.get("salary_min") and j.get("salary_type") == "brut"]
    employers, places = {}, {}
    for j in jobs:
        e = (j.get("employer_name") or "").strip()
        if e:
            employers[e] = employers.get(e, 0) + (j.get("positions") or 1)
        if j.get("locality"):
            places[j["locality"]] = places.get(j["locality"], 0) + 1
    top_emp = [_company(e) for e, _ in sorted(employers.items(), key=lambda kv: -kv[1])[:3]]
    top_places = [p for p, _ in sorted(places.items(), key=lambda kv: -kv[1])[:3]]
    no_exp = sum(1 for j in jobs if _fold(j.get("experience")).startswith("fara experienta"))
    return {
        "offers": len(jobs), "positions": positions,
        "median_brut": int(median(brut)) if len(brut) >= 3 else None, "n_brut": len(brut),
        "employers": top_emp, "places": top_places if info.get("kind") == "topic" else [],
        "no_experience": no_exp,
    }
