#!/usr/bin/env python3
"""
KronPapir - Archive, cleanup & restore pentru articole.

Brute (data/articles/):
  - Strip HTML după 3 zile
  - Arhivare tar.gz după 5 zile, originale șterse

Procesate (data/processed/):
  - Comprimare individuală .json → .json.gz după 30 zile
  - Rămân disponibile — load_articles() le citește transparent
  - Dezarhivare (restore) la cerere

Utilizare:
    python archive_articles.py                        # Rulează tot (strip + archive brute + compress procesate)
    python archive_articles.py --dry-run              # Preview fără modificări
    python archive_articles.py --raw-only             # Doar brute
    python archive_articles.py --processed-only       # Doar procesate
    python archive_articles.py restore                # Decomprima TOATE .json.gz înapoi în .json
    python archive_articles.py restore <id>           # Decomprima un singur articol
    python archive_articles.py status                 # Arată statistici spațiu
"""

import os
import sys
import json
import gzip
import time
import tarfile
import argparse
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger("KronPapir.Archive")

BASE_DIR = Path(__file__).parent
ARTICLES_DIR = BASE_DIR / "data" / "articles"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
ARCHIVE_DIR = BASE_DIR / "data" / "archives"

# Defaults
RAW_STRIP_DAYS = 3
RAW_ARCHIVE_DAYS = 5
PROCESSED_COMPRESS_DAYS = 30


# ─── BRUTE: strip HTML ──────────────────────────────────────────────

def strip_html(strip_days=RAW_STRIP_DAYS, dry_run=False):
    """Strip original_text HTML din articolele brute mai vechi de N zile."""
    now = time.time()
    cutoff = now - strip_days * 86400
    stripped = 0
    saved_bytes = 0

    for f in ARTICLES_DIR.glob("**/*.json"):
        if f.name.startswith("_") or "processed" in f.name:
            continue
        if f.stat().st_mtime > cutoff:
            continue

        try:
            with open(f, 'r', encoding='utf-8') as fh:
                raw = fh.read()

            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            modified = False

            for art in items:
                orig = art.get('original_text', '')
                if orig and len(orig) > 500:
                    saved_bytes += len(orig.encode('utf-8'))
                    art['original_text'] = ''
                    art['_html_stripped'] = True
                    modified = True

            if modified:
                if not dry_run:
                    new_data = json.dumps(
                        data if isinstance(data, list) else items[0],
                        ensure_ascii=False, indent=2
                    )
                    with open(f, 'w', encoding='utf-8') as fh:
                        fh.write(new_data)
                stripped += 1

        except Exception as e:
            logger.debug(f"Error processing {f.name}: {e}")

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Strip HTML: {stripped} fișiere, "
                f"eliberat ~{saved_bytes/1024/1024:.1f} MB")
    return stripped, saved_bytes


# ─── BRUTE: arhivare tar.gz ─────────────────────────────────────────

def archive_raw(archive_days=RAW_ARCHIVE_DAYS, dry_run=False):
    """Comprimă articolele brute mai vechi de N zile în tar.gz lunar, apoi șterge originalele."""
    now = time.time()
    cutoff = now - archive_days * 86400
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    by_group = {}
    for f in ARTICLES_DIR.glob("**/*.json"):
        if f.name.startswith("_") or "processed" in f.name:
            continue
        if f.stat().st_mtime > cutoff:
            continue

        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        source = f.parent.name if f.parent != ARTICLES_DIR else "misc"
        group_key = f"{source}_{mtime.strftime('%Y-%m')}"

        if group_key not in by_group:
            by_group[group_key] = []
        by_group[group_key].append(f)

    if not by_group:
        logger.info("Brute: nimic de arhivat.")
        return 0, 0

    archived_files = 0
    archived_size = 0

    for group_key, files in sorted(by_group.items()):
        archive_path = ARCHIVE_DIR / f"raw_{group_key}.tar.gz"
        total_size = sum(f.stat().st_size for f in files)

        if dry_run:
            logger.info(f"  [DRY-RUN] {len(files)} fișiere "
                        f"({total_size/1024/1024:.1f} MB) -> {archive_path.name}")
            archived_files += len(files)
            archived_size += total_size
            continue

        try:
            # Append dacă arhiva există deja
            mode = "a:gz" if archive_path.exists() else "w:gz"
            with tarfile.open(archive_path, mode) as tar:
                for f in files:
                    arcname = f"{f.parent.name}/{f.name}"
                    tar.add(str(f), arcname=arcname)

            for f in files:
                f.unlink()

            archived_files += len(files)
            archived_size += total_size
            compressed_size = archive_path.stat().st_size
            ratio = compressed_size * 100 // total_size if total_size else 0
            logger.info(f"  Arhivat {len(files)} fișiere -> {archive_path.name} "
                        f"({total_size/1024/1024:.1f} MB -> {compressed_size/1024/1024:.1f} MB, {ratio}%)")

        except Exception as e:
            logger.error(f"  Eroare la arhivarea {group_key}: {e}")

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Brute arhivate: {archived_files} fișiere, "
                f"{archived_size/1024/1024:.1f} MB original")
    return archived_files, archived_size


# ─── PROCESATE: comprimare individuală .json.gz ─────────────────────

def compress_processed(compress_days=PROCESSED_COMPRESS_DAYS, dry_run=False):
    """
    Comprimă articolele procesate mai vechi de N zile: .json → .json.gz
    Fișierele comprimate rămân în data/processed/ și sunt citite transparent.
    """
    now = time.time()
    cutoff = now - compress_days * 86400
    compressed = 0
    saved_bytes = 0

    for f in PROCESSED_DIR.glob("*.json"):
        if f.stat().st_mtime > cutoff:
            continue

        try:
            original_size = f.stat().st_size
            gz_path = f.with_suffix('.json.gz')

            if gz_path.exists():
                continue

            if dry_run:
                logger.debug(f"  [DRY-RUN] {f.name} ({original_size/1024:.1f} KB)")
                compressed += 1
                saved_bytes += original_size  # estimare
                continue

            # Comprimă
            with open(f, 'rb') as fin:
                with gzip.open(gz_path, 'wb', compresslevel=6) as fout:
                    fout.write(fin.read())

            compressed_size = gz_path.stat().st_size
            saved_bytes += original_size - compressed_size

            # Șterge originalul doar dacă gz e valid
            try:
                with gzip.open(gz_path, 'rb') as check:
                    json.loads(check.read())
                f.unlink()
                compressed += 1
            except Exception:
                gz_path.unlink()
                logger.warning(f"  Verificare eșuată, păstrez originalul: {f.name}")

        except Exception as e:
            logger.error(f"  Eroare la comprimarea {f.name}: {e}")

    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Procesate comprimate: {compressed} fișiere, "
                f"economisit ~{saved_bytes/1024/1024:.1f} MB")
    return compressed, saved_bytes


# ─── RESTORE: dezarhivare ───────────────────────────────────────────

def restore_processed(article_id=None):
    """
    Decomprima articole procesate: .json.gz → .json
    Fără argument: restaurează toate. Cu article_id: doar unul.
    """
    restored = 0

    if article_id:
        gz_path = PROCESSED_DIR / f"{article_id}.json.gz"
        if not gz_path.exists():
            logger.warning(f"Nu am găsit arhiva: {gz_path.name}")
            return 0
        _decompress_one(gz_path)
        return 1

    for gz_path in PROCESSED_DIR.glob("*.json.gz"):
        if _decompress_one(gz_path):
            restored += 1

    logger.info(f"Restaurate: {restored} articole")
    return restored


def _decompress_one(gz_path):
    """Decomprima un singur .json.gz și șterge arhiva."""
    json_path = gz_path.with_suffix('')  # .json.gz → .json
    try:
        with gzip.open(gz_path, 'rb') as fin:
            data = fin.read()
        with open(json_path, 'wb') as fout:
            fout.write(data)
        gz_path.unlink()
        return True
    except Exception as e:
        logger.error(f"  Eroare la restaurarea {gz_path.name}: {e}")
        return False


# ─── LOAD HELPER: citire transparentă .json + .json.gz ─────────────

def load_article_file(path):
    """Citește un articol fie din .json fie din .json.gz."""
    if path.suffix == '.gz':
        with gzip.open(path, 'rb') as f:
            return json.loads(f.read())
    else:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)


# ─── STATUS ─────────────────────────────────────────────────────────

def show_status():
    """Afișează statistici spațiu disc."""
    # Brute
    raw_json = list(ARTICLES_DIR.glob("**/*.json"))
    raw_size = sum(f.stat().st_size for f in raw_json) if raw_json else 0

    # Procesate .json
    proc_json = list(PROCESSED_DIR.glob("*.json"))
    proc_json_size = sum(f.stat().st_size for f in proc_json) if proc_json else 0

    # Procesate .json.gz
    proc_gz = list(PROCESSED_DIR.glob("*.json.gz"))
    proc_gz_size = sum(f.stat().st_size for f in proc_gz) if proc_gz else 0

    # Arhive brute
    archive_files = list(ARCHIVE_DIR.glob("*.tar.gz")) if ARCHIVE_DIR.exists() else []
    archive_size = sum(f.stat().st_size for f in archive_files) if archive_files else 0

    total = raw_size + proc_json_size + proc_gz_size + archive_size

    print("=" * 60)
    print("📊 KronPapir — Spațiu stocare articole")
    print("=" * 60)
    print(f"  Brute (data/articles/):      {len(raw_json):>5} fișiere  {raw_size/1024/1024:>7.1f} MB")
    print(f"  Procesate .json:             {len(proc_json):>5} fișiere  {proc_json_size/1024/1024:>7.1f} MB")
    print(f"  Procesate .json.gz:          {len(proc_gz):>5} fișiere  {proc_gz_size/1024/1024:>7.1f} MB")
    print(f"  Arhive brute (tar.gz):       {len(archive_files):>5} fișiere  {archive_size/1024/1024:>7.1f} MB")
    print(f"  {'─' * 48}")
    print(f"  TOTAL:                       {len(raw_json)+len(proc_json)+len(proc_gz)+len(archive_files):>5} fișiere  {total/1024/1024:>7.1f} MB")
    print(f"\n  Articole active (disponibile web): {len(proc_json) + len(proc_gz)}")
    print("=" * 60)


# ─── MAIN ───────────────────────────────────────────────────────────

def main():
    # Subcomandă restore / status
    if len(sys.argv) > 1 and sys.argv[1] == 'restore':
        article_id = sys.argv[2] if len(sys.argv) > 2 else None
        restore_processed(article_id)
        return

    if len(sys.argv) > 1 and sys.argv[1] == 'status':
        show_status()
        return

    parser = argparse.ArgumentParser(
        description="KronPapir — Arhivare și cleanup articole"
    )
    parser.add_argument('--raw-strip-days', type=int, default=RAW_STRIP_DAYS,
                        help=f'Strip HTML din brute după N zile (default: {RAW_STRIP_DAYS})')
    parser.add_argument('--raw-archive-days', type=int, default=RAW_ARCHIVE_DAYS,
                        help=f'Arhivează brute după N zile (default: {RAW_ARCHIVE_DAYS})')
    parser.add_argument('--processed-days', type=int, default=PROCESSED_COMPRESS_DAYS,
                        help=f'Comprimă procesate după N zile (default: {PROCESSED_COMPRESS_DAYS})')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview fără modificări')
    parser.add_argument('--raw-only', action='store_true',
                        help='Doar articole brute')
    parser.add_argument('--processed-only', action='store_true',
                        help='Doar articole procesate')

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("KronPapir — Arhivare & Cleanup")
    logger.info("=" * 60)

    if not args.processed_only:
        logger.info(f"\n📋 Faza 1: Strip HTML din brute > {args.raw_strip_days} zile...")
        strip_html(args.raw_strip_days, args.dry_run)

        logger.info(f"\n📦 Faza 2: Arhivare brute > {args.raw_archive_days} zile...")
        archive_raw(args.raw_archive_days, args.dry_run)

    if not args.raw_only:
        logger.info(f"\n🗜️  Faza 3: Comprimare procesate > {args.processed_days} zile...")
        compress_processed(args.processed_days, args.dry_run)

    print()
    show_status()


if __name__ == "__main__":
    main()
