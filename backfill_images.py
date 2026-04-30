#!/usr/bin/env python3
"""
KronPapir - Backfill article images from original sources.

Scans processed articles missing images and tries to find them from:
1. Raw article cache (og:image / CSS selectors)
2. Re-fetch from original URL (og:image / CSS selectors)
3. Pixabay API fallback (optional)

Usage:
    python backfill_images.py                  # All articles without images
    python backfill_images.py --days 14        # Only last 14 days
    python backfill_images.py --dry-run        # Preview without saving
    python backfill_images.py --no-pixabay     # Skip Pixabay fallback
    python backfill_images.py --force          # Replace Pixabay with real images
"""

import os
import sys
import json
import time
import random
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urljoin

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger("KronPapir.BackfillImages")

BASE_DIR = Path(__file__).parent
ARTICLES_DIR = BASE_DIR / "data" / "articles"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]


def build_raw_index():
    """Index all raw articles by URL for fast lookup."""
    index = {}
    for f in ARTICLES_DIR.glob("**/*.json"):
        if f.name.startswith("_") or "processed" in f.name:
            continue
        try:
            data = json.load(open(f, 'r', encoding='utf-8'))
            items = data if isinstance(data, list) else [data]
            for art in items:
                url = art.get('url', '')
                if url:
                    index[url] = art
        except Exception:
            pass
    return index


def fetch_page(url, timeout=15):
    """Fetch a page with rate limiting and random user agent."""
    try:
        resp = requests.get(url, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ro-RO,ro;q=0.9",
        }, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as e:
        logger.debug(f"Failed to fetch {url[:80]}: {e}")
        return None


def extract_image_from_html(html, article_url=""):
    """
    Extract the best image URL from article HTML.

    Priority: og:image > twitter:image > CSS selectors
    Returns (image_url, method) tuple.
    """
    if not html or '<' not in html:
        return "", ""

    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return "", ""

    # Priority 1: og:image
    og = soup.find('meta', property='og:image')
    if og:
        url = og.get('content', '').strip()
        if url and not url.startswith('data:'):
            return url, "og:image"

    # Priority 2: twitter:image
    tw = soup.find('meta', attrs={'name': 'twitter:image'})
    if tw:
        url = tw.get('content', '').strip()
        if url and not url.startswith('data:'):
            return url, "twitter:image"

    # Priority 3: CSS selectors for featured images
    selectors = [
        'img.wp-post-image',
        'img.featured-image',
        '.post-thumbnail img',
        'figure.post-image img',
        'article img:first-of-type',
    ]
    skip_patterns = ['1x1', 'pixel', 'spacer', 'blank', 'tracking', 'logo',
                     'avatar', 'icon', 'emoji', 'badge']

    for sel in selectors:
        for elem in soup.select(sel):
            src = elem.get('src', '').strip()
            if not src or src.startswith('data:'):
                continue
            if any(p in src.lower() for p in skip_patterns):
                continue
            if not src.startswith('http') and article_url:
                src = urljoin(article_url, src)
            return src, "css-selector"

    return "", ""


def backfill(days=None, dry_run=False, use_pixabay=True, force=False):
    """
    Backfill images for processed articles.

    Args:
        days: Only process articles from last N days (None = all)
        dry_run: Preview without saving
        use_pixabay: Use Pixabay API as last fallback
        force: Re-process articles that already have Pixabay images
    """
    logger.info("Building raw article index...")
    raw_index = build_raw_index()
    logger.info(f"Indexed {len(raw_index)} raw articles by URL")

    # Load Pixabay if needed
    pixabay_fn = None
    if use_pixabay:
        try:
            from utils.pixabay import get_article_image
            pixabay_fn = get_article_image
        except ImportError:
            logger.warning("Pixabay module not available, skipping")

    # Date cutoff
    date_cutoff = None
    if days:
        date_cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # Stats
    stats = {
        'total': 0,
        'skipped_has_image': 0,
        'skipped_date': 0,
        'skipped_editorial': 0,
        'updated_raw': 0,
        'updated_fetch': 0,
        'updated_pixabay': 0,
        'fetch_failed': 0,
        'no_image_found': 0,
    }

    processed_files = sorted(PROCESSED_DIR.glob("*.json"))
    logger.info(f"Scanning {len(processed_files)} processed articles...")

    # Collect articles to process
    to_process = []
    for f in processed_files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                art = json.load(fh)
        except Exception:
            continue

        stats['total'] += 1
        current_image = art.get('image', '')

        # Skip if already has a real (non-Pixabay) image
        if current_image and 'pixabay' not in current_image:
            stats['skipped_has_image'] += 1
            continue

        # Skip Pixabay images unless force mode
        if current_image and 'pixabay' in current_image and not force:
            stats['skipped_has_image'] += 1
            continue

        # Date filter
        if date_cutoff and art.get('date', '') < date_cutoff:
            stats['skipped_date'] += 1
            continue

        # Skip editorials (kronpapir.ro URLs, no original source to fetch)
        url = art.get('url', '')
        if 'kronpapir.ro' in url or not url:
            stats['skipped_editorial'] += 1
            continue

        to_process.append((f, art))

    logger.info(f"Articles to process: {len(to_process)}")

    for idx, (f, art) in enumerate(to_process, 1):
        url = art.get('url', '')
        title = art.get('title', '?')[:60]
        source = art.get('source', '')
        new_image = ""
        method = ""

        # Step 1: Try raw article cache
        raw = raw_index.get(url)
        if raw:
            orig_html = raw.get('original_text', '')
            new_image, method = extract_image_from_html(orig_html, url)
            if new_image:
                method = f"raw:{method}"

        # Step 2: Re-fetch from original URL
        if not new_image and url.startswith('http'):
            if not dry_run:
                time.sleep(0.5)  # rate limit
            html = None if dry_run else fetch_page(url)
            if html:
                new_image, method = extract_image_from_html(html, url)
                if new_image:
                    method = f"fetch:{method}"
            elif not dry_run:
                stats['fetch_failed'] += 1

        # Step 3: Pixabay fallback
        if not new_image and pixabay_fn and not dry_run:
            category = art.get('category', 'local')
            new_image = pixabay_fn(title, category)
            if new_image:
                method = "pixabay"

        # Apply
        if new_image:
            if not dry_run:
                art['image'] = new_image
                if 'pixabay' not in new_image:
                    art['image_source'] = source
                with open(f, 'w', encoding='utf-8') as fh:
                    json.dump(art, fh, ensure_ascii=False, indent=2)

            if 'raw:' in method:
                stats['updated_raw'] += 1
            elif 'fetch:' in method:
                stats['updated_fetch'] += 1
            elif method == "pixabay":
                stats['updated_pixabay'] += 1

            prefix = "[DRY-RUN] " if dry_run else ""
            logger.info(f"  {prefix}{method:20s} | {title}")
        else:
            stats['no_image_found'] += 1
            if idx <= 20 or idx % 50 == 0:
                logger.debug(f"  {'[DRY-RUN] ' if dry_run else ''}NO IMAGE{' ':13s} | {title}")

        # Progress
        if idx % 50 == 0:
            done = stats['updated_raw'] + stats['updated_fetch'] + stats['updated_pixabay']
            logger.info(f"  Progress: {idx}/{len(to_process)} scanned, {done} updated...")

    # Summary
    updated_total = stats['updated_raw'] + stats['updated_fetch'] + stats['updated_pixabay']
    logger.info("=" * 60)
    logger.info(f"Backfill {'preview' if dry_run else 'complete'}:")
    logger.info(f"  Total scanned:       {stats['total']}")
    logger.info(f"  Already had image:   {stats['skipped_has_image']}")
    logger.info(f"  Skipped editorials:  {stats['skipped_editorial']}")
    if date_cutoff:
        logger.info(f"  Skipped (too old):   {stats['skipped_date']}")
    logger.info(f"  Updated (raw cache): {stats['updated_raw']}")
    logger.info(f"  Updated (re-fetch):  {stats['updated_fetch']}")
    logger.info(f"  Updated (pixabay):   {stats['updated_pixabay']}")
    logger.info(f"  Fetch failed:        {stats['fetch_failed']}")
    logger.info(f"  No image found:      {stats['no_image_found']}")
    logger.info(f"  TOTAL UPDATED:       {updated_total}")
    logger.info("=" * 60)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Backfill images for KronPapir processed articles"
    )
    parser.add_argument('--days', type=int, default=None,
                        help='Only process articles from last N days')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without saving')
    parser.add_argument('--no-pixabay', action='store_true',
                        help='Skip Pixabay API fallback')
    parser.add_argument('--force', action='store_true',
                        help='Re-process articles with Pixabay images')

    args = parser.parse_args()
    backfill(
        days=args.days,
        dry_run=args.dry_run,
        use_pixabay=not args.no_pixabay,
        force=args.force,
    )


if __name__ == "__main__":
    main()
