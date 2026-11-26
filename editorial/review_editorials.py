"""Verificarea în bloc a editorialelor vechi, cerută de George (aprobare condiționată de fact-check).

Editorialele nu și-au păstrat linkurile surselor, doar numele publicațiilor (`sources_used`).
Le reconstituim din știrile brute din data/articles/ (și din arhivele lunare data/archives/raw_*.tar.gz):
știrile acelor publicații din cele 36 de ore dinaintea editorialului, ordonate după cât seamănă cu textul.
Editorul de fact-check (config/agents.yaml: editor-fact-check) verifică faptele din editorial față de ele.

Se aprobă (reviewed_by = George, plus `review_method`) doar editorialele cu scor ≥ 8 și fără erori blocante.
Celelalte rămân cu noindex, iar rezultatul se scrie în data/reviews/ pentru George.

    python -m editorial.review_editorials --days 14 [--limit N] [--dry-run] [--apply]
Fără --apply doar raportează.
"""
import argparse
import gzip
import json
import logging
import os
import re
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

from ai import costs
from ai.factcheck_llm import SCHEMA, _prompt
from editorial import presentation as pres
from editorial import store as editorial_store
from editorial.factcheck import plain

log = logging.getLogger("editorial.review_editorials")

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR = BASE_DIR / "data" / "articles"
ARCHIVE_DIR = BASE_DIR / "data" / "archives"
REVIEWS_DIR = BASE_DIR / "data" / "reviews"
AGENT = "editor-fact-check"
MAX_SOURCES = 6
SOURCE_CHARS = 2500
WINDOW_HOURS = 36
MIN_SCORE = 8
METHOD = "aprobat în bloc de editor, după fact-check automat față de știrile sursă"

EDITORIAL_NOTE = (
    "ATENȚIE: textul KronPapir este un EDITORIAL (analiză) scris din mai multe știri ale zilei, nu rescrierea uneia "
    "singure. Sursele de mai jos sunt reconstituite (știrile acelor publicații din ziua respectivă), deci pot lipsi "
    "unele. Opiniile, interpretările și concluziile prezentate clar ca opinie nu sunt erori. Verifică FAPTELE: nume, "
    "funcții, cifre, date, citate, evenimente. Un fapt care nu apare în nicio sursă de mai jos este eroare blocantă "
    "(„neverificabil în sursă”)."
)


def _stems(text):
    return {w[:5] for w in re.findall(r"\w+", text.lower()) if len(w) > 4}


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def _load_raw(sources):
    """Toate știrile brute ale publicațiilor date, din fișiere și din arhivele lunare."""
    items = []
    for path in RAW_DIR.glob("*/*.json"):
        try:
            a = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if a.get("source") in sources:
            items.append(a)
    for tar_path in ARCHIVE_DIR.glob("raw_*.tar.gz"):
        try:
            with tarfile.open(tar_path) as tar:
                for member in tar:
                    if not member.isfile() or not member.name.endswith(".json"):
                        continue
                    try:
                        a = json.load(tar.extractfile(member))
                    except (ValueError, OSError):
                        continue
                    if a.get("source") in sources:
                        items.append(a)
        except (tarfile.TarError, OSError) as e:
            log.warning("Arhivă ilizibilă %s: %s", tar_path.name, e)
    seen, unique = set(), []
    for a in items:
        key = a.get("url") or a.get("title")
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique


def candidate_sources(editorial, raw, limit=MAX_SOURCES):
    """Știrile publicațiilor folosite, din fereastra editorialului, ordonate după asemănare."""
    when = _parse_date(editorial.get("date"))
    used = set(editorial.get("sources_used") or [])
    text = _stems(f"{editorial.get('title', '')} {plain(editorial.get('content') or '')}")
    scored = []
    for a in raw:
        if used and a.get("source") not in used:
            continue
        d = _parse_date(a.get("created_at") or a.get("date"))
        if when and d and not (when - timedelta(hours=WINDOW_HOURS) <= d <= when + timedelta(hours=1)):
            continue
        body = _stems(f"{a.get('title', '')} {plain(a.get('content') or '')}")
        if not body:
            continue
        scored.append((len(text & body) / (len(body) ** 0.5), a))
    scored.sort(key=lambda x: -x[0])
    return [a for _, a in scored[:limit]]


def build_message(editorial, sources):
    parts = [EDITORIAL_NOTE, ""]
    for i, s in enumerate(sources, 1):
        parts.append(f"TEXTUL SURSĂ {i} ({s.get('source') or '?'}, {s.get('url') or ''}):\n"
                     f"Titlu: {s.get('title') or ''}\n{plain(s.get('content') or '')[:SOURCE_CHARS]}\n")
    parts.append(f"EDITORIALUL KRONPAPIR:\nTitlu: {editorial.get('title') or ''}\n"
                 f"Rezumat: {plain(editorial.get('excerpt') or '')}\n{plain(editorial.get('content') or '')}")
    return "\n".join(parts)


def check(client, cfg, system, editorial, sources):
    now = datetime.now()
    costs.check(cfg, now)
    msg = client.beta.messages.create(
        model=cfg["model"],
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": build_message(editorial, sources)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
    )
    usd, _ = costs.record(AGENT, cfg["model"], msg.usage, now)
    if msg.stop_reason != "end_turn":
        return None, usd
    text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
    data = json.loads(text)
    data["scor"] = max(1, min(10, int(data.get("scor") or 1)))
    data["model"] = cfg["model"]
    return data, usd


def passes(result):
    return bool(result) and result["scor"] >= MIN_SCORE and not result.get("erori_blocante")


def approve(path, article, result, reviewer):
    article = editorial_store.mark_reviewed(article, reviewed_by=reviewer)
    article["review_method"] = METHOD
    article["fact_check"] = {k: result[k] for k in ("scor", "erori_blocante", "recomandari", "model")}
    stem = path.name.removesuffix(".gz").removesuffix(".json")
    editorial_store._write_json_atomic(PROCESSED_DIR / f"{stem}.json", article)
    (PROCESSED_DIR / f"{stem}.json.gz").unlink(missing_ok=True)


def unreviewed_editorials(days):
    cut = (datetime.now() - timedelta(days=days)).isoformat()[:10]
    out = []
    for path in PROCESSED_DIR.glob("*.json*"):
        try:
            raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
            a = json.loads(raw)
        except (ValueError, OSError):
            continue
        if pres.source_type(a) == "editorial" and not pres.is_reviewed(a) and str(a.get("date", ""))[:10] >= cut:
            out.append((path, a))
    out.sort(key=lambda x: str(x[1].get("date")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="marchează ca verificate editorialele care trec")
    ap.add_argument("--dry-run", action="store_true", help="doar arată sursele găsite, fără apeluri LLM")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    todo = unreviewed_editorials(args.days)
    if args.limit:
        todo = todo[:args.limit]
    names = {n for _, a in todo for n in (a.get("sources_used") or [])}
    raw = _load_raw(names)
    log.info("%d editoriale neverificate, %d știri brute din %s", len(todo), len(raw), sorted(names))

    cfg = costs.settings(AGENT, "claude-sonnet-5-5")
    system = _prompt()
    client = None
    reviewer = os.getenv("EDITOR_NAME", "George")
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REVIEWS_DIR / f"editoriale-{datetime.now():%Y%m%d-%H%M}.json"
    report, total = [], 0.0
    for path, a in todo:
        sources = candidate_sources(a, raw)
        entry = {"id": a.get("id"), "slug": a.get("slug"), "title": a.get("title"), "date": a.get("date"),
                 "sources": [s.get("url") for s in sources]}
        if args.dry_run or not sources:
            entry["status"] = "fara_surse" if not sources else "dry_run"
            report.append(entry)
            log.info("%s | %d surse | %s", entry["status"], len(sources), str(a.get("title"))[:60])
            continue
        if client is None:
            from anthropic import Anthropic
            client = Anthropic()
        try:
            result, usd = check(client, cfg, system, a, sources)
        except costs.BudgetExceeded as e:
            log.warning("%s Mă opresc.", e)
            break
        except Exception as e:
            log.warning("Fact-check eșuat pentru %s: %s", a.get("id"), e)
            result, usd = None, 0.0
        total += usd
        entry["result"] = result
        ok = passes(result)
        entry["status"] = ("aprobat" if args.apply else "ar_trece") if ok else "picat"
        if ok and args.apply:
            approve(path, a, result, reviewer)
        report.append(entry)
        editorial_store._write_json_atomic(report_path, {"total_usd": round(total, 4), "items": report})
        log.info("%s | scor %s | %d erori | %.3f USD | %s", entry["status"], (result or {}).get("scor"),
                 len((result or {}).get("erori_blocante") or []), usd, str(a.get("title"))[:60])
    editorial_store._write_json_atomic(report_path, {"total_usd": round(total, 4), "items": report})
    counts = {}
    for e in report:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    log.info("Gata: %s, cost %.2f USD, raport %s", counts, total, report_path)


if __name__ == "__main__":
    main()
