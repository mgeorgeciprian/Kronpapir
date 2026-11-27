"""Anunțuri de achiziții, terenuri și vânzări ANAF din județul Brașov.

Surse (o rulare pe zi, KronPapirBot, robots.txt respectat, pauză de 2 s):
- paginile de anunțuri ale celor 58 de primării din județ (config/primarii_brasov.yaml):
  linkurile noi care par cereri de ofertă, licitații sau vânzări de terenuri;
- vânzările de bunuri ANAF, doar din sitemap-ul și fluxurile RSS ale elicitatii.anaf.ro
  (termenii platformei interzic colectarea paginilor), păstrate doar când descrierea pomenește
  o localitate din județul Brașov.
Nu preluăm documentele și nici date de contact. Rezultatul: data/business/licitatii/store.json.

Rulare: python -m sources.licitatii_bv [--only sites,anaf] [--dry-run]
"""
import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from sources.licitatii.anaf_sales import AnafSalesClient
from sources.licitatii.sites import SitesClient

log = logging.getLogger("sources.licitatii_bv")

TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
SITES_FILE = BASE_DIR / "config" / "primarii_brasov.yaml"
KEEP_DAYS = 30          # cât păstrăm (și afișăm) un anunț de pe site-ul unei primării
MAX_AGE_DAYS = 14       # un anunț publicat acum mai mult de 14 zile nu mai e luat în seamă
ANAF_BASE = "https://elicitatii.anaf.ro"


def store_path(data_dir=None):
    return Path(data_dir or BASE_DIR / "data") / "business" / "licitatii" / "store.json"


def load_store(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"items": {}, "baseline": {}}


def write_store(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def too_old(item, today, max_age_days=MAX_AGE_DAYS):
    """Anunț cu dată reală (nu ziua în care l-am găsit) mai veche de max_age_days."""
    when = str(item.get("published") or "")[:10]
    if not when or item.get("date_guessed"):
        return False
    return when < (date.fromisoformat(today) - timedelta(days=max_age_days)).isoformat()


def merge(store, fresh, source, today, keep_days=KEEP_DAYS):
    """Adaugă doar elementele noi și recente (cel mult MAX_AGE_DAYS); cele cunoscute nu se mai procesează.

    Prima rulare a unei surse doar le reține, fără să le marcheze „nou”.
    """
    items = store.setdefault("items", {})
    baseline = store.setdefault("baseline", {})
    first_run = not baseline.get(source)
    seen_now = set()
    new = 0
    for it in fresh:
        seen_now.add(it["id"])
        old = items.get(it["id"])
        if old:
            old["last_seen"] = today  # cunoscut: nu-l mai procesăm
            continue
        if too_old(it, today):
            continue
        it = dict(it, source=source, first_seen=today, last_seen=today, is_new=not first_run)
        items[it["id"]] = it
        new += 0 if first_run else 1
    baseline[source] = baseline.get(source) or today
    cut = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    for key in list(items):
        it = items[key]
        if it.get("source") != source:
            continue
        if source == "anaf" and key not in seen_now:
            del items[key]  # bunul a ieșit din fluxuri: vândut sau retras
        elif source == "sites" and it.get("first_seen", "") < cut:
            del items[key]
    return new


def fetch_sites(today, known_urls=()):
    cfg = yaml.safe_load(SITES_FILE.read_text(encoding="utf-8"))
    client = SitesClient(delay=2.0, timeout=30)
    items = list(client.items(cfg["sites"], date.fromisoformat(today), cfg.get("county", "BRASOV"),
                              known_urls=set(known_urls)))
    return items, {"failed": client.failed, "robots_blocked": client.blocked, "sites": len(cfg["sites"])}


def fetch_anaf():
    client = AnafSalesClient(ANAF_BASE, delay=2.0)
    items = [i for i in client.items() if i.get("county") == "BRASOV"]
    return items, {}


def run(data_dir=None, only=("sites", "anaf"), dry_run=False, now=None):
    now = now or datetime.now(TZ)
    today = now.date().isoformat()
    path = store_path(data_dir)
    store = load_store(path)
    report = {}
    known = {i.get("url") for i in (store.get("items") or {}).values()}
    for source, fetch in (("sites", lambda: fetch_sites(today, known)), ("anaf", fetch_anaf)):
        if source not in only:
            continue
        try:
            fresh, info = fetch()
        except Exception as e:  # o sursă căzută nu oprește cealaltă
            log.error("%s a eșuat: %s", source, e)
            report[source] = {"error": str(e)}
            continue
        new = 0 if dry_run else merge(store, fresh, source, today)
        report[source] = dict(info, found=len(fresh), new=new)
        log.info("%s: %d găsite, %d noi %s", source, len(fresh), new,
                 json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in info.items()}, ensure_ascii=False))
    if not dry_run:
        store["updated"] = now.isoformat(timespec="seconds")
        store["last_report"] = report
        write_store(path, store)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Licitații și anunțuri din județul Brașov")
    parser.add_argument("--only", default="sites,anaf")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    report = run(data_dir=args.data_dir, only=tuple(args.only.split(",")), dry_run=args.dry_run)
    return 0 if any("error" not in r for r in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
