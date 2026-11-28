"""Raport săptămânal: licitațiile, achizițiile și proiectele noi ale primăriilor din județul Brașov.

Fără LLM. Strânge, pentru ultimele 7 zile:
- anunțurile noi de pe site-urile celor 58 de primării (data reală din anunț sau apărute după
  prima noastră vizită; cele fără dată găsite la prima vizită pot fi vechi și nu intră);
- licitațiile și achizițiile noi ale Primăriei Brașov și proiectele HCL intrate în dezbatere publică;
- termenele care expiră în următoarele 7 zile și licitațiile ANAF din următoarele 14 zile.

Cifrele se numără aici, iar o verificare deterministă confirmă că fiecare număr din articol vine
din date (titlurile oficiale ale anunțurilor sau numărătorile). Articol de date oficiale, publicat
automat (CLAUDE.md, regula 3). Rulează lunea după colectarea licitațiilor; un raport deja publicat
pentru aceeași săptămână nu se suprascrie.

Rulare: python -m reports.licitatii_weekly [--dry-run] [--data-dir data] [--today AAAA-LL-ZZ]
"""
import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from editorial import store as editorial_store
from editorial.factcheck import _NUM, _norm_number
from sources.licitatii import expiry
from web import business
from web.jobs import MONTHS, ro_count

log = logging.getLogger("reports.licitatii_weekly")

TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
WINDOW = 7
ANAF_AHEAD = 14
MIN_ITEMS = 3  # anunțuri noi + termene care expiră; licitațiile ANAF singure nu fac un raport


def report_id(today):
    y, w, _ = today.isocalendar()
    return f"licitatii-saptamana-{y}-{w:02d}"


def fmt_day(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MONTHS[d.month - 1]}"


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _in(day, start, end):
    return bool(day) and start <= day[:10] <= end


def _deadline(it):
    return str(it.get("deadline") or "")[:10] or expiry.deadline_in_title(it.get("title")) or ""


def collect(lic_store, bc_store, today):
    end = today.isoformat()
    start = (today - timedelta(days=WINDOW - 1)).isoformat()
    soon = (today + timedelta(days=WINDOW)).isoformat()
    anaf_until = (today + timedelta(days=ANAF_AHEAD)).isoformat()
    uats = business.load_map()["uat"]
    groups = business.with_places(business.licitatii_groups(lic_store, today), uats)

    def is_new(it):
        if it.get("date_guessed"):
            return bool(it.get("is_new")) and _in(it.get("first_seen"), start, end)
        return _in(it.get("published"), start, end)

    new_sites = [dict(it, dl=_deadline(it)) for k in ("achizitii", "terenuri") for it in groups[k] if is_new(it)]
    soon_sites = [dict(it, dl=_deadline(it)) for k in ("achizitii", "terenuri") for it in groups[k]
                  if not is_new(it) and end <= _deadline(it) <= soon]
    anaf = [it for it in groups["anaf"] if _in(it.get("published"), end, anaf_until)]
    anaf.sort(key=lambda it: it.get("published") or "")

    bc = business.primaria_groups(bc_store, today)
    bc_new = [d for d in bc["lic_open"] if _in(d.get("published"), start, end)]
    bc_soon = [d for d in bc["lic_open"] if d not in bc_new and d.get("deadline", "") <= soon]
    hcl_new = [d for d in bc["hcl_open"] if _in(d.get("published"), start, end)]
    return {"start": start, "end": end, "new_sites": new_sites, "soon_sites": soon_sites, "anaf": anaf,
            "bc_new": bc_new, "bc_soon": bc_soon, "hcl_new": hcl_new}


def _site_row(it):
    place = it.get("place") or ""
    kind = "teren" if it.get("topic") == "terenuri" else "achiziție"
    meta = [escape(place), kind] + ([f"termen {fmt_day(it['dl'])}"] if it.get("dl") else [])
    loc = f' (<a href="{business.LICITATII_PATH}/{it["loc"]}">toate din {escape(place)}</a>)' if it.get("loc") else ""
    return (f'<li><a href="{escape(it["url"])}" rel="noopener nofollow" target="_blank">{escape(it["title"])}</a>'
            f" – {' · '.join(m for m in meta if m)}{loc}</li>")


def _bc_row(d):
    meta = [f"termen {fmt_day(d['deadline'])}"] if d.get("deadline") else []
    return (f'<li><a href="{escape(d["url"])}" rel="noopener nofollow" target="_blank">{escape(d["title"])}</a>'
            + (f" – {' · '.join(meta)}" if meta else "") + "</li>")


def render(c, today):
    total_new = len(c["new_sites"]) + len(c["bc_new"]) + len(c["hcl_new"])
    p = []
    lic = f'<a href="{business.LICITATII_PATH}">Licitații și achiziții în județul Brașov</a>'
    prim = f'<a href="{business.PRIMARIA_PATH}">Primăria Brașov</a>'
    lead = f"<p>În ultimele 7 zile, până pe {fmt_day(c['end'])}, "
    parts = []
    if c["new_sites"]:
        parts.append(f"primăriile din județ au publicat {ro_count(len(c['new_sites']), 'anunț nou', 'anunțuri noi')} de achiziții sau terenuri")
    if c["bc_new"]:
        parts.append(f"Primăria Brașov a lansat {ro_count(len(c['bc_new']), 'licitație sau achiziție', 'licitații și achiziții')}")
    if c["hcl_new"]:
        parts.append(f"{ro_count(len(c['hcl_new']), 'proiect de hotărâre a intrat', 'proiecte de hotărâre au intrat')} în dezbatere publică la Brașov")
    lead += (", ".join(parts[:-1]) + " și " + parts[-1] if len(parts) > 1 else (parts[0] if parts else "nu au apărut anunțuri noi"))
    lead += "."
    n_soon = len(c["soon_sites"]) + len(c["bc_soon"])
    if n_soon:
        lead += f" {ro_count(n_soon, 'termen expiră', 'termene expiră')} în următoarele 7 zile."
    if c["anaf"]:
        lead += f" ANAF are {ro_count(len(c['anaf']), 'licitație', 'licitații')} cu bunuri din județ în următoarele {ANAF_AHEAD} zile."
    p.append(lead + "</p>")

    if c["bc_new"]:
        p.append("<h2>Licitații noi la Primăria Brașov</h2>")
        p.append("<ul>" + "".join(_bc_row(d) for d in c["bc_new"]) + "</ul>")
    if c["hcl_new"]:
        p.append("<h2>Proiecte noi în dezbatere publică la Brașov</h2>")
        p.append("<p>Oricine poate trimite propuneri până la termenul trecut la fiecare proiect. Documentele și "
                 f"explicațiile pe înțeles sunt pe pagina {prim}.</p>")
        p.append("<ul>" + "".join(_bc_row(d) for d in c["hcl_new"]) + "</ul>")
    if c["new_sites"]:
        p.append("<h2>Anunțuri noi ale primăriilor din județ</h2>")
        p.append("<ul>" + "".join(_site_row(it) for it in c["new_sites"]) + "</ul>")
    if c["soon_sites"] or c["bc_soon"]:
        p.append("<h2>Termene care expiră săptămâna aceasta</h2>")
        p.append("<ul>" + "".join(_bc_row(d) for d in c["bc_soon"]) + "".join(_site_row(it) for it in c["soon_sites"]) + "</ul>")
    if c["anaf"]:
        p.append(f"<h2>Bunuri scoase la licitație de ANAF în următoarele {ANAF_AHEAD} zile</h2>")
        p.append("<ul>" + "".join(
            f'<li><a href="{escape(it["url"])}" rel="noopener nofollow" target="_blank">{escape(it["title"])}</a>'
            + (f" – licitație pe {fmt_day(it['published'])}" if it.get("published") else "") + "</li>" for it in c["anaf"]) + "</ul>")

    p.append("<h2>De unde sunt anunțurile</h2>")
    p.append("<p>Le citim de două ori pe săptămână de pe site-urile celor 58 de primării din județ, de pe brasovcity.ro "
             "și din fluxurile ANAF. Titlurile sunt cele oficiale, iar fiecare link duce la anunțul original: "
             f"verifică acolo condițiile și documentele înainte să depui o ofertă. Toate anunțurile active sunt pe {lic}.</p>")

    end = date.fromisoformat(c["end"])
    st = date.fromisoformat(c["start"])
    span = f"{st.day}–{fmt_day(c['end'])}" if st.month == end.month else f"{fmt_day(c['start'])} – {fmt_day(c['end'])}"
    title = f"Licitații și achiziții noi în județul Brașov ({span})"
    excerpt = (f"{ro_count(total_new, 'anunț nou', 'anunțuri noi')} ale primăriilor din județul Brașov în ultimele 7 zile"
               + (f", {ro_count(n_soon, 'termen', 'termene')} care expiră curând" if n_soon else "")
               + ". Lista cu linkurile oficiale.")
    return {
        "id": report_id(today),
        "title": title,
        "slug": f"licitatii-achizitii-brasov-{end.isoformat()}",
        "excerpt": excerpt,
        "meta_description": excerpt[:155],
        "content": "\n".join(p),
        "category": "economie",
        "type": "local",
        "source": "Primăriile din județul Brașov",
        "source_url": "https://kronpapir.ro" + business.LICITATII_PATH,
        "url": "https://kronpapir.ro" + business.LICITATII_PATH,
        "source_type": "date_oficiale",
        "keywords": ["licitații Brașov", "achiziții publice Brașov", "terenuri de vânzare Brașov", "licitații ANAF Brașov"],
        "date": datetime.now(TZ).isoformat(timespec="seconds"),
        "report_week": c["end"],
    }, total_new + n_soon


def verify(article, c):
    """Numerele din articol care nu vin din date (lista goală = trecut)."""
    allowed_text = " ".join(str(v) for k in ("new_sites", "soon_sites", "anaf", "bc_new", "bc_soon", "hcl_new")
                            for it in c[k] for v in (it.get("title"), it.get("place"), it.get("dl"),
                                                     it.get("deadline"), it.get("published")) if v)
    vals = set(_NUM.findall(allowed_text))
    for k in ("new_sites", "soon_sites", "anaf", "bc_new", "bc_soon", "hcl_new"):
        vals.add(str(len(c[k])))
    vals |= {str(len(c["soon_sites"]) + len(c["bc_soon"])), str(len(c["new_sites"]) + len(c["bc_new"]) + len(c["hcl_new"])),
             str(WINDOW), str(ANAF_AHEAD), "58"}
    for d in (c["start"], c["end"]):
        vals |= {d[:4], str(int(d[8:10]))}
    for k in ("new_sites", "soon_sites", "anaf", "bc_new", "bc_soon", "hcl_new"):
        for it in c[k]:
            for f in ("dl", "deadline", "published"):
                if it.get(f):
                    vals.add(str(int(str(it[f])[8:10])))
    allowed = set()
    for v in vals:
        allowed |= _norm_number(v)
    text = " | ".join(re.sub(r"<[^>]+>", " | ", re.sub(r'href="[^"]*"', "", article.get(k) or ""))
                      for k in ("title", "excerpt", "content"))
    return [m.group(0) for m in _NUM.finditer(text) if not (_norm_number(m.group(0)) & allowed)]


def run(data_dir=None, today=None, dry_run=False):
    data_root = Path(data_dir or BASE_DIR / "data")
    today = today or datetime.now(TZ).date()
    c = collect(_load(data_root / "business" / "licitatii" / "store.json"),
                _load(data_root / "brasovcity" / "store.json"), today)
    article, n = render(c, today)
    if n < MIN_ITEMS:
        raise RuntimeError(f"Doar {n} anunțuri pentru săptămâna până pe {today}; nu fac raportul.")
    bad = verify(article, c)
    if bad:
        raise RuntimeError(f"Numere care nu vin din anunțuri: {bad[:10]}; nu public.")
    if (editorial_store.PROCESSED_DIR / f"{article['id']}.json").exists():
        log.info("Raportul de licitații %s există deja; nu-l suprascriu.", article["id"])
        return article, False
    if dry_run:
        return article, False
    article["fact_check"] = {"scor": 10, "erori_blocante": [], "recomandari": [],
                             "model": "verificare deterministă (fiecare număr provine din anunțurile oficiale)"}
    editorial_store.publish_automatic(article)
    return article, True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raportul săptămânal de licitații din județul Brașov")
    parser.add_argument("--dry-run", action="store_true", help="afișează articolul, nu publică")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--today", default=None, help="ultima zi din fereastra de 7 zile (AAAA-LL-ZZ)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    today = date.fromisoformat(args.today) if args.today else None
    try:
        article, saved = run(data_dir=args.data_dir, today=today, dry_run=args.dry_run)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1
    if args.dry_run:
        print(article["title"])
        print(article["content"])
    log.info("Raport licitații %s: %s", article["id"], "publicat" if saved else "nepublicat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
