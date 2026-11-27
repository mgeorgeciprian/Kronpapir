"""Afaceri în Brașov: hub cu firmele din județ (ONRC), licitații și achiziții, joburi și știri economice.

Datele ONRC vin din data/business/onrc/latest.json, scris de `python -m sources.onrc`.
Toate cifrele sunt cele din fișierele ONRC; calculăm doar variații procentuale și clasamente.
"""
import json
import re
import threading
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, redirect, render_template, request

from web import business_reports as rep
from web import charts

from editorial.presentation import SITE_URL

HUB_PATH = "/afaceri-brasov"
COUNTY = "Brașov"
PEERS = ["Cluj", "Sibiu", "Timiș", "Prahova", "Mureș", "Covasna"]
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "business" / "onrc"
LICITATII_STORE = Path(__file__).resolve().parent.parent / "data" / "business" / "licitatii" / "store.json"
LICITATII_PATH = HUB_PATH + "/licitatii"
MAP_FILE = Path(__file__).resolve().parent.parent / "data" / "geo" / "harta_brasov.json"
SHOW_DAYS = 30
INDEX_MIN_ITEMS = 3  # o pagină de localitate intră în Google doar cu cel puțin atâtea anunțuri active
CSV_PATH = HUB_PATH + "/date-onrc-brasov.csv"
PRIMARIA_PATH = HUB_PATH + "/primaria-brasov"
BRASOVCITY_STORE = Path(__file__).resolve().parent.parent / "data" / "brasovcity" / "store.json"
WAITING_DAYS = 180  # proiect în dezbatere cu termenul trecut: îl arătăm ca „așteaptă votul” cel mult atât
MONTHS_TITLE = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sep.", "oct.", "nov.", "dec."]
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
# Titluri de meniu sau de categorie (la plural, fără un obiect anume), nu anunțuri.
CATEGORY_TITLES = re.compile(r"^(anunturi|dezbateri|licitatii|achizitii|oferte|vanzari|concesionari|inchirieri)"
                             r"( (publice|de|si|vanzari|vanzare|terenuri|teren|achizitii|licitatii|publicitare|"
                             r"participare|ofertă|oferta|imobile|bunuri)){0,4}\W*$", re.I)
TITLE_TAIL = re.compile(r"\s*[–-]\s*(vezi|detalii|citește mai mult|citeste mai mult)\s*$", re.I)


def clean_title(title):
    """Titlul de afișat sau None dacă e doar textul unui buton."""
    t = TITLE_TAIL.sub("", (title or "").strip())
    plain = t.translate(str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaisstt" + "AAISSTT"))
    if len(t) < 12 or GENERIC_TITLES.match(plain) or CATEGORY_TITLES.match(plain):
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


def place_slug(name):
    """„Șercaia” / „SERCAIA” -> „sercaia” (aceeași cheie ca în data/geo/harta_brasov.json)."""
    t = unicodedata.normalize("NFKD", name or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


_map_cache = {}


def load_map(path=MAP_FILE):
    """Contururile celor 58 de UAT-uri (generate de tools/build_harta_brasov.py), cu numele cu diacritice."""
    if path not in _map_cache:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            data = {"width": 600, "height": 475, "uat": []}
        for u in data["uat"]:
            u["title"] = PLACE_NAMES.get(u["name"].title(), u["name"].title())
        _map_cache[path] = data
    return _map_cache[path]


def _anaf_place(item, uats):
    """Localitatea unui bun ANAF, din titlu și descriere. Alt UAT decât Brașov are prioritate:
    „Brasov” apare des doar ca județ. Fără nicio potrivire: None."""
    blob = " " + place_slug((item.get("title") or "") + " " + (item.get("description") or "")).replace("-", " ") + " "
    hits = [u for u in uats if " " + u["slug"].replace("-", " ") + " " in blob]
    hits.sort(key=lambda u: (u["slug"] == "brasov", -len(u["slug"])))
    return hits[0] if hits else None


def with_places(groups, uats):
    """Pune pe fiecare anunț `loc` (slug) și `place` (nume afișat), ca să-l putem filtra pe hartă."""
    by_slug = {u["slug"]: u for u in uats}
    for key, items in groups.items():
        for it in items:
            if key == "anaf":
                u = _anaf_place(it, uats)
            else:
                u = by_slug.get(place_slug(it.get("place")))
            it["loc"] = u["slug"] if u else None
            if u:
                it["place"] = u["title"]
    return groups


_bc_cache = {"key": None, "data": None}


def load_brasovcity(path=None):
    path = Path(path or current_app.config.get("BRASOVCITY_STORE") or BRASOVCITY_STORE)
    try:
        st = path.stat()
    except FileNotFoundError:
        return {"items": {}}
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _bc_cache["key"] != key:
            try:
                _bc_cache.update(key=key, data=json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                _bc_cache.update(key=key, data={"items": {}})
        return _bc_cache["data"]


_HCL_PREFIX = re.compile(r"^\s*PROIECT(UL)?\s+DE\s+HOT[ĂA]R[ÂA]RE\s*", re.I)


def clean_doc_title(title):
    """„PROIECT DE HOTĂRÂRE privind…” -> „Proiect de hotărâre privind…”."""
    from sources.brasovcity import redact_private  # și pentru store-uri scrise înainte de regulă
    t = redact_private(_HCL_PREFIX.sub("Proiect de hotărâre ", title or "").strip())
    return t[:1].upper() + t[1:]


_PUBLIC_FILE = re.compile(r"anun|proiect|phcl|referat|raport de specialitate|anex|regulament|caiet|ghid", re.I)


def public_files(files):
    """Doar documentele de procedură (anunț, proiect, referat, raport, anexe), nu și planurile PUZ,
    ale căror nume de fișier pot conține numele unei persoane fizice. Restul: pe brasovcity.ro."""
    from sources.brasovcity import redact_private
    out = []
    for f in files or []:
        if _PUBLIC_FILE.search(f.get("name") or "") and not re.search(r"plan|reglement|memoriu", f["name"], re.I):
            out.append(dict(f, name=redact_private(f["name"])))
    return out


def explanations_dir():
    return Path(current_app.config.get("BRASOVCITY_STORE") or BRASOVCITY_STORE).parent / "explicatii"


_exp_cache = {"key": None, "data": {}}


def load_explanations(folder=None):
    """Explicațiile HCL (ai/hcl_explainer.py), după id. Cache invalidat când se schimbă folderul."""
    folder = Path(folder or explanations_dir())
    if not folder.exists():
        return {}
    files = sorted(folder.glob("*.json"))
    key = (str(folder), tuple((f.name, f.stat().st_mtime_ns) for f in files))
    with _lock:
        if _exp_cache["key"] != key:
            data = {}
            for f in files:
                try:
                    data[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
            _exp_cache.update(key=key, data=data)
        return _exp_cache["data"]


def primaria_groups(store, today=None, explanations=None):
    """Documentele Primăriei Brașov pe grupe, pentru pagina dedicată și pentru hub.

    - hcl_open: proiecte în dezbatere publică, cu termen de propuneri neexpirat;
    - hcl_waiting: în dezbatere, termenul de propuneri a trecut (urmează votul), publicate recent;
    - hcl_decided: aprobate, respinse, retrase, expirate; cele mai noi întâi;
    - lic_open / lic_past: licitații și achiziții, după termenul de depunere (site-ul nu le închide singur).
    """
    today = (today or date.today()).isoformat()
    since = (date.fromisoformat(today) - timedelta(days=WAITING_DAYS)).isoformat()
    out = {k: [] for k in ("hcl_open", "hcl_waiting", "hcl_decided", "lic_open", "lic_past")}
    explanations = explanations or {}
    for doc_id, it in (store.get("items") or {}).items():
        d = dict(it, id=doc_id, title=clean_doc_title(it.get("title")), files=public_files(it.get("files")))
        d["n_files"] = it.get("n_files") or len(it.get("files") or [])
        exp = explanations.get(doc_id)
        if exp and exp.get("status") == "published":
            d["exp"] = exp
        dl, pub, status = d.get("deadline"), d.get("published") or "", (d.get("status") or "").lower()
        if dl and dl >= today:
            d["days_left"] = (date.fromisoformat(dl) - date.fromisoformat(today)).days
        if d["kind"] == "hcl":
            if "dezbatere" in status:
                if dl and dl >= today:
                    out["hcl_open"].append(d)
                elif pub >= since:
                    out["hcl_waiting"].append(d)
            else:
                out["hcl_decided"].append(d)
        elif dl and dl >= today and status != "expirat":
            out["lic_open"].append(d)
        else:
            out["lic_past"].append(d)
    out["hcl_open"].sort(key=lambda d: d["deadline"])
    out["lic_open"].sort(key=lambda d: d["deadline"])
    for k in ("hcl_waiting", "hcl_decided"):
        out[k].sort(key=lambda d: (d.get("status_since") or "", d.get("published") or ""), reverse=True)
    out["lic_past"].sort(key=lambda d: d.get("deadline") or d.get("published") or "", reverse=True)
    return out


def primaria_sidebar(limit=3):
    """Caseta de pe prima pagină: proiectele cu termen deschis, apoi ultimele explicate. Fără date: None."""
    try:
        g = primaria_groups(load_brasovcity(), explanations=load_explanations())
    except Exception:
        return None
    items = g["hcl_open"] + g["lic_open"]
    explained = [d for d in g["hcl_waiting"] + g["hcl_decided"] if d.get("exp")]
    items = (items + explained)[:limit]
    if not items:
        return None
    return {"docs": items, "path": PRIMARIA_PATH, "n_open": len(g["hcl_open"]), "n_lic": len(g["lic_open"])}


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
        "dateModified": payload.get("fetched_at"),
        "variableMeasured": [label for _, label, _ in FLOWS] + ["Profesioniști activi"],
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": SITE_URL + CSV_PATH}],
        "measurementTechnique": "Statistici lunare publicate de ONRC; variațiile sunt calculate de KronPapir.",
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
    news = [a for a in articles if _is_business(a) and not _is_public_doc(a)][:8]
    reports = [a for a in articles if str(a.get("id", "")).startswith(("onrc-raport-", "ajofm-raport-"))][:6]
    ctx = {"payload": payload, "pb": primaria_groups(load_brasovcity(), explanations=load_explanations()), "primaria_path": PRIMARIA_PATH, "news": news, "reports": reports,
           "hub_path": HUB_PATH,
           "categories": current_app.config.get("KP_CATEGORIES", {}),
           "fmt_int": fmt_int, "fmt_pct": fmt_pct, "hide_ticker": True}
    jsonld = [breadcrumbs()]
    if payload:
        ytd, month = period_label(payload["period_end"])
        reg_rank = rank(payload["stats"], "inmatriculari")
        act_rank = rank(payload["stats"], "activi", field="total")
        d = date.fromisoformat(payload["period_end"])
        ctx["title_period"] = f"{MONTHS_TITLE[d.month - 1]} {d.year}"
        ctx.update(ytd_label=ytd, month_label=month, rows=indicators(payload), active=active(payload),
                   forms=forms(payload), peers=peers(payload), reg_rank=reg_rank, act_rank=act_rank,
                   year=int(payload["period_end"][:4]))
        jsonld.append(dataset_jsonld(payload))
    ctx["jsonld"] = jsonld
    lic_store = load_licitatii()
    lic = with_places(licitatii_groups(lic_store), load_map()["uat"])
    ctx["lic"] = {k: v[:6] for k, v in lic.items()}
    ctx["lic_counts"] = {k: len(v) for k, v in lic.items()}
    ctx["lic_path"] = LICITATII_PATH
    ctx["lic_report"] = rep.licitatii_report(lic)
    ctx["localitati"] = sorted(load_map()["uat"], key=lambda u: u["slug"])
    ctx["lic_counts_by_loc"] = licitatii_counts(lic)
    ctx["plural"] = rep.plural
    ctx["de"] = rep.de
    ctx.update(build_reports(payload, ctx))
    updated = [d for d in ((payload or {}).get("fetched_at", "")[:10], (lic_store.get("updated") or "")[:10]) if d]
    ctx["updated"] = max(updated) if updated else None
    return render_template("business_hub.html", **ctx)


def build_reports(payload, ctx):
    """Graficele și cifrele-cheie ale hub-ului. Un grafic fără date suficiente nu apare deloc."""
    out = {"chart_reg": None, "chart_rad": None, "chart_vs": None, "chart_rank": None, "health": [], "sparks": {},
           "chart_forms": None,
           "headline": None, "rank1000": None, "hero": None, "insights": []}
    if payload:
        period = payload["period_end"][:7]
        hist = rep.load_history(data_dir())
        for key, stat, word in (("chart_reg", "inmatriculari", "înmatriculări"), ("chart_rad", "radieri", "radieri")):
            pts = rep.series(hist, stat)
            if len(pts) >= rep.MIN_SERIES and pts[-1][0] == period:
                best = max(pts, key=lambda p: p[1])
                desc = (f"{word.capitalize()} lunare în județul Brașov, {charts.month_label(pts[0][0])} – "
                        f"{charts.month_label(pts[-1][0])}. Ultima lună: {fmt_int(pts[-1][1])}; "
                        f"cea mai mare valoare: {fmt_int(best[1])} în {charts.month_label(best[0])}.")
                out[key] = {"svg": charts.monthly_bars(pts, f"{word.capitalize()} pe lună, județul Brașov", desc),
                            "points": pts, "desc": desc, "months": len(pts)}
        rows = ctx.get("rows") or []
        out["headline"] = rep.headline(rows)
        out["hero"] = rep.hero(rows)
        out["health"] = rep.health_index(payload)
        out["sparks"] = {stat: charts.sparkline(rep.series(hist, stat), f"{word.capitalize()} pe lună")
                         for stat, word in (("inmatriculari", "înmatriculări"), ("radieri", "radieri"),
                                            ("dizolvari", "dizolvări"), ("suspendari", "suspendări"))
                         if (rep.series(hist, stat) or [("", 0)])[-1][0] == period}
        frm = ctx.get("forms") or []
        if frm:
            yr = ctx["year"]
            out["chart_forms"] = charts.paired_hbars(
                [(f["label"][:1].upper() + f["label"][1:], f["ytd"], f["ytd_prev"]) for f in frm],
                f"Firme noi pe forme de organizare: {ctx['ytd_label']} față de {yr - 1}",
                "; ".join(f"{f['label']}: {fmt_int(f['ytd'])} față de {fmt_int(f['ytd_prev'])} ({fmt_pct(f['change'])})" for f in frm),
                series=(str(yr), str(yr - 1)))
        vs = [(r["short"] if r.get("short") else r["label"], r.get("change"), r.get("national_change")) for r in rows]
        if vs:
            out["chart_vs"] = charts.diverging(
                vs, f"Variația față de {ctx['year'] - 1}: Brașov și România",
                "; ".join(f"{l}: Brașov {fmt_pct(a)}, România {fmt_pct(b)}" for l, a, b in vs))
        r1000 = rep.registrations_per_1000(payload)
        if r1000["rows"]:
            out["rank1000"] = r1000
            items = [(f"{r['rank']}. {r['name']}", r["value"], r["name"] == COUNTY) for r in r1000["rows"]]
            mine = r1000["mine"]
            out["chart_rank"] = charts.hbars(
                items, "Firme noi la 1.000 de firme active, pe județe",
                (f"Brașovul e pe locul {mine['rank']} din {r1000['of']}, cu {str(mine['value']).replace('.', ',')} "
                 f"înmatriculări la 1.000 de profesioniști activi." if mine else ""),
                fmt=lambda v: f"{v:.1f}".replace(".", ","))
    out["insights"] = rep.insights(ctx.get("rows") or [], ctx.get("forms") or [], out["rank1000"])
    return out


def licitatii_counts(groups):
    counts = {}
    for items in groups.values():
        for it in items:
            if it.get("loc"):
                counts[it["loc"]] = counts.get(it["loc"], 0) + 1
    return counts


def datafeed_jsonld(groups, store, url, selected=""):
    """Feed-ul de anunțuri (schema.org DataFeed), cu titlul oficial și linkul fiecărui anunț."""
    items = [it for k in ("achizitii", "terenuri", "anaf") for it in groups.get(k, [])
             if not selected or it.get("loc") == selected]
    return {"@context": "https://schema.org", "@type": "DataFeed", "url": url,
            "name": "Licitații, achiziții și terenuri ale primăriilor din județul Brașov",
            "dateModified": store.get("updated"),
            "dataFeedElement": [{"@type": "DataFeedItem", "dateCreated": (it.get("published") or it.get("first_seen") or "")[:10] or None,
                                 "item": {"@type": "Thing", "name": it.get("title"), "url": it.get("url")}}
                                for it in items[:50]]}


@bp.route(LICITATII_PATH)
def licitatii():
    old = request.args.get("localitate", "").strip().lower()
    if old:  # adresa veche cu parametru -> pagina localității
        return redirect(f"{LICITATII_PATH}/{old}", code=301)
    return _licitatii_page("")


@bp.route(LICITATII_PATH + "/<slug>")
def licitatii_localitate(slug):
    return _licitatii_page(slug)


def _licitatii_page(selected):
    store = load_licitatii()
    harta = load_map()
    groups = with_places(licitatii_groups(store), harta["uat"])
    counts = licitatii_counts(groups)
    by_slug = {u["slug"]: u for u in harta["uat"]}
    if selected and selected not in by_slug:
        abort(404)
    name = by_slug[selected]["title"] if selected else ""
    url = SITE_URL + LICITATII_PATH + (f"/{selected}" if selected else "")
    crumbs = breadcrumbs()
    crumbs["itemListElement"].append({"@type": "ListItem", "position": 3, "name": "Licitații și achiziții",
                                      "item": SITE_URL + LICITATII_PATH})
    if selected:
        crumbs["itemListElement"].append({"@type": "ListItem", "position": 4, "name": name, "item": url})
    indexable = not selected or counts.get(selected, 0) >= INDEX_MIN_ITEMS
    return render_template("licitatii.html", groups=groups, updated=store.get("updated"),
                           show_days=SHOW_DAYS, hub_path=HUB_PATH, lic_path=LICITATII_PATH,
                           jsonld=[crumbs, datafeed_jsonld(groups, store, url, selected)],
                           harta=harta, counts=counts, selected=selected, selected_name=name,
                           indexable=indexable, page_url=url, n_selected=counts.get(selected, 0),
                           localitati=sorted(harta["uat"], key=lambda u: u["slug"]),
                           categories=current_app.config.get("KP_CATEGORIES", {}))


@bp.route(PRIMARIA_PATH)
def primaria():
    store = load_brasovcity()
    g = primaria_groups(store, explanations=load_explanations())
    url = SITE_URL + PRIMARIA_PATH
    crumbs = breadcrumbs()
    crumbs["itemListElement"].append({"@type": "ListItem", "position": 3, "name": "Primăria Brașov", "item": url})
    listed = g["hcl_open"] + g["lic_open"] + g["hcl_waiting"] + g["hcl_decided"][:20]
    itemlist = {"@context": "https://schema.org", "@type": "ItemList", "url": url,
                "name": "Proiecte de hotărâre, hotărâri și licitații ale Primăriei Brașov",
                "itemListElement": [{"@type": "ListItem", "position": i, "name": d["title"][:200], "url": d["url"]}
                                    for i, d in enumerate(listed, 1)]}
    by_year = {}
    for d in g["hcl_decided"]:
        by_year.setdefault((d.get("published") or "")[:4] or "fără dată", []).append(d)
    return render_template("primaria_brasov.html", g=g, by_year=sorted(by_year.items(), reverse=True),
                           updated=store.get("updated"), source=store.get("source"),
                           hub_path=HUB_PATH, page_path=PRIMARIA_PATH, jsonld=[crumbs, itemlist],
                           approved_year=sum(1 for d in g["hcl_decided"] if "aprobat" in (d.get("status") or "").lower()
                                             and (d.get("published") or "")[:4] == str(date.today().year)),
                           year=date.today().year,
                           categories=current_app.config.get("KP_CATEGORIES", {}))


@bp.route(CSV_PATH)
def onrc_csv():
    """Seria lunară ONRC pentru Brașov și România, ca CSV (sursa: fișierele ONRC)."""
    hist = rep.load_history(data_dir())
    lines = ["luna,indicator,brasov,romania,sursa"]
    for stat in ("inmatriculari", "radieri", "dizolvari", "suspendari", "insolvente", "activi"):
        for month, p in sorted((hist.get(stat) or {}).items()):
            v = p.get("counties", {}).get(COUNTY)
            if v is None:
                continue
            nat = p.get("national")
            lines.append(f"{month},{stat},{v},{'' if nat is None else nat},{p.get('source_url', '')}")
    return Response("\n".join(lines) + "\n", mimetype="text/csv",
                    headers={"Content-Disposition": "inline; filename=onrc-brasov.csv",
                             "Cache-Control": "public, max-age=3600"})


def locality_sitemap_entries():
    """Paginile de localitate cu destule anunțuri ca să merite indexate."""
    store = load_licitatii()
    harta = load_map()
    counts = licitatii_counts(with_places(licitatii_groups(store), harta["uat"]))
    day = (store.get("updated") or "")[:10] or None
    return [{"loc": f"{SITE_URL}{LICITATII_PATH}/{slug}", "lastmod": day}
            for slug, n in sorted(counts.items()) if n >= INDEX_MIN_ITEMS]


def sitemap_entry():
    payload = load_latest()
    return {"loc": SITE_URL + HUB_PATH, "lastmod": (payload or {}).get("fetched_at", "")[:10] or None}


_counts_cache = {"key": None, "counts": {}}
LINK_CATEGORIES = ("local", "economie")


def _indexable_counts():
    """{slug: nr. anunțuri} pentru localitățile cu pagină indexabilă; recalculat doar când se schimbă store-ul."""
    store = load_licitatii()
    key = store.get("updated")
    if _counts_cache["key"] != key:
        counts = licitatii_counts(with_places(licitatii_groups(store), load_map()["uat"]))
        _counts_cache.update(key=key, counts={k: v for k, v in counts.items() if v >= INDEX_MIN_ITEMS})
    return _counts_cache["counts"]


def locality_link(article):
    """Link spre licitațiile localității despre care e articolul (Local / Economie), sau None.

    Alegem o localitate pomenită în titlu sau în începutul textului. „Brașov” apare aproape peste tot,
    așa că îl folosim doar când nu e pomenită altă localitate și apare în titlu.
    """
    try:
        if (article.get("category") or "").lower() not in LINK_CATEGORIES:
            return None
        counts = _indexable_counts()
        if not counts:
            return None
        title = article.get("title") or ""
        body = re.sub(r"<[^>]+>", " ", article.get("content") or "")[:800]
        blob_t = " " + place_slug(title).replace("-", " ") + " "
        blob = blob_t + place_slug(body).replace("-", " ") + " "
        uats = {u["slug"]: u for u in load_map()["uat"]}
        hits = [s for s in counts if s != "brasov" and " " + s.replace("-", " ") + " " in blob]
        if not hits and "brasov" in counts and " brasov " in blob_t:
            hits = ["brasov"]
        if not hits:
            return None
        slug = max(hits, key=lambda s: (" " + s.replace("-", " ") + " " in blob_t, counts[s]))
        return {"name": uats[slug]["title"], "url": f"{LICITATII_PATH}/{slug}", "n": counts[slug]}
    except Exception:  # un link în plus nu are voie să strice pagina articolului
        return None


def register(app, categories, load_articles):
    app.jinja_env.globals["locality_link"] = locality_link
    app.config.setdefault("KP_CATEGORIES", categories)
    app.config["KP_LOAD_ARTICLES"] = load_articles
    app.register_blueprint(bp)
