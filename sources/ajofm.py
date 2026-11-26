"""Locuri de muncă vacante din județul Brașov, din platforma publică ANOFM (mediere.anofm.ro).

Sursa: API-ul public folosit chiar de pagina https://mediere.anofm.ro/app/module/mediere/jobs
(`POST /api/entity/vw_public_job_posting`, filtru `county_id`). Fără LLM: date structurate.

Date personale: NU păstrăm numele, telefonul și emailul persoanei de contact (CLAUDE.md, regula 6).
Pagina fiecărei oferte trimite la anunțul de pe ANOFM, unde candidatul găsește contactul.

Rulare: python -m sources.ajofm [--dry-run] [--data-dir data]
"""
import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sources.http import FetchError, PoliteClient

log = logging.getLogger("sources.ajofm")

BASE_URL = "https://mediere.anofm.ro"
API_URL = f"{BASE_URL}/api/entity/vw_public_job_posting"
JOB_URL = f"{BASE_URL}/app/module/mediere/job/{{id}}"
SOURCE_NAME = "ANOFM / AJOFM Brașov"
SOURCE_HOME = f"{BASE_URL}/app/module/mediere/jobs"
COUNTY_ID_BRASOV = 9
PAGE_SIZE = 50
MAX_PAGES = 40            # plafon de siguranță: 2.000 de oferte
KEEP_INACTIVE_DAYS = 30   # cât păstrăm o ofertă dispărută (pagina răspunde 410)
MIN_RATIO_VS_PREVIOUS = 0.4  # sub 40% din numărul anterior: sursa probabil are o problemă
TZ = ZoneInfo("Europe/Bucharest")

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_NAME = "ajofm_brasov.json"

# Localitățile din județ, cu diacritice (sursa le dă cu majuscule, fără diacritice).
LOCALITIES = {
    "BRASOV": "Brașov", "FAGARAS": "Făgăraș", "SACELE": "Săcele", "CODLEA": "Codlea",
    "RASNOV": "Râșnov", "ZARNESTI": "Zărnești", "RUPEA": "Rupea", "VICTORIA": "Victoria",
    "GHIMBAV": "Ghimbav", "PREDEAL": "Predeal", "CRISTIAN": "Cristian", "SANPETRU": "Sânpetru",
    "HARMAN": "Hărman", "PREJMER": "Prejmer", "FELDIOARA": "Feldioara", "BOD": "Bod",
    "HALCHIU": "Hălchiu", "TARLUNGENI": "Tărlungeni", "VULCAN": "Vulcan", "BRAN": "Bran",
    "MOIECIU": "Moieciu", "SINCA": "Șinca", "SINCA NOUA": "Șinca Nouă", "VOILA": "Voila",
    "SERCAIA": "Șercaia", "MANDRA": "Mândra", "HOGHIZ": "Hoghiz", "APATA": "Apața",
    "AUGUSTIN": "Augustin", "BECLEAN": "Beclean", "BUNESTI": "Bunești", "CATA": "Cața",
    "CINCU": "Cincu", "COMANA": "Comana", "DUMBRAVITA": "Dumbrăvița", "FUNDATA": "Fundata",
    "HOMOROD": "Homorod", "JIBERT": "Jibert", "LISA": "Lisa", "MAIERUS": "Măieruș",
    "ORMENIS": "Ormeniș", "PARAU": "Părău", "POIANA MARULUI": "Poiana Mărului",
    "RACOS": "Racoș", "RECEA": "Recea", "SAMBATA DE SUS": "Sâmbăta de Sus",
    "SOARS": "Șoarș", "TELIU": "Teliu", "UCEA": "Ucea", "UNGRA": "Ungra",
    "VAMA BUZAULUI": "Vama Buzăului", "VISTEA": "Viștea", "BUDILA": "Budila",
    "CRIZBAV": "Crizbav", "HALMEAG": "Hălmeag",
    "POIANA BRASOV": "Poiana Brașov", "STUPINI": "Stupini", "DARSTE": "Dârste",
    "BARTOLOMEU": "Bartolomeu", "OHABA": "Ohaba", "DRAGUS": "Drăguș", "PERSANI": "Perșani",
    "TOHANU NOU": "Tohanu Nou", "TANTARI": "Țânțari", "MAGURA": "Măgura",
    "CARPINIS": "Cărpiniș", "LUNCA CALNICULUI": "Lunca Câlnicului", "SIRNEA": "Șirnea",
    "CINCSOR": "Cincșor", "MOIECIU DE SUS": "Moieciu de Sus", "MOIECIU DE JOS": "Moieciu de Jos",
}

# Ocupațiile vin cu majuscule și adesea fără diacritice. Corectăm doar cuvintele verificate aici;
# un cuvânt necunoscut rămâne cum e (nu ghicim diacritice).
OCCUPATION_WORDS = {
    "achizitii": "achiziții", "acoperisuri": "acoperișuri", "apa": "apă", "bucatar": "bucătar",
    "bucatarie": "bucătărie", "cai": "căi", "camerista": "cameristă", "captuseli": "căptușeli",
    "cercetator": "cercetător", "cladiri": "clădiri", "cladirilor": "clădirilor", "clienti": "clienți",
    "comanda": "comandă", "conditionare": "condiționare", "conducator": "conducător",
    "confectiilor": "confecțiilor", "constructii": "construcții", "curatenie": "curățenie",
    "descarcator": "descărcător", "determinari": "determinări", "economica": "economică",
    "electronica": "electronică", "executia": "execuția", "faianta": "faianță", "formatie": "formație",
    "functionar": "funcționar", "generala": "generală", "handicapati": "handicapați", "in": "în",
    "informatica": "informatică", "informatii": "informații", "instalatii": "instalații",
    "instalatiile": "instalațiile", "lacatus": "lăcătuș", "legator": "legător", "lucrator": "lucrător",
    "marfuri": "mărfuri", "masini": "mașini", "masinist": "mașinist", "mecanica": "mecanică",
    "menajera": "menajeră", "mentenanta": "mentenanță", "microelectronica": "microelectronică",
    "munitie": "muniție", "numerica": "numerică", "operatiuni": "operațiuni", "ospatar": "ospătar",
    "performantei": "performanței", "placi": "plăci", "platbanda": "platbandă", "poarta": "poartă",
    "prelucratoare": "prelucrătoare", "receptioner": "recepționer", "relatii": "relații",
    "reparatii": "reparații", "retele": "rețele", "roboti": "roboți", "sanitara": "sanitară",
    "sarcina": "sarcină", "sef": "șef", "si": "și", "silvicultura": "silvicultură",
    "sociala": "socială", "sofer": "șofer", "slefuitor": "șlefuitor", "spalator": "spălător",
    "spalatoreasa": "spălătoreasă", "spatii": "spații", "tabla": "tablă", "taierea": "tăierea",
    "telecomunicatii": "telecomunicații", "tura": "tură", "unitati": "unități",
    "utilitati": "utilități", "vânzari": "vânzări", "vânzator": "vânzător", "zidarie": "zidărie",
    "încarcator": "încărcător", "întretinere": "întreținere", "îngrijitoare": "îngrijitoare",
}
ACRONYMS = {"cnc", "it", "hr", "ssm", "psi", "tir", "cfr", "ue", "ctp", "ai"}

# Doar aceste câmpuri ajung pe disc. Tot ce nu e aici (contact_name, contact_phone, contact_email,
# apartament, scară, etaj) se aruncă la colectare.
_TEXT_FIELDS = {
    "occupation": "occupation",
    "cor_name": "cor_name",
    "employer_name": "employer_name",
    "employer_tax_code": "employer_cui",
    "job_domain_name": "domain",
    "contract_type_name": "contract_type",
    "work_type_name": "work_type",
    "work_regime_name": "work_regime",
    "education_level_name": "education",
    "professional_experience_name": "experience",
    "job_posting_target_name": "target",
    "job_offer_closing_name": "apply_method",
    "apprentice_qualification_name": "apprentice_qualification",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?<!\d)(\+?4?0?\s?[237]\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3})(?!\d)")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _salary(value):
    """Sub 500 lei e un substituent (ANOFM are oferte cu „1 leu”), nu un salariu: îl tratăm ca lipsă."""
    n = _number(value)
    return n if n and n >= 500 else None


def _int(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _date(value):
    """'2026-11-24' sau '2026-11-24 13:30:25' -> '2026-11-24'; altfel None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def nice_locality(raw):
    """'BRASOV' -> 'Brașov'; necunoscut -> forma cu inițiale mari (fără să inventăm diacritice)."""
    raw = _clean(raw)
    if not raw:
        return None
    key = raw.upper().replace("Ș", "S").replace("Ț", "T")
    key = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode()
    key = re.sub(r"\s+", " ", key).strip()
    if key in LOCALITIES:
        return LOCALITIES[key]
    raw = re.sub(r"^(MUNICIPIUL|ORAS|ORAȘ|COMUNA)\s+", "", raw, flags=re.I)
    if raw.upper() != key and raw:
        return nice_locality(raw)
    return " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in raw.split())


def nice_occupation(raw):
    """'OPERATOR LA MASINI-UNELTE CU COMANDA NUMERICA' -> 'Operator la mașini-unelte cu comandă numerică'."""
    raw = _clean(raw)
    if not raw:
        return None
    text = raw.lower() if raw.isupper() else raw

    def fix(m):
        w = m.group(0)
        low = w.lower()
        if low in ACRONYMS:
            return low.upper()
        if w == low:
            return OCCUPATION_WORDS.get(low, w)
        if w == low.capitalize() and low in OCCUPATION_WORDS:  # „Conducator” -> „Conducător”
            return OCCUPATION_WORDS[low].capitalize()
        return w

    text = re.sub(r"[^\W\d_]+", fix, text)
    return text[0].upper() + text[1:]


def parse_locality(path):
    """'Brașov > MUNICIPIUL BRASOV > BRASOV' -> ('Municipiul Brașov', 'Brașov')."""
    parts = [p.strip() for p in (path or "").split(">") if p.strip()]
    if not parts:
        return None, None
    locality = nice_locality(parts[-1])
    uat = None
    if len(parts) >= 2:
        m = re.match(r"(MUNICIPIUL|ORAS|ORAȘ|COMUNA)\s+(.+)", parts[1].upper())
        if m:
            kind = {"MUNICIPIUL": "Municipiul", "ORAS": "Orașul", "ORAȘ": "Orașul", "COMUNA": "Comuna"}[m.group(1)]
            uat = f"{kind} {nice_locality(m.group(2))}"
        else:
            uat = nice_locality(parts[1])
    return uat, locality


def scrub_description(text):
    """Textul angajatorului, fără HTML și fără date de contact (acestea rămân pe ANOFM)."""
    text = _clean(_TAG_RE.sub(" ", text or ""))
    if not text:
        return None
    text = _EMAIL_RE.sub("[contact pe ANOFM]", text)
    text = _PHONE_RE.sub("[contact pe ANOFM]", text)
    return text[:3000]


def slugify(text):
    text = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(slug) > 80:
        slug = slug[:81].rsplit("-", 1)[0]
    return slug or "oferta"


def normalize(row):
    """Un rând din API -> oferta noastră. Întoarce None dacă lipsesc câmpurile de bază."""
    job_id = _int(row.get("id"))
    occupation = _clean(row.get("occupation"))
    if not job_id or not occupation or row.get("county_id") not in (None, COUNTY_ID_BRASOV):
        return None
    job = {"id": job_id}
    for src, dst in _TEXT_FIELDS.items():
        job[dst] = _clean(row.get(src))
    job["title"] = nice_occupation(occupation)
    job["domain"] = nice_occupation(job["domain"])
    cor = re.match(r"\s*(\d{4,6})\b", row.get("cor_name") or "")
    job["cor_code"] = cor.group(1) if cor else None
    job["uat"], job["locality"] = parse_locality(row.get("address_locality_name"))
    street = " ".join(x for x in (_clean(row.get("address_street")), _clean(row.get("address_street_number"))) if x)
    job["street"] = street.title() if street else None
    job["salary_min"] = _salary(row.get("minimum_salary"))
    job["salary_max"] = _salary(row.get("maximum_salary"))
    if job["salary_min"] and job["salary_max"] and job["salary_max"] < job["salary_min"]:
        job["salary_max"] = None
    if not job["salary_min"]:
        job["salary_min"], job["salary_max"] = job["salary_max"], None
    job["salary_type"] = {"gross": "brut", "net": "net"}.get(row.get("salary_type"))
    job["positions"] = _int(row.get("open_positions"))
    job["eu_citizens"] = bool(row.get("offer_available_eu_citizens"))
    job["months"] = _int(row.get("number_of_months"))
    job["description"] = scrub_description(row.get("description"))
    job["date_posted"] = _date(row.get("created_at"))
    job["start_date"] = _date(row.get("job_start_date"))
    job["valid_through"] = _date(row.get("job_expiry_date"))
    job["source_url"] = JOB_URL.format(id=job_id)
    job["slug"] = f"{job_id}-{slugify(job['title'] + ' ' + (job['locality'] or ''))}"
    return job


def fetch_rows(client, county_id=COUNTY_ID_BRASOV):
    rows, total, page = [], None, 1
    while page <= MAX_PAGES:
        data = client.request_json(API_URL, {
            "county_id": county_id, "current": page, "rowCount": PAGE_SIZE,
            "sort": {"created_at": "desc"},
        })
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise FetchError("Răspuns neașteptat de la ANOFM (lipsește 'rows').")
        total = int(data.get("total") or 0)
        rows.extend(data["rows"])
        if not data["rows"] or len(rows) >= total:
            break
        page += 1
    return rows, total


def store_path(data_dir=None):
    return Path(data_dir or BASE_DIR / "data") / "jobs" / STORE_NAME


def load_store(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"jobs": {}}


def merge(previous, fresh_jobs, now):
    """Combină colectarea nouă cu cea veche: first_seen stabil, ofertele dispărute devin inactive."""
    now_s = now.isoformat(timespec="seconds")
    today = now.date().isoformat()
    old = previous.get("jobs", {})
    merged = {}
    for job in fresh_jobs:
        key = str(job["id"])
        prev = old.get(key, {})
        job["first_seen"] = prev.get("first_seen") or now_s
        job["last_seen"] = now_s
        expired = bool(job.get("valid_through") and job["valid_through"] < today)
        job["active"] = not expired
        job["inactive_since"] = (prev.get("inactive_since") or now_s) if expired else None
        merged[key] = job
    cutoff = (now - timedelta(days=KEEP_INACTIVE_DAYS)).isoformat(timespec="seconds")
    for key, prev in old.items():
        if key in merged:
            continue
        gone = dict(prev, active=False, inactive_since=prev.get("inactive_since") or now_s)
        if gone["inactive_since"] >= cutoff:
            merged[key] = gone
    return merged


def write_store(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def run(data_dir=None, client=None, dry_run=False, now=None):
    now = now or datetime.now(TZ)
    data_root = Path(data_dir or BASE_DIR / "data")
    client = client or PoliteClient(cache_dir=data_root / "cache" / "http", cache_ttl=1800)
    path = store_path(data_root)
    previous = load_store(path)
    prev_active = sum(1 for j in previous.get("jobs", {}).values() if j.get("active"))

    rows, total = fetch_rows(client)
    fresh = [j for j in (normalize(r) for r in rows) if j]
    if total and len(rows) < total:
        raise FetchError(f"Colectare incompletă: {len(rows)} din {total} oferte.")
    if prev_active and len(fresh) < prev_active * MIN_RATIO_VS_PREVIOUS:
        raise FetchError(
            f"Doar {len(fresh)} oferte față de {prev_active} data trecută; "
            "probabil o problemă la ANOFM. Păstrez datele vechi.")

    jobs = merge(previous, fresh, now)
    payload = {
        "source": SOURCE_NAME,
        "source_url": SOURCE_HOME,
        "fetched_at": now.isoformat(timespec="seconds"),
        "total_reported": total,
        "jobs": jobs,
    }
    stats = {
        "active": sum(1 for j in jobs.values() if j["active"]),
        "inactive": sum(1 for j in jobs.values() if not j["active"]),
        "new": sum(1 for j in fresh if str(j["id"]) not in previous.get("jobs", {})),
        "requests": client.requests_made,
    }
    if not dry_run:
        write_store(path, payload)
    return payload, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Colectează ofertele AJOFM Brașov de pe mediere.anofm.ro")
    parser.add_argument("--dry-run", action="store_true", help="nu scrie nimic pe disc")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        _, stats = run(data_dir=args.data_dir, dry_run=args.dry_run)
    except FetchError as e:
        log.error("Colectarea AJOFM a eșuat: %s", e)
        return 1
    log.info("AJOFM Brașov: %(active)d active, %(inactive)d inactive, %(new)d noi, %(requests)d cereri", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
