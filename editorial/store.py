"""
Stocarea articolelor după status.

- Ciornele și articolele respinse stau în data/drafts/<id>.json. Nimic de pe site
  (pagini, sitemap, RSS, API, Facebook) nu citește acest folder, deci o ciornă nu
  poate ajunge publică din greșeală.
- Articolele publicate stau, ca până acum, în data/processed/<id>.json, cu
  status = "published".

Câmpuri adăugate de acest modul:
  status         draft | rejected | published
  source_type    date_oficiale | editorial | rezumat_presa | rescriere_veche
  reviewed_by    cine a verificat (de ex. "George"); gol = neverificat
  reviewed_at    ISO datetime al verificării
  updated        ISO datetime al ultimei modificări (dateModified)
"""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("KronPapir.editorial")

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DRAFTS_DIR = BASE_DIR / "data" / "drafts"

DRAFT_STATUSES = ("draft", "rejected")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _write_json_atomic(path: Path, data: dict):
    """Scrie JSON atomic, ca serverul web să nu citească niciodată un fișier pe jumătate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _safe_id(article_id: str) -> str:
    if not article_id or "/" in article_id or "\\" in article_id or article_id.startswith("."):
        raise ValueError(f"ID de articol invalid: {article_id!r}")
    return article_id


def save_draft(article: dict, reason: str = "") -> dict:
    """Salvează un articol ca ciornă pentru George. Întoarce articolul salvat."""
    article = dict(article)
    article.setdefault("id", str(uuid.uuid4()))
    article["status"] = "draft"
    article.setdefault("created_at", _now())
    article["updated"] = _now()
    if reason:
        article["draft_reason"] = reason
    _write_json_atomic(DRAFTS_DIR / f"{_safe_id(article['id'])}.json", article)
    logger.info(f"📝 Ciornă salvată: {article.get('title', '')[:60]} ({article['id']})")
    return article


def list_drafts(status: str = "draft") -> list:
    """Ciornele (sau articolele respinse), cele mai noi primele."""
    items = []
    if not DRAFTS_DIR.exists():
        return items
    for path in DRAFTS_DIR.glob("*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                art = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Nu pot citi ciorna {path.name}: {e}")
            continue
        if status and art.get("status") != status:
            continue
        items.append(art)
    items.sort(key=lambda a: a.get("updated") or a.get("date") or "", reverse=True)
    return items


def get_draft(article_id: str):
    path = DRAFTS_DIR / f"{_safe_id(article_id)}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def publish_draft(article_id: str, reviewed_by: str) -> dict:
    """Publică o ciornă verificată de un om: o mută în data/processed cu reviewed_by/at."""
    if not reviewed_by:
        raise ValueError("Publicarea unei ciorne cere numele celui care a verificat-o.")
    article = get_draft(article_id)
    if article is None:
        raise FileNotFoundError(article_id)
    now = _now()
    article["status"] = "published"
    article["reviewed_by"] = reviewed_by
    article["reviewed_at"] = now
    article["updated"] = now
    article.setdefault("date", now)
    article.pop("draft_reason", None)
    _write_json_atomic(PROCESSED_DIR / f"{_safe_id(article['id'])}.json", article)
    (DRAFTS_DIR / f"{article['id']}.json").unlink(missing_ok=True)
    logger.info(f"✅ Publicat după verificare ({reviewed_by}): {article.get('title', '')[:60]}")
    return article


def reject_draft(article_id: str, reason: str = "") -> dict:
    article = get_draft(article_id)
    if article is None:
        raise FileNotFoundError(article_id)
    article["status"] = "rejected"
    article["rejected_at"] = _now()
    article["rejection_reason"] = reason
    _write_json_atomic(DRAFTS_DIR / f"{_safe_id(article['id'])}.json", article)
    return article


def publish_automatic(article: dict) -> dict:
    """Publică direct un articol de date oficiale care a trecut fact-check-ul (scor ≥ 8).

    Refuză orice alt tip de articol: editorialele și subiectele sensibile trec doar prin ciornă.
    """
    if article.get("source_type") != "date_oficiale":
        raise ValueError("Publicarea automată e permisă doar pentru articole din date oficiale.")
    score = (article.get("fact_check") or {}).get("scor")
    if score is None or score < 8:
        raise ValueError(f"Scor de fact-check insuficient pentru publicare automată: {score}")
    article = dict(article)
    article.setdefault("id", str(uuid.uuid4()))
    now = _now()
    article["status"] = "published"
    article.setdefault("date", now)
    article["updated"] = now
    article["reviewed_by"] = ""
    article["reviewed_at"] = ""
    _write_json_atomic(PROCESSED_DIR / f"{_safe_id(article['id'])}.json", article)
    return article


def mark_reviewed(article: dict, reviewed_by: str) -> dict:
    """George a verificat un articol deja publicat: schimbă eticheta și dateModified."""
    if not reviewed_by:
        raise ValueError("reviewed_by este obligatoriu.")
    article = dict(article)
    now = _now()
    article["reviewed_by"] = reviewed_by
    article["reviewed_at"] = now
    article["updated"] = now
    return article
