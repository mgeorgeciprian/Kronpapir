"""Verificare săptămânală PageSpeed Insights pentru paginile principale KronPapir.

Rulează din cron (duminica), cu PAGESPEED_API_KEY din .env:
    python -m seo.pagespeed

Scrie data/seo/pagespeed/<YYYY-MM-DD>.json și un rezumat în log, cu alertă când o
pagină scade cu cel puțin 10 puncte față de rularea precedentă sau are sub 50.
Cheia se trimite în header (X-Goog-Api-Key), nu în URL, ca să nu ajungă în loguri.
Nu trimite nimic nicăieri: raportul rămâne pe server.
"""
import argparse
import json
import logging
import os
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from editorial import presentation as pres
from sources.http import FetchError, PoliteClient

log = logging.getLogger("seo.pagespeed")

TZ = ZoneInfo("Europe/Bucharest")
ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = ROOT / "data" / "seo" / "pagespeed"
API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
SITE = "https://kronpapir.ro"
PAGES = ["/", "/local", "/editoriale", "/locuri-de-munca-brasov"]
STRATEGIES = ("mobile", "desktop")
DROP_ALERT = 10   # puncte pierdute față de rularea precedentă
LOW_SCORE = 50    # sub acest scor, pagina e „slabă” după Google

# Lighthouse (laborator) și CrUX (date reale de la vizitatori, când Google are destule)
LAB_AUDITS = {
    "lcp_ms": "largest-contentful-paint",
    "cls": "cumulative-layout-shift",
    "tbt_ms": "total-blocking-time",
    "fcp_ms": "first-contentful-paint",
}
FIELD_METRICS = {
    "lcp_ms": "LARGEST_CONTENTFUL_PAINT_MS",
    "inp_ms": "INTERACTION_TO_NEXT_PAINT",
    "cls": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
}


def newest_article_path(processed_dir=PROCESSED_DIR):
    """Cel mai nou articol publicat și indexabil: îl testăm ca șablon de articol."""
    best = None
    for f in processed_dir.glob("*.json"):
        try:
            a = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if a.get("status") == "draft" or not a.get("slug") or pres.should_noindex(a):
            continue
        if best is None or (a.get("date") or "") > (best.get("date") or ""):
            best = a
    return f"/stiri/{best['slug']}" if best else None


def summarize(data):
    """Din răspunsul PSI păstrăm doar cifrele care contează."""
    lh = data.get("lighthouseResult") or {}
    score = ((lh.get("categories") or {}).get("performance") or {}).get("score")
    audits = lh.get("audits") or {}
    lab = {}
    for key, audit_id in LAB_AUDITS.items():
        value = (audits.get(audit_id) or {}).get("numericValue")
        lab[key] = round(value, 3 if key == "cls" else 0) if value is not None else None
    field = {}
    metrics = (data.get("loadingExperience") or {}).get("metrics") or {}
    for key, metric_id in FIELD_METRICS.items():
        m = metrics.get(metric_id) or {}
        p75 = m.get("percentile")
        if p75 is not None and key == "cls":
            p75 = p75 / 100  # CrUX dă CLS înmulțit cu 100
        field[key] = {"p75": p75, "category": m.get("category")} if p75 is not None else None
    return {
        "score": round(score * 100) if score is not None else None,
        "lab": lab,
        "field": field if any(field.values()) else None,
    }


def previous_report(out_dir, today):
    reports = sorted(p for p in out_dir.glob("*.json") if p.stem < today)
    if not reports:
        return None
    try:
        return json.loads(reports[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def alerts(results, previous):
    """Liste de texte: pagini slabe și scăderi față de săptămâna trecută."""
    old = {(r["path"], r["strategy"]): r.get("score") for r in (previous or {}).get("results", [])}
    out = []
    for r in results:
        score = r.get("score")
        if score is None:
            continue
        label = f"{r['path']} ({r['strategy']})"
        before = old.get((r["path"], r["strategy"]))
        if before is not None and before - score >= DROP_ALERT:
            out.append(f"{label}: a scăzut de la {before} la {score}")
        elif score < LOW_SCORE:
            out.append(f"{label}: scor {score}, sub {LOW_SCORE}")
    return out


def run(api_key, client=None, out_dir=OUT_DIR, processed_dir=PROCESSED_DIR, now=None):
    now = now or datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")
    client = client or PoliteClient(timeout=120, retries=2, backoff=30)
    pages = list(PAGES)
    article = newest_article_path(processed_dir)
    if article:
        pages.append(article)

    results = []
    for path in pages:
        for strategy in STRATEGIES:
            query = urllib.parse.urlencode({"url": SITE + path, "strategy": strategy,
                                            "category": "performance", "locale": "ro"})
            entry = {"path": path, "strategy": strategy}
            try:
                data = client.request_json(f"{API}?{query}", headers={"X-Goog-Api-Key": api_key})
                entry.update(summarize(data))
            except FetchError as e:
                entry["error"] = str(e)[:300]
                log.warning("PageSpeed a eșuat pentru %s (%s): %s", path, strategy, entry["error"])
            results.append(entry)

    report = {"checked_at": now.isoformat(timespec="seconds"), "results": results}
    report["alerts"] = alerts(results, previous_report(out_dir, today))

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"{today}.json.tmp"
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_dir / f"{today}.json")

    for r in results:
        if "error" in r:
            continue
        lab = r["lab"]
        log.info("%-40s %-7s scor %s | LCP %s ms | CLS %s | TBT %s ms", r["path"], r["strategy"],
                 r["score"], lab["lcp_ms"], lab["cls"], lab["tbt_ms"])
    for text in report["alerts"]:
        log.warning("ALERTĂ PageSpeed: %s", text)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    api_key = os.environ.get("PAGESPEED_API_KEY", "").strip()
    if not api_key:
        log.error("PAGESPEED_API_KEY lipsește din .env; nu rulez.")
        return 2
    report = run(api_key)
    failed = sum(1 for r in report["results"] if "error" in r)
    log.info("Gata: %d verificări, %d eșuate, %d alerte.",
             len(report["results"]), failed, len(report["alerts"]))
    return 1 if failed == len(report["results"]) else 0


if __name__ == "__main__":
    sys.exit(main())
