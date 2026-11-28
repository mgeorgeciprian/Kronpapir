"""Paginile „Știri <localitate>”: /stiri-sacele, /stiri-fagaras, /stiri-ghimbav etc.

Fiecare pagină strânge tot ce avem despre o localitate din județ: știrile locale care o pomenesc
în titlu sau la începutul textului, locurile de muncă AJOFM de acolo și anunțurile de licitații
ale primăriei. Textul de introducere e făcut numai din cifre (nimic inventat).

O pagină intră în Google și în sitemap doar dacă are destul conținut (vezi `indexable`); sub prag
rămâne accesibilă, cu noindex, ca Google să nu vadă pagini subțiri. Municipiul Brașov nu are
pagină proprie: /stiri-brasov face 301 spre /local.
"""
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta

from flask import Blueprint, abort, current_app, redirect, render_template, request

from sources.licitatii import expiry
from web import business, job_topics
from web import jobs as jobs_web

bp = Blueprint("localities", __name__)

SITE_URL = "https://kronpapir.ro"
PREFIX = "/stiri-"
PER_PAGE = 20
RECENT_DAYS = 180  # știrile numărate pentru prag
MIN_NEWS_ALONE = 10  # atâtea știri recente ajung singure pentru index
MIN_NEWS = 5  # sau atâtea, plus joburi / licitații
MIN_JOBS = 5
MIN_TENDERS = business.INDEX_MIN_ITEMS
CACHE_SECONDS = 600

MUNICIPII = {"brasov", "codlea", "fagaras", "sacele"}
ORASE = {"ghimbav", "predeal", "rasnov", "rupea", "victoria", "zarnesti"}

# Nume care sunt și prenume, cuvinte obișnuite sau localități din alte județe: le numărăm doar
# când textul spune clar că e localitatea („comuna Bod”, „din Cristian”, „la Victoria”).
AMBIGUOUS = {"augustin", "beclean", "bod", "cata", "comana", "cristian", "dumbravita", "homorod",
             "lisa", "mandra", "recea", "ucea", "victoria", "vulcan"}
CONTEXT = r"(?:comuna|comunei|orasul|orasului|municipiul|municipiului|localitatea|localitatii|satul|satului|din|la|in)\s+"


def _fold(text):
    """Fără diacritice, cu majusculele păstrate: „Săcele” -> „Sacele”."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c))


def _plain(html, limit):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or ""))[:limit]


def uats():
    """[{slug, title}] pentru cele 57 de localități din județ, fără municipiul Brașov."""
    return [u for u in business.load_map()["uat"] if u["slug"] != "brasov"]


def kind(slug):
    if slug in MUNICIPII:
        return "municipiul"
    if slug in ORASE:
        return "orașul"
    return "comuna"


_patterns = {}


def pattern(u, all_uats=None):
    """Regex pe textul fără diacritice. Cu majusculă, ca „recea”/„bod” scrise mic să nu conteze;
    „Șinca” nu prinde „Șinca Nouă”."""
    key = u["slug"]
    if key not in _patterns:
        name = _fold(u["title"])
        longer = [_fold(o["title"])[len(name):] for o in (all_uats or uats())
                  if o["slug"] != key and _fold(o["title"]).startswith(name + " ")]
        tail = "".join(f"(?!{re.escape(rest)})" for rest in longer)
        core = r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])" + tail
        if key in AMBIGUOUS:
            core = r"(?i:" + CONTEXT + r")" + core
        _patterns[key] = re.compile(core)
    return _patterns[key]


def mentions(article, all_uats=None):
    """Slug-urile localităților pomenite: (în titlu, în text). Textul = primele 800 de caractere."""
    all_uats = all_uats or uats()
    title = _fold(article.get("title"))
    body = _fold(_plain(article.get("content"), 800))
    in_title, in_body = [], []
    for u in all_uats:
        rx = pattern(u, all_uats)
        if rx.search(title):
            in_title.append(u["slug"])
        elif rx.search(body):
            in_body.append(u["slug"])
    return in_title, in_body


def _is_local_news(a):
    return a.get("type", "local") != "national" and not a.get("is_editorial") \
        and (a.get("category") or "").lower() != "editorial" and not a.get("duplicate_of")


_cache = {"key": None, "at": 0.0, "index": {}}
_lock = threading.Lock()


def _load_articles():
    loader = current_app.config.get("KP_LOAD_ARTICLES")
    return loader() if loader else []


def news_index():
    """{slug: [articole]} (cele mai noi întâi). Recalculat când se schimbă lista sau la 10 minute."""
    articles = [a for a in _load_articles() if _is_local_news(a)]
    key = (len(articles), max((a.get("date") or "" for a in articles), default=""))
    with _lock:
        if _cache["key"] == key and time.time() - _cache["at"] < CACHE_SECONDS:
            return _cache["index"]
    all_uats = uats()
    index = {}
    for a in articles:
        in_title, in_body = mentions(a, all_uats)
        for slug in in_title + in_body:
            index.setdefault(slug, []).append(a)
    for items in index.values():
        items.sort(key=lambda a: a.get("date") or "", reverse=True)
    with _lock:
        _cache.update(key=key, at=time.time(), index=index)
    return index


def _recent(items, days, now=None):
    cut = ((now or datetime.now()) - timedelta(days=days)).strftime("%Y-%m-%d")
    return [a for a in items if (a.get("date") or "")[:10] >= cut]


def _jobs_by_place():
    out = {}
    for j in jobs_web.active_jobs():
        out.setdefault(job_topics.slugify(j.get("locality")), []).append(j)
    return out


def _tenders_by_place():
    groups = business.with_places(business.licitatii_groups(business.load_licitatii()), business.load_map()["uat"])
    out = {}
    for key in ("achizitii", "terenuri", "anaf"):
        for it in groups.get(key, []):
            if it.get("loc"):
                # doar termenul scris în anunț, nu cel estimat (30 de zile) din expiry.py
                it["deadline_shown"] = str(it.get("deadline") or "")[:10] or expiry.deadline_in_title(it.get("title"))
                out.setdefault(it["loc"], []).append(it)
    return out


def indexable(n_recent, n_jobs, n_tenders):
    return n_recent >= MIN_NEWS_ALONE or (n_recent >= MIN_NEWS and (n_jobs >= MIN_JOBS or n_tenders >= MIN_TENDERS))


def overview():
    """[{slug, title, news, recent, jobs, tenders, indexable}] pentru toate localitățile, cele mai bogate întâi."""
    news, jobs, tenders = news_index(), _safe(_jobs_by_place), _safe(_tenders_by_place)
    rows = []
    for u in uats():
        s = u["slug"]
        items = news.get(s, [])
        rec = len(_recent(items, RECENT_DAYS))
        nj, nt = len(jobs.get(s, [])), len(tenders.get(s, []))
        rows.append({"slug": s, "title": u["title"], "news": len(items), "recent": rec, "jobs": nj,
                     "tenders": nt, "indexable": indexable(rec, nj, nt), "url": PREFIX + s})
    rows.sort(key=lambda r: (-r["indexable"], -(r["news"] + r["jobs"] + r["tenders"]), r["title"]))
    return rows


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # o sursă de date lipsă nu are voie să strice pagina
        current_app.logger.warning("localități: %s indisponibil: %s", fn.__name__, e)
        return {}


def indexed_pages():
    return [r for r in overview() if r["indexable"]]


def sitemap_entries():
    today = datetime.now().strftime("%Y-%m-%d")
    news = news_index()
    out = []
    for r in indexed_pages():
        items = news.get(r["slug"]) or []
        last = (items[0].get("date") or "")[:10] if items else ""
        out.append({"loc": SITE_URL + r["url"], "lastmod": last or today})
    return out


def article_link(article):
    """Linkul „Tot despre <localitate>” pentru un articol local, spre o pagină indexabilă, sau None.
    Preferăm localitatea din titlu; la egalitate, pe cea cu mai mult conținut."""
    try:
        if not _is_local_news(article):
            return None
        in_title, in_body = mentions(article)
        if not in_title and not in_body:
            return None
        rows = {r["slug"]: r for r in indexed_pages()}
        for group in (in_title, in_body):
            hits = [rows[s] for s in group if s in rows]
            if hits:
                return max(hits, key=lambda r: r["news"] + r["jobs"] + r["tenders"])
        return None
    except Exception:
        return None


def _breadcrumbs(name, url):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Acasă", "item": SITE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": "Știri locale", "item": SITE_URL + "/local"},
        {"@type": "ListItem", "position": 3, "name": f"Știri {name}", "item": url}]}


@bp.route(PREFIX + "<slug>")
def page(slug):
    if slug == "brasov":
        return redirect("/local", code=301)
    by_slug = {u["slug"]: u for u in uats()}
    if slug not in by_slug:
        abort(404)
    name = by_slug[slug]["title"]
    pg = max(request.args.get("page", 1, type=int), 1)

    items = news_index().get(slug, [])
    jobs = _safe(_jobs_by_place).get(slug, [])
    tenders = _safe(_tenders_by_place).get(slug, [])
    rec = _recent(items, RECENT_DAYS)
    last30 = _recent(items, 30)

    total_pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    if pg > total_pages:
        abort(404)
    shown = items[(pg - 1) * PER_PAGE: pg * PER_PAGE]
    url = SITE_URL + PREFIX + slug
    canonical = url + (f"?page={pg}" if pg > 1 else "")
    ok = indexable(len(rec), len(jobs), len(tenders)) and pg == 1

    job_pages = job_topics.localities(jobs_web.active_jobs()) if jobs else {}
    sources = {}
    for a in rec:
        if a.get("source"):
            sources[a["source"]] = sources.get(a["source"], 0) + 1
    top_sources = [s for s, _ in sorted(sources.items(), key=lambda kv: -kv[1])[:3]]

    others = [r for r in indexed_pages() if r["slug"] != slug]
    jsonld = [
        {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"Știri {name}",
         "url": url, "inLanguage": "ro-RO",
         "isPartOf": {"@type": "WebSite", "name": "KronPapir", "url": SITE_URL},
         "about": {"@type": "Place", "name": name,
                   "containedInPlace": {"@type": "AdministrativeArea", "name": "Județul Brașov"}},
         "mainEntity": {"@type": "ItemList", "itemListElement": [
             {"@type": "ListItem", "position": i + 1, "url": SITE_URL + current_app.jinja_env.filters["article_url"](a)}
             for i, a in enumerate(shown[:10])]}},
        _breadcrumbs(name, url),
    ]
    return render_template(
        "stiri_localitate.html", name=name, slug=slug, kind=kind(slug), articles=shown, total=len(items),
        n_recent=len(rec), n_30=len(last30), recent_days=RECENT_DAYS, top_sources=top_sources,
        jobs=jobs[:5], n_jobs=len(jobs), jobs_url=(f"{jobs_web.HUB_PATH}/{slug}" if slug in job_pages else None),
        tenders=tenders[:5], n_tenders=len(tenders),
        tenders_url=f"{business.LICITATII_PATH}/{slug}", page=pg, total_pages=total_pages,
        canonical=canonical, indexable=ok, others=others, jsonld=jsonld,
        categories=current_app.config.get("KP_CATEGORIES", {}),
    )


def register(app):
    app.add_template_global(article_link, "locality_hub_link")
    app.add_template_global(indexed_pages, "locality_pages")
    app.register_blueprint(bp)
