"""Locuri de muncă Brașov: pagina hub, pagina fiecărei oferte și JobPosting (schema.org).

Datele vin din `data/jobs/ajofm_brasov.json`, scris de `python -m sources.ajofm`.
Nu adăugăm nimic ce nu e în sursă: câmpurile lipsă nu apar (nici pe pagină, nici în JSON-LD).
"""
import json
import math
import threading
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from editorial.presentation import SITE_NAME, SITE_URL
from web import job_topics as topics

TZ = ZoneInfo("Europe/Bucharest")
HUB_PATH = "/locuri-de-munca-brasov"
PER_PAGE = 30
STALE_AFTER = timedelta(hours=36)
DEFAULT_STORE = Path(__file__).resolve().parent.parent / "data" / "jobs" / "ajofm_brasov.json"

MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
          "septembrie", "octombrie", "noiembrie", "decembrie"]

bp = Blueprint("jobs", __name__)

_cache = {"key": None, "data": None}
_lock = threading.Lock()


# ---------- date ----------

def store_file():
    return Path(current_app.config.get("JOBS_STORE") or DEFAULT_STORE)


def load_store():
    """Citește fișierul o singură dată pe versiune (cheie: mtime + mărime)."""
    path = store_file()
    try:
        st = path.stat()
    except FileNotFoundError:
        return {"jobs": {}, "fetched_at": None}
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] != key:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                current_app.logger.error("Fișierul de joburi %s nu e JSON valid", path)
                data = {"jobs": {}, "fetched_at": None}
            _cache.update(key=key, data=data)
        return _cache["data"]


def is_active(job, today=None):
    today = today or datetime.now(TZ).date().isoformat()
    if not job.get("active"):
        return False
    return not (job.get("valid_through") and job["valid_through"] < today)


def active_jobs():
    today = datetime.now(TZ).date().isoformat()
    jobs = [j for j in load_store().get("jobs", {}).values() if is_active(j, today)]
    jobs.sort(key=lambda j: (j.get("date_posted") or "", j["id"]), reverse=True)
    return jobs


# ---------- prezentare ----------

def job_path(job):
    return f"{HUB_PATH}/{job['slug']}"


def job_url(job):
    return SITE_URL + job_path(job)


def fmt_date(iso):
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return None
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_lei(n):
    return f"{int(round(n)):,}".replace(",", ".")


def salary_text(job):
    lo, hi = job.get("salary_min"), job.get("salary_max")
    if not lo:
        return None
    text = f"{fmt_lei(lo)} lei" if not hi or hi == lo else f"{fmt_lei(lo)}–{fmt_lei(hi)} lei"
    return f"{text} {job['salary_type']}" if job.get("salary_type") else text


def place_text(job):
    loc = job.get("locality")
    uat = job.get("uat")
    if loc and uat and loc not in uat:
        return f"{loc} ({uat})"
    return loc or uat


def ro_count(n, one, many):
    """1 post, 5 posturi, 20 de posturi, 105 posturi, 120 de posturi (regula lui „de” în română)."""
    n = int(n or 0)
    if n == 1:
        return f"1 {one}"
    rest = n % 100
    de = "de " if n and (rest == 0 or rest >= 20) else ""
    return f"{n} {de}{many}"


def positions_text(job):
    n = job.get("positions")
    return ro_count(n, "post", "posturi") if n else None


def details(job):
    """Lista de detalii afișate, în ordinea în care contează pentru cititor. Doar ce există."""
    rows = [
        ("Angajator", job.get("employer_name")),
        ("Localitate", place_text(job)),
        ("Adresa", job.get("street")),
        ("Salariu", salary_text(job)),
        ("Posturi", positions_text(job)),
        ("Normă", job.get("work_type")),
        ("Contract", job.get("contract_type")),
        ("Durata", f"{job['months']} luni" if job.get("months") else None),
        ("Unde se lucrează", job.get("work_regime")),
        ("Studii", job.get("education")),
        ("Experiență", job.get("experience")),
        ("Pentru", job.get("target")),
        ("Calificare (ucenicie)", job.get("apprentice_qualification")),
        ("Selecția se face prin", job.get("apply_method")),
        ("Domeniu", job.get("domain")),
        ("Cod COR", job.get("cor_code")),
        ("Valabilă până la", fmt_date(job.get("valid_through"))),
        ("Publicată de angajator", fmt_date(job.get("date_posted"))),
        ("Deschisă cetățenilor UE", "Da" if job.get("eu_citizens") else None),
    ]
    return [(k, v) for k, v in rows if v]


def lead(job):
    """Prima frază: cine, ce, unde, cât. Construită doar din câmpurile sursei."""
    who = job.get("employer_name") or "Un angajator"
    title = job.get("title") or ""
    what = (title[0].lower() + title[1:]) if title else "personal"
    parts = [f"{who} angajează {what}"]
    if place_text(job):
        parts.append(f"în {place_text(job)}")
    sentence = " ".join(parts)
    if positions_text(job):
        sentence += f", {positions_text(job)}"
    if salary_text(job):
        sentence += f", cu un salariu de {salary_text(job)}"
    sentence += "."
    if job.get("valid_through"):
        sentence += f" Oferta e valabilă până la {fmt_date(job['valid_through'])}."
    return sentence


def meta_description(job):
    return lead(job)[:158]


def employment_types(job):
    types = []
    if job.get("work_type") == "Cu normă întreagă":
        types.append("FULL_TIME")
    elif job.get("work_type") and "parțial" in job["work_type"]:
        types.append("PART_TIME")
    if job.get("contract_type") == "Cu durată determinată":
        types.append("TEMPORARY")
    return types


def description_html(job):
    parts = [f"<p>{escape(lead(job))}</p>"]
    if job.get("description"):
        parts.append(f"<p>{escape(job['description'])}</p>")
    items = "".join(f"<li>{escape(k)}: {escape(str(v))}</li>" for k, v in details(job))
    parts.append(f"<ul>{items}</ul>")
    parts.append(f"<p>Sursa: ANOFM, oferta nr. {job['id']}: {escape(job['source_url'])}</p>")
    return "".join(parts)


def _end_of_day(iso):
    d = date.fromisoformat(iso)
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TZ).isoformat()


def jobposting_jsonld(job):
    """JobPosting după ghidul Google: fără câmpuri inventate; ce lipsește din sursă nu apare."""
    address = {"@type": "PostalAddress", "addressRegion": "Brașov", "addressCountry": "RO"}
    if job.get("locality"):
        address["addressLocality"] = job["locality"]
    if job.get("street"):
        address["streetAddress"] = job["street"]
    org = {"@type": "Organization", "name": job.get("employer_name") or "Angajator nespecificat"}
    if job.get("employer_cui"):
        org["taxID"] = job["employer_cui"]
    data = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": job["title"],
        "description": description_html(job),
        "identifier": {"@type": "PropertyValue", "name": "ANOFM", "value": str(job["id"])},
        "datePosted": job.get("date_posted") or (job.get("first_seen") or "")[:10],
        "hiringOrganization": org,
        "jobLocation": {"@type": "Place", "address": address},
        "directApply": False,
        "url": job_url(job),
        "inLanguage": "ro-RO",
    }
    if job.get("valid_through"):
        data["validThrough"] = _end_of_day(job["valid_through"])
    types = employment_types(job)
    if types:
        data["employmentType"] = types if len(types) > 1 else types[0]
    if job.get("work_regime") == "Telemuncă":
        data["jobLocationType"] = "TELECOMMUTE"
        data["applicantLocationRequirements"] = {"@type": "Country", "name": "România"}
    if job.get("salary_min"):
        value = {"@type": "QuantitativeValue", "unitText": "MONTH"}
        if job.get("salary_max") and job["salary_max"] != job["salary_min"]:
            value.update(minValue=job["salary_min"], maxValue=job["salary_max"])
        else:
            value["value"] = job["salary_min"]
        data["baseSalary"] = {"@type": "MonetaryAmount", "currency": "RON", "value": value}
    if job.get("positions"):
        data["totalJobOpenings"] = job["positions"]
    if job.get("domain"):
        data["industry"] = job["domain"]
    if job.get("cor_name"):
        data["occupationalCategory"] = job["cor_name"]
    if job.get("education"):
        data["educationRequirements"] = job["education"]
    if job.get("experience"):
        data["experienceRequirements"] = job["experience"]
    return data


def breadcrumbs(job=None, landing=None):
    items = [
        {"@type": "ListItem", "position": 1, "name": "Acasă", "item": f"{SITE_URL}/"},
        {"@type": "ListItem", "position": 2, "name": "Locuri de muncă Brașov", "item": SITE_URL + HUB_PATH},
    ]
    if job:
        items.append({"@type": "ListItem", "position": 3, "name": job["title"], "item": job_url(job)})
    elif landing:
        items.append({"@type": "ListItem", "position": 3, "name": landing["h1"],
                      "item": f"{SITE_URL}{HUB_PATH}/{landing['slug']}"})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def freshness(store):
    """('26 noiembrie 2026, 13:58', învechit?) pentru „Actualizat la”."""
    raw = store.get("fetched_at")
    if not raw:
        return None, True
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None, True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=TZ)
    ts = ts.astimezone(TZ)
    stale = datetime.now(TZ) - ts > STALE_AFTER
    return f"{fmt_date(ts.date().isoformat())}, {ts:%H:%M}", stale


def facet(jobs, field, limit=None):
    counts = {}
    for j in jobs:
        if j.get(field):
            counts[j[field]] = counts.get(j[field], 0) + 1
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:limit] if limit else items


def sitemap_entries():
    """Pentru sitemap.xml: hub-ul și ofertele active."""
    store = load_store()
    jobs = active_jobs()
    lastmod = (store.get("fetched_at") or datetime.now(TZ).isoformat())[:10]
    entries = [{"loc": SITE_URL + HUB_PATH, "lastmod": lastmod, "changefreq": "daily", "priority": "0.9"}]
    for info, n in topics.all_pages(jobs):
        if topics.indexable(n):
            entries.append({"loc": f"{SITE_URL}{HUB_PATH}/{info['slug']}", "lastmod": lastmod,
                            "changefreq": "daily", "priority": "0.8"})
    for j in jobs:
        entries.append({"loc": job_url(j), "lastmod": (j.get("date_posted") or lastmod)[:10],
                        "changefreq": "weekly", "priority": "0.6"})
    return entries


# ---------- rute ----------

def _context():
    cats = current_app.config.get("KP_CATEGORIES", {})
    return {"categories": cats, "hub_path": HUB_PATH}


def market(all_jobs):
    """Piața muncii din ofertele active: cifre-cheie și trei grafice (domenii, localități, angajatori)."""
    from web import business_reports as rep, charts
    if not all_jobs:
        return None, {}
    jr = rep.jobs_report(all_jobs)
    out = {}
    for key, title in (("domains", "Posturi pe domenii"), ("places", "Posturi pe localități"),
                       ("employers", "Angajatorii cu cele mai multe posturi")):
        items = [(name if len(name) <= 21 else name[:20].rstrip() + "…", n, False) for name, n in jr[key]]
        out[key] = charts.hbars(items, title + " (AJOFM Brașov)",
                                "; ".join(f"{name}: {n}" for name, n in jr[key]), width=460, label_w=175)
    return jr, out


@bp.route(HUB_PATH)
def hub():
    store = load_store()
    all_jobs = active_jobs()
    loc = (request.args.get("loc") or "").strip()
    dom = (request.args.get("domeniu") or "").strip()
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "recente")
    only_salary = request.args.get("salariu") == "1"
    page = max(1, request.args.get("page", 1, type=int) or 1)

    jobs = all_jobs
    if loc:
        jobs = [j for j in jobs if j.get("locality") == loc]
    if dom:
        jobs = [j for j in jobs if j.get("domain") == dom]
    if q:
        needle = q.lower()
        jobs = [j for j in jobs if needle in " ".join(
            str(j.get(k) or "") for k in ("title", "employer_name", "domain", "description")).lower()]
    if only_salary:
        jobs = [j for j in jobs if j.get("salary_min")]
    if sort == "salariu":
        jobs = sorted(jobs, key=lambda j: (j.get("salary_max") or j.get("salary_min") or 0), reverse=True)

    total = len(jobs)
    total_pages = max(1, math.ceil(total / PER_PAGE))
    if page > total_pages:
        page = total_pages
    shown = jobs[(page - 1) * PER_PAGE: page * PER_PAGE]
    updated, stale = freshness(store)
    filtered = bool(loc or dom or q or only_salary or sort != "recente")
    # Graficele apar doar pe prima pagină nefiltrată; cine caută un job vede întâi lista.
    jobs_rep, chart_jobs = market(all_jobs) if (page == 1 and not filtered) else (None, {})
    pages = topics.all_pages(all_jobs)

    def page_url(p):
        args = {k: v for k, v in request.args.items() if k != "page"}
        if p > 1:
            args["page"] = p
        return url_for("jobs.hub", **args)

    return render_template(
        "jobs_hub.html",
        jobs=shown, total=total, total_all=len(all_jobs),
        positions_all=sum(j.get("positions") or 0 for j in all_jobs),
        with_salary=sum(1 for j in all_jobs if j.get("salary_min")),
        localities=facet(all_jobs, "locality"), domains=facet(all_jobs, "domain"),
        loc=loc, dom=dom, q=q, sort=sort, only_salary=only_salary,
        page=page, total_pages=total_pages, page_url=page_url,
        updated=updated, stale=stale, filtered=filtered,
        jobs_rep=jobs_rep, chart_jobs=chart_jobs,
        searches=[(i, n) for i, n in pages if i["kind"] == "topic" and topics.indexable(n)],
        loc_pages={i["place"]: i["slug"] for i, n in pages if i["kind"] == "loc" and topics.indexable(n)},
        source_url=store.get("source_url"),
        breadcrumbs=breadcrumbs(),
        **_context(),
    )


@bp.route(f"{HUB_PATH}/<slug>")
def detail(slug):
    head = slug.split("-", 1)[0]
    if not head.isdigit():
        return landing(slug)
    job = load_store().get("jobs", {}).get(head)
    if not job:
        abort(404)
    if slug != job["slug"]:
        return redirect(job_path(job), code=301)
    active = is_active(job)
    related = []
    if active:
        pool = [j for j in active_jobs() if j["id"] != job["id"]]
        related = [j for j in pool if j.get("domain") and j.get("domain") == job.get("domain")][:5]
        if len(related) < 5:
            related += [j for j in pool if j.get("locality") == job.get("locality") and j not in related][:5 - len(related)]
    searches = []
    if active:
        # Linkuri spre paginile de căutare în care apare oferta (doar cele indexate).
        pool = active_jobs()
        for info, n in topics.all_pages(pool):
            if topics.indexable(n) and any(j["id"] == job["id"] for j in topics.resolve(info["slug"], pool)[1]):
                searches.append(info)
    html = render_template(
        "job_detail.html", searches=searches,
        job=job, active=active, rows=details(job), lead=lead(job),
        meta_description=meta_description(job),
        jsonld=[jobposting_jsonld(job), breadcrumbs(job)] if active else [breadcrumbs(job)],
        canonical=job_url(job), related=related,
        **_context(),
    )
    # Oferta expirată sau retrasă: 410, ca Google s-o scoată repede din rezultate.
    return (html, 200) if active else (html, 410)


def landing(slug):
    """Pagina unei căutări: o localitate („locuri de muncă Făgăraș”) sau un tip de job."""
    if slug != slug.lower():
        return redirect(f"{HUB_PATH}/{slug.lower()}", code=301)
    all_jobs = active_jobs()
    info, jobs = topics.resolve(slug, all_jobs)
    if info is None:
        abort(404)
    page = max(1, request.args.get("page", 1, type=int) or 1)
    total_pages = max(1, math.ceil(len(jobs) / PER_PAGE))
    page = min(page, total_pages)
    store = load_store()
    updated, stale = freshness(store)
    now = datetime.now(TZ)
    others = [(i, n) for i, n in topics.all_pages(all_jobs) if i["slug"] != slug and topics.indexable(n)]
    canonical = f"{SITE_URL}{HUB_PATH}/{slug}" + (f"?page={page}" if page > 1 else "")
    itemlist = {"@context": "https://schema.org", "@type": "ItemList", "name": info["h1"],
                "numberOfItems": len(jobs),
                "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": job_url(j)}
                                    for i, j in enumerate(jobs[:PER_PAGE])]}
    return render_template(
        "jobs_landing.html",
        info=info, jobs=jobs[(page - 1) * PER_PAGE: page * PER_PAGE], total=len(jobs),
        stats=topics.summary(info, jobs), indexable=topics.indexable(len(jobs)) and bool(jobs),
        page=page, total_pages=total_pages, canonical=canonical,
        month=f"{MONTHS[now.month - 1]} {now.year}", updated=updated, stale=stale,
        others=others, total_all=len(all_jobs), source_url=store.get("source_url"),
        jsonld=[breadcrumbs(landing=info), itemlist],
        **_context(),
    )


def register(app, categories):
    app.config.setdefault("KP_CATEGORIES", categories)
    app.register_blueprint(bp)
    app.add_template_global(job_path, "job_path")
    app.add_template_global(salary_text, "job_salary")
    app.add_template_global(place_text, "job_place")
    app.add_template_global(positions_text, "job_positions")
    app.add_template_global(fmt_date, "fmt_date_ro")
    app.add_template_global(ro_count, "ro_count")
    app.add_template_global(fmt_lei, "job_num")
    app.add_template_global(SITE_NAME, "site_name")
