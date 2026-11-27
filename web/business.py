"""Afaceri în Brașov: hub cu firmele din județ (ONRC), licitații și achiziții, joburi și știri economice.

Datele ONRC vin din data/business/onrc/latest.json, scris de `python -m sources.onrc`.
Toate cifrele sunt cele din fișierele ONRC; calculăm doar variații procentuale și clasamente.
"""
import json
import re
import threading
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, current_app, render_template

from editorial.presentation import SITE_URL

HUB_PATH = "/afaceri-brasov"
COUNTY = "Brașov"
PEERS = ["Cluj", "Sibiu", "Timiș", "Prahova", "Mureș", "Covasna"]
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "business" / "onrc"
LICITATII_STORE = Path(__file__).resolve().parent.parent / "data" / "business" / "licitatii" / "store.json"
LICITATII_PATH = HUB_PATH + "/licitatii"
SHOW_DAYS = 30
MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
          "septembrie", "octombrie", "noiembrie", "decembrie"]
FLOWS = [  # indicatorii de flux, în ordinea afișării
    ("inmatriculari", "Firme și PFA înmatriculate", "înmatriculări"),
    ("radieri", "Firme radiate (închise definitiv)", "radieri"),
    ("dizolvari", "Firme dizolvate", "dizolvări"),
    ("suspendari", "Activități suspendate", "suspendări"),
    ("insolvente", "Firme intrate în insolvență", "insolvențe"),
]

bp = Blueprint("business", __name__)
_cache = {"key": None, "data": None}
_lic_cache = {"key": None, "data": None}
_lock = threading.Lock()


# ---------- calcule (folosite și de reports/onrc_report.py) ----------

def pct_change(cur, prev):
    """Variația procentuală, cu o zecimală; None dacă nu se poate calcula."""
    if cur is None or not prev:
        return None
    return round((cur - prev) * 100.0 / prev, 1)


def fmt_int(n):
    return "–" if n is None else f"{n:,}".replace(",", ".")


def fmt_pct(p, sign=True):
    if p is None:
        return "–"
    text = f"{abs(p):.1f}".replace(".", ",") + "%"
    if not sign:
        return text
    return ("+" if p > 0 else "−" if p < 0 else "") + text


def period_label(period_end):
    """'2026-10-31' -> ('ianuarie–octombrie 2026', 'octombrie 2026')."""
    d = date.fromisoformat(period_end)
    month = MONTHS[d.month - 1]
    ytd = f"ianuarie–{month} {d.year}" if d.month > 1 else f"ianuarie {d.year}"
    return ytd, f"{month} {d.year}"


def rank(stats, stat, county=COUNTY, field="ytd", exclude=("București",)):
    """Locul județului după `field` (1 = cel mai mare), dintre județele fără `exclude`."""
    counties = (stats.get(stat) or {}).get("counties") or {}
    values = [(name, v.get(field)) for name, v in counties.items()
              if v.get(field) is not None and name not in exclude]
    values.sort(key=lambda x: -x[1])
    for i, (name, _) in enumerate(values, 1):
        if name == county:
            return i, len(values)
    return None, len(values)


def indicators(payload, county=COUNTY):
    """Rândurile tabelului principal pentru un județ."""
    stats = payload.get("stats") or {}
    rows = []
    for key, label, short in FLOWS:
        v = ((stats.get(key) or {}).get("counties") or {}).get(county)
        if not v:
            continue
        nat = (stats.get(key) or {}).get("national") or {}
        rows.append({
            "key": key, "label": label, "short": short,
            "ytd": v.get("ytd"), "ytd_prev": v.get("ytd_prev"), "month": v.get("month"),
            "change": pct_change(v.get("ytd"), v.get("ytd_prev")),
            "national_change": pct_change(nat.get("ytd"), nat.get("ytd_prev")),
        })
    return rows


def active(payload, county=COUNTY):
    v = (((payload.get("stats") or {}).get("activi") or {}).get("counties") or {}).get(county)
    if not v:
        return None
    return dict(v, change=pct_change(v.get("total"), v.get("total_prev")),
                pf_change=pct_change(v.get("pf"), v.get("pf_prev")),
                pj_change=pct_change(v.get("pj"), v.get("pj_prev")))


def forms(payload, county=COUNTY):
    """SRL și PFA înmatriculate, anul acesta față de anul trecut."""
    v = (((payload.get("stats") or {}).get("inmatriculari") or {}).get("counties") or {}).get(county) or {}
    cur, prev = v.get("forms") or {}, v.get("forms_prev") or {}
    out = []
    for f, label in (("SRL", "SRL-uri"), ("PFA", "PFA-uri"), ("II", "întreprinderi individuale")):
        if f in cur:
            out.append({"form": f, "label": label, "ytd": cur.get(f), "ytd_prev": prev.get(f),
                        "change": pct_change(cur.get(f), prev.get(f))})
    return out


def peers(payload, names=None):
    """Comparația cu alte județe: variația înmatriculărilor și a insolvențelor."""
    stats = payload.get("stats") or {}
    out = []
    for name in [COUNTY, *(names or PEERS)]:
        reg = ((stats.get("inmatriculari") or {}).get("counties") or {}).get(name)
        ins = ((stats.get("insolvente") or {}).get("counties") or {}).get(name)
        act = ((stats.get("activi") or {}).get("counties") or {}).get(name)
        if not reg:
            continue
        out.append({"name": name, "reg": reg.get("ytd"), "reg_change": pct_change(reg.get("ytd"), reg.get("ytd_prev")),
                    "ins": (ins or {}).get("ytd"), "ins_change": pct_change((ins or {}).get("ytd"), (ins or {}).get("ytd_prev")),
                    "active": (act or {}).get("total")})
    return out


# ---------- date ----------

def data_dir():
    return Path(current_app.config.get("ONRC_DIR") or DEFAULT_DIR)


def load_latest(folder=None):
    path = Path(folder or data_dir()) / "latest.json"
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] != key:
            try:
                _cache.update(key=key, data=json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                _cache.update(key=key, data=None)
        return _cache["data"]


def load_licitatii(path=None):
    path = Path(path or current_app.config.get("LICITATII_STORE") or LICITATII_STORE)
    try:
        st = path.stat()
    except FileNotFoundError:
        return {"items": {}}
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _lic_cache["key"] != key:
            try:
                _lic_cache.update(key=key, data=json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                _lic_cache.update(key=key, data={"items": {}})
        return _lic_cache["data"]


# Numele localităților cu diacritice (config/primarii_brasov.yaml le are fără).
PLACE_NAMES = {
    "Brasov": "Brașov", "Bunesti": "Bunești", "Cata": "Cața", "Dragus": "Drăguș", "Dumbravita": "Dumbrăvița",
    "Fagaras": "Făgăraș", "Harman": "Hărman", "Harseni": "Hârseni", "Lisa": "Lisa", "Maierus": "Măieruș",
    "Mandra": "Mândra", "Ormenis": "Ormeniș", "Parau": "Părău", "Poiana Marului": "Poiana Mărului",
    "Racos": "Racoș", "Rasnov": "Râșnov", "Sacele": "Săcele", "Sambata De Sus": "Sâmbăta de Sus",
    "Sanpetru": "Sânpetru", "Sercaia": "Șercaia", "Sinca": "Șinca", "Sinca Noua": "Șinca Nouă",
    "Soars": "Șoarș", "Tarlungeni": "Tărlungeni", "Ticusu": "Ticușu", "Vama Buzaului": "Vama Buzăului",
    "Vistea": "Viștea", "Zarnesti": "Zărnești",
}


def _place(authority):
    """„PRIMARIA COMUNEI SERCAIA” -> „Șercaia”."""
    name = re.sub(r"^(PRIMARIA|UAT)\s+((COMUNEI|ORASULUI|MUNICIPIULUI|COMUNA|ORAS|MUNICIPIUL)\s+)?", "",
                  (authority or "").strip(), flags=re.I).title()
    return PLACE_NAMES.get(name, name)


# Textul linkului, nu titlul anunțului: nu spune cititorului ce se cumpără.
GENERIC_TITLES = re.compile(r"^(deschide( de aici)?|aici|vezi|detalii|citeste( mai mult)?|click|descarca|"
                            r"achizitii( directe| publice)?|anunt(uri)?|document)\W*$", re.I)
TITLE_TAIL = re.compile(r"\s*[–-]\s*(vezi|detalii|citește mai mult|citeste mai mult)\s*$", re.I)


def clean_title(title):
    """Titlul de afișat sau None dacă e doar textul unui buton."""
    t = TITLE_TAIL.sub("", (title or "").strip())
    plain = t.translate(str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaisstt" + "AAISSTT"))
    if len(t) < 12 or GENERIC_TITLES.match(plain):
        return None
    return t


def licitatii_groups(store, today=None, days=SHOW_DAYS):
    """Anunțurile afișate, pe grupe: achiziții ale primăriilor, terenuri, bunuri ANAF.

    Un anunț de pe site-ul unei primării apare doar dacă știm că e recent: are dată reală
    în ultimele `days` zile sau a apărut pe site după prima noastră vizită (is_new).
    Cele fără dată găsite la prima vizită pot fi din arhivă (ani vechi), deci nu le arătăm.
    """
    today = today or date.today()
    cut = (today - timedelta(days=days)).isoformat()
    groups = {"achizitii": [], "terenuri": [], "anaf": []}
    seen = set()
    for it in (store.get("items") or {}).values():
        if not str(it.get("url", "")).startswith(("https://", "http://")):
            continue
        title = clean_title(it.get("title"))
        if not title:
            continue
        when = it.get("published") or it.get("first_seen") or ""
        if it.get("source") == "anaf":
            groups["anaf"].append(dict(it, title=title, when=None))
            continue
        if it.get("date_guessed") and not it.get("is_new"):
            continue
        key = (it.get("authority"), title.lower())
        if when[:10] >= cut and key not in seen:
            seen.add(key)
            groups["terenuri" if it.get("topic") == "terenuri" else "achizitii"].append(
                dict(it, title=title, when=when, place=_place(it.get("authority"))))
    for g in groups.values():
        g.sort(key=lambda i: (i.get("when") or i.get("published") or ""), reverse=True)
    return groups


def breadcrumbs():
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Acasă", "item": SITE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": "Afaceri în Brașov", "item": SITE_URL + HUB_PATH},
    ]}


def dataset_jsonld(payload):
    ytd, _ = period_label(payload["period_end"])
    return {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"Firmele din județul Brașov: înmatriculări, radieri, insolvențe ({ytd})",
        "description": ("Indicatorii lunari ai Registrului Comerțului pentru județul Brașov: înmatriculări, "
                        "radieri, dizolvări, suspendări, insolvențe și profesioniști activi, comparați cu anul trecut."),
        "url": SITE_URL + HUB_PATH,
        "spatialCoverage": {"@type": "Place", "name": "Județul Brașov, România"},
        "temporalCoverage": f"{payload['period_end'][:4]}-01-01/{payload['period_end']}",
        "isBasedOn": "https://www.onrc.ro/index.php/ro/statistici",
        "creator": {"@type": "Organization", "name": "Oficiul Național al Registrului Comerțului",
                    "url": "https://www.onrc.ro"},
        "publisher": {"@type": "NewsMediaOrganization", "name": "KronPapir", "url": SITE_URL},
        "license": "https://www.onrc.ro/index.php/ro/statistici",
        "dateModified": payload.get("fetched_at"),
    }


# ---------- rută ----------

def _is_business(a):
    src = (a.get("source") or "").lower()
    return a.get("category", "").lower() == "economie" or "bizbra" in src


def _is_public_doc(a):
    return "brasovcity.ro" in (a.get("source_url") or a.get("url") or "") and a.get("source_type") == "date_oficiale"


@bp.route(HUB_PATH)
def hub():
    payload = load_latest()
    loader = current_app.config["KP_LOAD_ARTICLES"]
    articles = loader(all_types=True)
    articles = [a for a in articles if not a.get("duplicate_of") and not a.get("is_editorial")]
    docs = [a for a in articles if _is_public_doc(a)][:8]
    news = [a for a in articles if _is_business(a) and not _is_public_doc(a)][:8]
    reports = [a for a in articles if str(a.get("id", "")).startswith(("onrc-raport-", "ajofm-raport-"))][:6]
    jobs_count = positions = 0
    try:
        from web import jobs as jobs_web
        active_jobs = jobs_web.active_jobs()
        jobs_count, positions = len(active_jobs), sum(j.get("positions") or 0 for j in active_jobs)
    except Exception:  # pagina merge și fără joburi
        pass
    ctx = {"payload": payload, "docs": docs, "news": news, "reports": reports,
           "jobs_count": jobs_count, "positions": positions, "hub_path": HUB_PATH,
           "categories": current_app.config.get("KP_CATEGORIES", {}),
           "fmt_int": fmt_int, "fmt_pct": fmt_pct}
    jsonld = [breadcrumbs()]
    if payload:
        ytd, month = period_label(payload["period_end"])
        reg_rank = rank(payload["stats"], "inmatriculari")
        act_rank = rank(payload["stats"], "activi", field="total")
        ctx.update(ytd_label=ytd, month_label=month, rows=indicators(payload), active=active(payload),
                   forms=forms(payload), peers=peers(payload), reg_rank=reg_rank, act_rank=act_rank,
                   year=int(payload["period_end"][:4]))
        jsonld.append(dataset_jsonld(payload))
    ctx["jsonld"] = jsonld
    lic = licitatii_groups(load_licitatii())
    ctx["lic"] = {k: v[:6] for k, v in lic.items()}
    ctx["lic_counts"] = {k: len(v) for k, v in lic.items()}
    ctx["lic_path"] = LICITATII_PATH
    return render_template("business_hub.html", **ctx)


@bp.route(LICITATII_PATH)
def licitatii():
    store = load_licitatii()
    groups = licitatii_groups(store)
    crumbs = breadcrumbs()
    crumbs["itemListElement"].append({"@type": "ListItem", "position": 3, "name": "Licitații și achiziții",
                                      "item": SITE_URL + LICITATII_PATH})
    return render_template("licitatii.html", groups=groups, updated=store.get("updated"),
                           show_days=SHOW_DAYS, hub_path=HUB_PATH, lic_path=LICITATII_PATH, jsonld=[crumbs],
                           categories=current_app.config.get("KP_CATEGORIES", {}))


def sitemap_entry():
    payload = load_latest()
    return {"loc": SITE_URL + HUB_PATH, "lastmod": (payload or {}).get("fetched_at", "")[:10] or None}


def register(app, categories, load_articles):
    app.config.setdefault("KP_CATEGORIES", categories)
    app.config["KP_LOAD_ARTICLES"] = load_articles
    app.register_blueprint(bp)
