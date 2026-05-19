#!/usr/bin/env python3
"""
KronPapir — Rescrie batch articolele procesate cu noul prompt editorial.

Utilizare:
    python rewrite_batch.py --days 5          # Rescrie articolele din ultimele 5 zile
    python rewrite_batch.py --days 5 --dry-run  # Preview fără rescriare
    python rewrite_batch.py --limit 10        # Rescrie doar 10 articole (test)
"""

import os
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger("KronPapir.BatchRewrite")

BASE_DIR = Path(__file__).parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
BACKUP_DIR = BASE_DIR / "data" / "backup_before_rewrite"


def run_batch(days=5, limit=None, dry_run=False):
    """Rescrie articolele procesate din ultimele N zile cu noul prompt."""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not dry_run:
        logger.error("ANTHROPIC_API_KEY nu e setat.")
        return

    # Găsește articolele din ultimele N zile
    cutoff = time.time() - days * 86400
    files = [f for f in PROCESSED_DIR.glob("*.json") if f.stat().st_mtime > cutoff]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    if limit:
        files = files[:limit]

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Articole de rescris: {len(files)} (ultimele {days} zile)")

    if not files:
        logger.info("Nimic de rescris.")
        return

    if dry_run:
        for f in files:
            with open(f, 'r', encoding='utf-8') as fh:
                art = json.load(fh)
            logger.info(f"  {art.get('title', f.name)[:70]}")
        return

    # Backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for f in files:
        backup_path = BACKUP_DIR / f.name
        if not backup_path.exists():
            import shutil
            shutil.copy2(f, backup_path)
    logger.info(f"Backup creat în {BACKUP_DIR}/")

    # Init rewriter
    from ai.rewriter import ArticleRewriter
    rewriter = ArticleRewriter(
        api_key=api_key,
        model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
    )

    rewritten_count = 0
    failed_count = 0
    start_time = time.time()

    for idx, f in enumerate(files, 1):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                original = json.load(fh)

            title = original.get('title', 'Fără titlu')
            logger.info(f"[{idx}/{len(files)}] {title[:60]}...")

            # Pregătim articolul brut pentru rewriter
            raw_article = {
                'title': title,
                'content': original.get('content', ''),
                'source': original.get('source', ''),
                'url': original.get('url', ''),
                'date': original.get('date', ''),
                'image_url': original.get('image', ''),
                'image': original.get('image', ''),
                'category': original.get('category', ''),
            }

            result = rewriter.rewrite_article(raw_article)

            if result:
                # Păstrăm ID-ul original și alte câmpuri
                result['id'] = original['id']
                result['date'] = original.get('date', result.get('date', ''))
                result['image'] = result.get('image') or original.get('image', '')
                result['image_source'] = original.get('image_source', result.get('source', ''))

                with open(f, 'w', encoding='utf-8') as fh:
                    json.dump(result, fh, ensure_ascii=False, indent=2)

                rewritten_count += 1
                logger.info(f"  ✅ Rescris: {result['title'][:60]}")
            else:
                failed_count += 1
                logger.warning(f"  ⚠️ Eșuat: {title[:60]}")

        except Exception as e:
            failed_count += 1
            logger.error(f"  ❌ Eroare: {e}")

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"Batch finalizat în {elapsed:.0f}s")
    logger.info(f"  Rescrise: {rewritten_count}")
    logger.info(f"  Eșuate: {failed_count}")
    logger.info(f"  Backup: {BACKUP_DIR}/")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KronPapir — Batch rewrite articole")
    parser.add_argument('--days', type=int, default=5, help='Rescrie articolele din ultimele N zile (default: 5)')
    parser.add_argument('--limit', type=int, default=None, help='Limită maximă articole')
    parser.add_argument('--dry-run', action='store_true', help='Preview fără rescriare')
    args = parser.parse_args()

    run_batch(days=args.days, limit=args.limit, dry_run=args.dry_run)
