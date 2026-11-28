"""Raport săptămânal: locurile de muncă noi din județul Brașov, din ofertele AJOFM.

Fără LLM. Ia ofertele active publicate de AJOFM în săptămâna trecută (luni–duminică), le
grupează pe localități și domenii și pune linkul fiecărei oferte de pe site. Cifrele se calculează
aici, iar o verificare deterministă confirmă că fiecare număr din articol vine din date. Articolul
e de date oficiale, deci se publică automat (CLAUDE.md, regula 3). Un raport deja publicat pentru
aceeași săptămână nu se suprascrie.

Rulare: python -m reports.jobs_weekly [--dry-run] [--data-dir data] [--week-of AAAA-LL-ZZ]
"""
import argparse
import logging
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from editorial import store as editorial_store
from editorial.factcheck import _NUM, _norm_number
from sources import ajofm
from web import job_topics
from web.jobs import HUB_PATH, MONTHS, fmt_lei, is_active, job_path, ro_count

log = logging.getLogger("reports.jobs_weekly")

TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
MIN_NEW = 10  # sub atâtea oferte noi nu publicăm (probabil sursa a avut o problemă)
LIST_MAX = 25
# Doar angajatori persoane juridice în topuri: fără nume de persoane fizice (CLAUDE.md, regula 6)
COMPANY = re.compile(r"\b(S\.?\s?R\.?\s?L\.?|S\.?\s?A\.?|SRL|SA|SCS|SNC|COOPERATIVA|ASOCIA|FUNDA|SPITAL|PRIM[ĂA]RIA|"
                     r"UNIVERSITATEA|LICEUL|[ȘS]COALA|GR[ĂA]DINI|DIREC[ȚT]IA|REGIA|COMPANIA|INSTITUTUL)\b", re.I)


def week_bounds(today):
    """Săptămâna trecută, de luni până duminică, față de `today`."""
    monday = today - timedelta(days=today.weekday() + 7)
    return monday, monday + timedelta(days=6)


def report_id(monday):
    y, w, _ = monday.isocalendar()
    return f"joburi-saptamana-{y}-{w:02d}"


def fmt_day(d):
    return f"{d.day} {MONTHS[d.month - 1]}"


def fmt_span(monday, sunday):
    """„23 și 29 noiembrie 2026” / „30 noiembrie și 6 decembrie 2026”."""
    first = str(monday.day) if monday.month == sunday.month else fmt_day(monday)
    return f"{first} și {fmt_day(sunday)} {sunday.year}"


def _positions(j):
    return int(j.get("positions") or 1)


def compute(store, monday, sunday, today):
    start, end = monday.isoformat(), sunday.isoformat()
    jobs = [dict(j, title=ajofm.nice_occupation(j.get("title")))
            for j in store.get("jobs", {}).values()
            if is_active(j, today.isoformat()) and start <= (j.get("date_posted") or "")[:10] <= end]
    jobs.sort(key=lambda j: (-(j.get("salary_min") or 0), j.get("title") or ""))
    places, domains, employers = {}, {}, {}
    for j in jobs:
        places[j.get("locality") or "nespecificat"] = places.get(j.get("locality") or "nespecificat", 0) + _positions(j)
        if j.get("domain"):
            domains[j["domain"]] = domains.get(j["domain"], 0) + _positions(j)
        e = (j.get("employer_name") or "").strip()
        if e and COMPANY.search(e):
            employers[e] = employers.get(e, 0) + _positions(j)
    brut = [j["salary_min"] for j in jobs if j.get("salary_min") and j.get("salary_type") == "brut"]
    no_exp = sum(1 for j in jobs if (j.get("experience") or "").startswith("Fără experiență"))
    return {
        "monday": start, "sunday": end, "jobs": jobs,
        "offers": len(jobs), "positions": sum(_positions(j) for j in jobs),
        "places": sorted(places.items(), key=lambda kv: (-kv[1], kv[0]))[:8],
        "domains": sorted(domains.items(), key=lambda kv: (-kv[1], kv[0]))[:6],
        "employers": sorted(employers.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
        "median_brut": int(statistics.median(brut)) if len(brut) >= 5 else None,
        "max_brut": int(max(brut)) if brut else None,
        "n_brut": len(brut), "no_experience": no_exp,
    }


def _salary(j):
    if not j.get("salary_min"):
        return ""
    s = fmt_lei(j["salary_min"])
    if j.get("salary_max") and j["salary_max"] > j["salary_min"]:
        s += f"–{fmt_lei(j['salary_max'])}"
    return f"{s} lei {j.get('salary_type') or ''}".strip()


def render(stats, active_pages):
    monday, sunday = date.fromisoformat(stats["monday"]), date.fromisoformat(stats["sunday"])
    period = fmt_span(monday, sunday)
    hub = f'<a href="{HUB_PATH}">Locuri de muncă Brașov</a>'
    p = []
    lead = (f"<p>Între {period}, AJOFM Brașov a publicat {ro_count(stats['offers'], 'ofertă nouă de muncă', 'oferte noi de muncă')} "
            f"în județ, cu {ro_count(stats['positions'], 'post liber', 'posturi libere')}, care sunt încă active.")
    if stats["median_brut"]:
        lead += (f" Salariul median oferit este {fmt_lei(stats['median_brut'])} lei brut, la cele "
                 f"{ro_count(stats['n_brut'], 'ofertă', 'oferte')} care au salariul brut afișat.")
    if stats["no_experience"]:
        lead += f" {ro_count(stats['no_experience'], 'ofertă nu cere', 'oferte nu cer')} experiență."
    p.append(lead + "</p>")

    if stats["places"]:
        p.append("<h2>Unde sunt posturile noi</h2>")
        items = []
        for name, n in stats["places"]:
            slug = job_topics.slugify(name)
            label = escape(name)
            if slug in active_pages:
                label = f'<a href="{HUB_PATH}/{slug}">{label}</a>'
            items.append(f"<li>{label}: {ro_count(n, 'post', 'posturi')}</li>")
        p.append("<ul>" + "".join(items) + "</ul>")

    if stats["domains"]:
        p.append("<h2>În ce domenii</h2>")
        p.append("<ul>" + "".join(f"<li>{escape(d)}: {ro_count(n, 'post', 'posturi')}</li>" for d, n in stats["domains"]) + "</ul>")

    if stats["employers"]:
        p.append("<h2>Cine angajează cel mai mult</h2>")
        p.append("<ul>" + "".join(f"<li>{escape(e)}: {ro_count(n, 'post', 'posturi')}</li>" for e, n in stats["employers"]) + "</ul>")

    shown = stats["jobs"][:LIST_MAX]
    p.append("<h2>Ofertele noi, de la cel mai mare salariu</h2>")
    rows = []
    for j in shown:
        bits = [escape(x) for x in (j.get("employer_name") if COMPANY.search(j.get("employer_name") or "") else "",
                                    j.get("locality") or "", _salary(j)) if x]
        rows.append(f'<li><a href="{job_path(j)}">{escape(j.get("title") or "")}</a>'
                    + (f" – {' · '.join(bits)}" if bits else "") + "</li>")
    p.append("<ul>" + "".join(rows) + "</ul>")
    if stats["offers"] > len(shown):
        p.append(f"<p>Restul ofertelor, cu filtre pe localitate și domeniu, sunt pe pagina {hub}.</p>")

    p.append("<h2>Cum aplici</h2>")
    p.append(f"<p>Fiecare ofertă are pe pagina ei datele angajatorului, cerințele și linkul spre anunțul oficial de pe "
             f'<a href="https://mediere.anofm.ro/app/module/mediere/jobs" rel="noopener" target="_blank">mediere.anofm.ro</a>. '
             "KronPapir nu intermediază angajări și nu cere bani candidaților. Lista se actualizează de două ori pe zi; "
             f"toate ofertele active din județ sunt pe {hub}.</p>")

    span = f"{monday.day}–{fmt_day(sunday)}" if monday.month == sunday.month else f"{fmt_day(monday)} – {fmt_day(sunday)}"
    title = (f"Locuri de muncă noi în Brașov ({span}): "
             f"{ro_count(stats['offers'], 'ofertă', 'oferte')} AJOFM")
    top = ", ".join(name for name, _ in stats["places"][:3])
    excerpt = (f"{ro_count(stats['offers'], 'ofertă nouă', 'oferte noi')} de muncă în județul Brașov, publicate de AJOFM "
               f"între {period}" + (f", mai ales în {top}" if top else "") + ". Lista completă, cu salariile.")
    return {
        "id": report_id(monday),
        "title": title,
        "slug": f"locuri-de-munca-noi-brasov-{monday.isoformat()}",
        "excerpt": excerpt,
        "meta_description": excerpt[:155],
        "content": "\n".join(p),
        "category": "economie",
        "type": "local",
        "source": "AJOFM Brașov",
        "source_url": "https://mediere.anofm.ro/app/module/mediere/jobs",
        "url": "https://mediere.anofm.ro/app/module/mediere/jobs",
        "source_type": "date_oficiale",
        "keywords": ["locuri de muncă Brașov", "joburi Brașov", "AJOFM Brașov", "angajări Brașov"],
        "date": datetime.now(TZ).isoformat(timespec="seconds"),
        "report_week": stats["monday"],
    }


def allowed_numbers(stats):
    """Numerele pe care articolul are voie să le conțină: cifrele calculate și cele din datele ofertelor."""
    vals = set()
    for k in ("offers", "positions", "median_brut", "max_brut", "n_brut", "no_experience"):
        if stats.get(k) is not None:
            vals |= {str(stats[k]), fmt_lei(stats[k])}
    for _, n in stats["places"] + stats["domains"] + stats["employers"]:
        vals.add(str(n))
    for d in (stats["monday"], stats["sunday"]):
        vals |= {d[:4], str(int(d[8:10])), d[5:7]}
    text = " ".join(" ".join(str(j.get(f) or "") for f in ("title", "employer_name", "locality", "domain"))
                    for j in stats["jobs"])
    vals |= set(_NUM.findall(text))
    for j in stats["jobs"]:
        for f in ("salary_min", "salary_max"):
            if j.get(f):
                vals |= {fmt_lei(j[f]), str(int(j[f]))}
    out = set()
    for v in vals:
        if v:
            out |= _norm_number(str(v))
    return out


def verify(article, stats):
    allowed = allowed_numbers(stats)
    text = " | ".join(re.sub(r"<[^>]+>", " | ", article.get(k) or "") for k in ("title", "excerpt", "content"))
    text = re.sub(r'href="[^"]*"', "", text)
    return [m.group(0) for m in _NUM.finditer(text) if not (_norm_number(m.group(0)) & allowed)]


def run(data_dir=None, today=None, dry_run=False):
    data_root = Path(data_dir or BASE_DIR / "data")
    today = today or datetime.now(TZ).date()
    monday, sunday = week_bounds(today)
    store = ajofm.load_store(ajofm.store_path(data_root))
    stats = compute(store, monday, sunday, today)
    if stats["offers"] < MIN_NEW:
        raise RuntimeError(f"Doar {stats['offers']} oferte noi în săptămâna {monday}; nu fac raportul.")
    active = [j for j in store.get("jobs", {}).values() if is_active(j, today.isoformat())]
    pages = {info["slug"] for info, n in job_topics.all_pages(active) if job_topics.indexable(n)}
    article = render(stats, pages)
    bad = verify(article, stats)
    if bad:
        raise RuntimeError(f"Numere care nu vin din datele AJOFM: {bad[:10]}; nu public.")
    if (editorial_store.PROCESSED_DIR / f"{article['id']}.json").exists():
        log.info("Raportul săptămânii %s există deja; nu-l suprascriu.", monday)
        return article, False
    if dry_run:
        return article, False
    article["fact_check"] = {"scor": 10, "erori_blocante": [], "recomandari": [],
                             "model": "verificare deterministă (fiecare număr provine din ofertele AJOFM)"}
    editorial_store.publish_automatic(article)
    return article, True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raportul săptămânal: locuri de muncă noi în Brașov (AJOFM)")
    parser.add_argument("--dry-run", action="store_true", help="afișează articolul, nu publică")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--week-of", default=None, help="o zi din săptămâna DE DUPĂ cea raportată (AAAA-LL-ZZ)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    today = date.fromisoformat(args.week_of) if args.week_of else None
    try:
        article, saved = run(data_dir=args.data_dir, today=today, dry_run=args.dry_run)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1
    if args.dry_run:
        print(article["title"])
        print(article["content"])
    log.info("Raport joburi %s: %s", article["id"], "publicat" if saved else "nepublicat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
