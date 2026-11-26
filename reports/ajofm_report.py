"""Raport lunar: piața muncii în județul Brașov, din ofertele AJOFM colectate de sources/ajofm.py.

Fără LLM: toate cifrele se calculează din data/jobs/ajofm_brasov.json, iar textul e un șablon.
Articolul se salvează ca ciornă pentru George (data/drafts/), cu source_type = date_oficiale.
Fiecare rulare păstrează și cifrele lunii în data/jobs/reports/AAAA-LL.json, ca raportul
următor să poată compara cu luna trecută.

Rulare: python -m reports.ajofm_report [--dry-run] [--data-dir data]
"""
import argparse
import json
import logging
import statistics
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from editorial import store as editorial_store
from sources import ajofm
from web.jobs import HUB_PATH, MONTHS, SITE_URL, fmt_lei, is_active, ro_count

log = logging.getLogger("reports.ajofm")

TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
MIN_JOBS = 20       # sub atâtea oferte nu are sens un raport (probabil sursa a avut o problemă)
MIN_SALARIES = 10   # sub atâtea salarii declarate nu dăm mediane
TOP = 10


def report_id(day):
    return f"ajofm-raport-{day:%Y-%m}"


def _positions(job):
    return job.get("positions") or 1


def _by_positions(jobs, field, limit=TOP):
    counts = {}
    for j in jobs:
        key = j.get(field)
        if key:
            offers, pos = counts.get(key, (0, 0))
            counts[key] = (offers + 1, pos + _positions(j))
    items = sorted(counts.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))
    return [{"name": k, "offers": o, "positions": p} for k, (o, p) in items[:limit]]


def _share(jobs, pred):
    return round(100 * sum(1 for j in jobs if pred(j)) / len(jobs)) if jobs else 0


def _salary_stats(values):
    if len(values) < MIN_SALARIES:
        return None
    q = statistics.quantiles(values, n=4)
    return {"count": len(values), "median": statistics.median(values), "p25": q[0], "p75": q[2]}


def compute(store, today):
    """Cifrele raportului, doar din ofertele active la data `today`."""
    today_s = today.isoformat()
    jobs = [dict(j, title=ajofm.nice_occupation(j.get("title")))
            for j in store.get("jobs", {}).values() if is_active(j, today_s)]
    salaried = [j for j in jobs if j.get("salary_min")]
    return {
        "date": today_s,
        "fetched_at": store.get("fetched_at"),
        "offers": len(jobs),
        "positions": sum(_positions(j) for j in jobs),
        "employers": len({j.get("employer_cui") or j.get("employer_name") for j in jobs}),
        "localities": _by_positions(jobs, "locality"),
        "locality_count": len({j.get("locality") for j in jobs if j.get("locality")}),
        "occupations": _by_positions(jobs, "title"),
        "domains": _by_positions(jobs, "domain", limit=6),
        "top_employers": _by_positions(jobs, "employer_name", limit=5),
        "with_salary": len(salaried),
        "salary_gross": _salary_stats([j["salary_min"] for j in salaried if j.get("salary_type") == "brut"]),
        "salary_net": _salary_stats([j["salary_min"] for j in salaried if j.get("salary_type") == "net"]),
        "no_experience_pct": _share(jobs, lambda j: (j.get("experience") or "").startswith("Fără experiență")),
        "low_education_pct": _share(jobs, lambda j: (j.get("education") or "").startswith(("Gimnazial", "Primar"))),
        "higher_education_pct": _share(jobs, lambda j: (j.get("education") or "").startswith("Universitar")),
        "permanent_pct": _share(jobs, lambda j: j.get("contract_type") == "Cu durată nedeterminată"),
        "remote": sum(1 for j in jobs if j.get("work_regime") in ("Telemuncă", "Hibrid - sediu + telemuncă")),
        "eu_citizens": sum(1 for j in jobs if j.get("eu_citizens")),
        "new_this_month": sum(1 for j in jobs if (j.get("date_posted") or "")[:7] == today_s[:7]),
    }


# ---------- text ----------

def fmt_day(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def _hub_link(text, **args):
    url = HUB_PATH + ("?" + urlencode(args) if args else "")
    return f'<a href="{escape(url)}">{escape(text)}</a>'


def _change(now, before):
    diff = now - before
    if diff == 0:
        return "la fel ca luna trecută"
    pct = round(100 * abs(diff) / before) if before else None
    word = "mai multe" if diff > 0 else "mai puține"
    extra = f" ({pct}%)" if pct else ""
    return f"cu {ro_count(abs(diff), 'post', 'posturi')} {word} decât luna trecută{extra}"


def _table(head, rows):
    th = "".join(f"<th>{escape(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def render(stats, previous=None):
    """Articolul (dict) pentru stats. `previous` = cifrele lunii trecute, dacă există."""
    day = date.fromisoformat(stats["date"])
    when = fmt_day(day)
    month = f"{MONTHS[day.month - 1]} {day.year}"
    top_occ = stats["occupations"][0] if stats["occupations"] else None
    city = next((l for l in stats["localities"] if l["name"] == "Brașov"), None)
    source_link = f'<a href="{ajofm.SOURCE_HOME}" rel="noopener">platforma ANOFM</a>'

    title = f"Locuri de muncă în județul Brașov, {month}: {ro_count(stats['positions'], 'post liber', 'posturi libere')} la AJOFM"

    p = []
    lead = (f"Pe {when}, angajatorii din județul Brașov aveau la AJOFM "
            f"{ro_count(stats['offers'], 'ofertă activă', 'oferte active')}, pentru "
            f"{ro_count(stats['positions'], 'post', 'posturi')}, la "
            f"{ro_count(stats['employers'], 'angajator', 'angajatori')} din "
            f"{ro_count(stats['locality_count'], 'localitate', 'localități')}.")
    if city:
        lead += f" În municipiul Brașov sunt {ro_count(city['positions'], 'post', 'posturi')}."
    if top_occ:
        lead += (f" Cele mai multe posturi sunt pentru „{escape(top_occ['name'].lower())}” "
                 f"({top_occ['positions']}).")
    p.append(f"<p>{lead}</p>")
    if previous and previous.get("positions"):
        p.append(f"<p>Numărul de posturi este {_change(stats['positions'], previous['positions'])}, "
                 f"când erau {ro_count(previous['positions'], 'post', 'posturi')} în "
                 f"{ro_count(previous['offers'], 'ofertă', 'oferte')}.</p>")
    p.append(f"<p>Cifrele sunt calculate de KronPapir din ofertele publicate pe {source_link}, "
             f"pe care le colectăm de două ori pe zi. Toate ofertele active se găsesc, cu filtre "
             f"pe localitate și domeniu, pe pagina {_hub_link('Locuri de muncă Brașov')}.</p>")

    p.append("<h2>Ce meserii se caută</h2>")
    p.append(_table(["Ocupație", "Posturi", "Oferte"], [
        [_hub_link(o["name"], q=o["name"]), o["positions"], o["offers"]] for o in stats["occupations"]]))
    if stats["domains"]:
        doms = ", ".join(f"{escape(d['name'])} ({d['positions']})" for d in stats["domains"])
        p.append(f"<p>Pe domenii, cele mai multe posturi sunt în: {doms}.</p>")

    p.append("<h2>Unde sunt posturile</h2>")
    p.append(_table(["Localitate", "Posturi", "Oferte"], [
        [_hub_link(l["name"], loc=l["name"]), l["positions"], l["offers"]] for l in stats["localities"]]))

    p.append("<h2>Ce salarii se oferă</h2>")
    g, n = stats["salary_gross"], stats["salary_net"]
    sal = (f"<p>Doar {stats['with_salary']} din {ro_count(stats['offers'], 'ofertă', 'oferte')} au salariul trecut în anunț. "
           if stats["with_salary"] < stats["offers"] else "<p>Toate ofertele au salariul trecut în anunț. ")
    if g:
        sal += (f"La cele {g['count']} cu salariu brut, salariul de pornire median este "
                f"{fmt_lei(g['median'])} lei brut: jumătate dintre oferte dau mai puțin, jumătate mai mult. "
                f"Jumătatea din mijloc se încadrează între {fmt_lei(g['p25'])} și {fmt_lei(g['p75'])} lei brut.")
    if n:
        sal += (f" La cele {ro_count(n['count'], 'ofertă', 'oferte')} cu salariu net, mediana este {fmt_lei(n['median'])} lei net.")
    if not g and not n:
        sal += "Sunt prea puține salarii declarate ca să calculăm o medie corectă."
    p.append(sal + "</p>")
    p.append(f"<p>{_hub_link('Vezi ofertele ordonate după salariu', salariu='1', sort='salariu')}.</p>")

    p.append("<h2>Ce se cere</h2>")
    p.append(f"<p>{stats['no_experience_pct']}% dintre oferte acceptă candidați fără experiență, iar "
             f"{stats['low_education_pct']}% cer cel mult școala generală. Studii superioare cer "
             f"{stats['higher_education_pct']}% dintre oferte. {stats['permanent_pct']}% sunt cu contract "
             f"pe durată nedeterminată. Doar {ro_count(stats['remote'], 'ofertă', 'oferte')} permit "
             f"telemunca, total sau parțial. {ro_count(stats['eu_citizens'], 'ofertă e deschisă', 'oferte sunt deschise')} "
             f"și cetățenilor din alte țări ale UE.</p>")

    if stats["top_employers"]:
        p.append("<h2>Angajatorii cu cele mai multe posturi</h2>")
        p.append(_table(["Angajator", "Posturi", "Oferte"], [
            [escape(e["name"]), e["positions"], e["offers"]] for e in stats["top_employers"]]))

    p.append("<h2>Cum aplici</h2>")
    p.append(f"<p>Fiecare ofertă de pe {_hub_link('pagina noastră')} trimite la anunțul de pe {source_link}, "
             "unde găsești datele de contact ale angajatorului.</p>")

    p.append("<h2>Cum am calculat</h2>")
    fetched = stats.get("fetched_at") or stats["date"]
    p.append("<p>Am numărat ofertele active din județul Brașov la ultima colectare "
             f"({fmt_day(date.fromisoformat(fetched[:10]))}{', ora ' + fetched[11:16] if len(fetched) >= 16 else ''}). O ofertă poate avea mai multe posturi; "
             "unde AJOFM nu trece numărul de posturi, am numărat unul. Salariile sub 500 de lei "
             "(unele anunțuri trec „1 leu”) nu sunt salarii reale și nu intră în calcul. Am folosit "
             "salariul minim din fiecare anunț (cel de pornire). Mediana e mai corectă decât media "
             "pentru salarii, fiindcă nu e trasă în sus de câteva oferte foarte bine plătite.</p>")

    excerpt = (f"{ro_count(stats['positions'], 'post liber', 'posturi libere')} la AJOFM Brașov pe {when}: "
               "ce meserii se caută, în ce localități și ce salarii se oferă.")
    return {
        "id": report_id(day),
        "title": title,
        "slug": f"locuri-de-munca-judetul-brasov-{day:%Y-%m}",
        "excerpt": excerpt,
        "meta_description": excerpt[:160],
        "content": "\n".join(p),
        "category": "economie",
        "type": "local",
        "source": ajofm.SOURCE_NAME,
        "source_url": ajofm.SOURCE_HOME,
        "source_type": "date_oficiale",
        "keywords": ["locuri de muncă Brașov", "AJOFM Brașov", "salarii Brașov", "joburi Brașov"],
        "date": datetime.now(TZ).isoformat(timespec="seconds"),
        "report_stats": stats,
    }


# ---------- rulare ----------

def snapshot_path(data_root, day):
    return Path(data_root) / "jobs" / "reports" / f"{day:%Y-%m}.json"


def previous_snapshot(data_root, day):
    folder = Path(data_root) / "jobs" / "reports"
    current = f"{day:%Y-%m}.json"
    older = sorted(p for p in folder.glob("*.json") if p.name < current) if folder.exists() else []
    if not older:
        return None
    try:
        return json.loads(older[-1].read_text(encoding="utf-8"))
    except ValueError:
        return None


def run(data_dir=None, today=None, dry_run=False):
    data_root = Path(data_dir or BASE_DIR / "data")
    today = today or datetime.now(TZ).date()
    store = ajofm.load_store(ajofm.store_path(data_root))
    stats = compute(store, today)
    if stats["offers"] < MIN_JOBS:
        raise RuntimeError(f"Doar {stats['offers']} oferte active; nu fac raportul.")
    article = render(stats, previous_snapshot(data_root, today))

    if (editorial_store.PROCESSED_DIR / f"{article['id']}.json").exists():
        log.info("Raportul pe %s e deja publicat; nu-l suprascriu.", f"{today:%Y-%m}")
        return article, False
    if dry_run:
        return article, False
    ajofm.write_store(snapshot_path(data_root, today), stats)
    editorial_store.save_draft(article, reason="Raport lunar AJOFM (cifre calculate automat)")
    return article, True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raportul lunar AJOFM Brașov, ca ciornă")
    parser.add_argument("--dry-run", action="store_true", help="afișează articolul, nu scrie nimic")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        article, saved = run(data_dir=args.data_dir, dry_run=args.dry_run)
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    if args.dry_run:
        print(article["title"])
        print(article["content"])
    log.info("Raport AJOFM %s: %s", article["id"], "ciornă salvată" if saved else "nesalvat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
