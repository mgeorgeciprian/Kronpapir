#!/usr/bin/env python3
"""
KronPapir.ro - Pipeline Principal
Agregator de știri locale Brașov/Covasna

Orchestrează întregul flux:
1. Scraping → Fetchuiește articole din surse locale și naționale
2. AI Processing → Rescrie articolele cu Claude AI
3. Web Server → Servește site-ul

Utilizare:
    python run_pipeline.py scrape          # Doar scraping
    python run_pipeline.py process         # Doar procesare AI
    python run_pipeline.py serve           # Pornește serverul web
    python run_pipeline.py full            # Pipeline complet (scrape + process)
    python run_pipeline.py auto            # Mod automat (scrape + process + serve)
    python run_pipeline.py status          # Verifică starea sistemului
"""

import os
import sys

# Încarcă .env ÎNAINTE de orice altceva
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

import json
import glob
import time
import signal
import logging
import argparse
import subprocess
import re
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from threading import Thread, Event
from collections import defaultdict

# Configurare directoare
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
ARTICLES_DIR = DATA_DIR / "articles"
PROCESSED_DIR = DATA_DIR / "processed"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"

# Creare directoare dacă nu există
for d in [ARTICLES_DIR, PROCESSED_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / "pipeline.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("KronPapir")

# Event pentru oprire gracioasă
shutdown_event = Event()


def signal_handler(signum, frame):
    """Oprire gracioasă la Ctrl+C."""
    logger.info("🛑 Se oprește KronPapir...")
    shutdown_event.set()


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_article_count(directory):
    """Numără articolele dintr-un director."""
    count = 0
    for f in directory.glob("*.json"):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    count += len(data)
                else:
                    count += 1
        except Exception:
            pass
    return count


def run_scraping(sources_filter="all"):
    """Rulează agenții de scraping."""
    logger.info(f"📰 Pornesc scraping-ul ({sources_filter})...")

    try:
        from scrapers.scraper_manager import ScraperManager

        config_path = CONFIG_DIR / "sources.yaml"
        manager = ScraperManager(str(config_path))

        if sources_filter == "local":
            results = manager.scrape_category("local")
        elif sources_filter == "national":
            results = manager.scrape_category("national")
        else:
            results = manager.scrape_all()

        if isinstance(results, dict):
            logger.info(f"✅ Scraping finalizat. Articole noi: {results.get('new_articles', 0)}")
        else:
            logger.info(f"✅ Scraping finalizat.")
        return {"status": "completed"}

    except ImportError:
        logger.warning("⚠️ Modulul de scraping nu este disponibil. Rulez main.py...")
        cmd = [sys.executable, str(BASE_DIR / "main.py"), "scrape", "--all"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        logger.info(result.stdout)
        if result.returncode != 0:
            logger.error(f"Eroare scraping: {result.stderr}")
        return {"status": "completed" if result.returncode == 0 else "error"}
    except Exception as e:
        logger.error(f"❌ Eroare la scraping: {e}")
        return {"status": "error", "error": str(e)}


def normalize_title(title):
    """Normalize title for comparison."""
    title = title.lower().strip()
    title = re.sub(r'[^\w\s]', '', title)  # remove punctuation
    return set(title.split())


def jaccard_similarity(set1, set2):
    """Calculate Jaccard similarity between two sets."""
    if not set1 or not set2:
        return 0.0
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union)


def deduplicate_articles(processed_dir):
    """Remove duplicate articles based on title similarity and content overlap.

    Compares article titles using Jaccard similarity on word sets.
    If two articles have >60% word overlap in titles, they're considered duplicates.
    Keeps the one with longer content, deletes the other.
    """
    logger.info("🔍 Comenzând deduplicare semantică de articole...")

    articles = {}
    duplicates_found = 0
    duplicates_removed = 0

    # Load all articles from processed directory
    for f in processed_dir.glob("*.json"):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                article = json.load(fh)
                articles[f] = article
        except Exception as e:
            logger.warning(f"⚠️ Eroare la citirea {f.name}: {e}")
            continue

    logger.info(f"   Total articole pentru comparare: {len(articles)}")

    # Compare all pairs of articles
    processed_pairs = set()
    files_to_delete = []

    for file1, art1 in articles.items():
        title1 = art1.get('title', '')
        content1 = art1.get('content', '')

        if not title1:
            continue

        title_set1 = normalize_title(title1)

        for file2, art2 in articles.items():
            if file1 == file2:
                continue

            # Avoid comparing same pair twice
            pair = tuple(sorted([str(file1), str(file2)]))
            if pair in processed_pairs:
                continue

            title2 = art2.get('title', '')
            content2 = art2.get('content', '')

            if not title2:
                continue

            title_set2 = normalize_title(title2)

            # Check title similarity
            similarity = jaccard_similarity(title_set1, title_set2)

            if similarity > 0.6:  # >60% word overlap = duplicate
                duplicates_found += 1

                # Also check content similarity (first 100 chars)
                content_match = (content1[:100].lower() == content2[:100].lower())

                logger.debug(f"   Posibil duplicat găsit:")
                logger.debug(f"     - Titlu 1: {title1[:70]}")
                logger.debug(f"     - Titlu 2: {title2[:70]}")
                logger.debug(f"     - Asemănare: {similarity:.1%}")
                logger.debug(f"     - Conținut asemanator: {content_match}")

                # Keep the one with longer content
                if len(content1) >= len(content2):
                    files_to_delete.append(file2)
                    logger.info(f"   Ștergere: {art2.get('title', '')[:60]}")
                    duplicates_removed += 1
                else:
                    files_to_delete.append(file1)
                    logger.info(f"   Ștergere: {art1.get('title', '')[:60]}")
                    duplicates_removed += 1

            processed_pairs.add(pair)

    # Delete duplicate files
    for file_path in files_to_delete:
        try:
            file_path.unlink()
            logger.debug(f"   Fișier șters: {file_path.name}")
        except Exception as e:
            logger.warning(f"   Eroare la ștergerea {file_path.name}: {e}")

    logger.info(f"✅ Deduplicare finalizată: {duplicates_found} posibili duplicați, {duplicates_removed} șterse")
    return {"duplicates_found": duplicates_found, "duplicates_removed": duplicates_removed}


def run_ai_processing():
    """Procesează articolele cu Claude AI: 5 locale individual + editorial național + editorial internațional."""
    logger.info("🤖 Pornesc procesarea AI...")

    # Configurare limite din .env
    max_local = int(os.environ.get("LOCAL_ARTICLES_PER_RUN", "5"))
    max_national_editorial = int(os.environ.get("NATIONAL_EDITORIAL_SOURCES", "5"))
    max_intl_editorial = int(os.environ.get("INTL_EDITORIAL_SOURCES", "5"))

    raw_count = get_article_count(ARTICLES_DIR)
    processed_count_init = get_article_count(PROCESSED_DIR)

    logger.info(f"   Articole brute: {raw_count}, Procesate: {processed_count_init}")
    logger.info(f"   Plan: {max_local} locale + 1 editorial național ({max_national_editorial} știri) + 1 editorial internațional ({max_intl_editorial} știri)")

    if raw_count == 0:
        logger.warning("⚠️ Nu există articole de procesat.")
        return {"status": "no_articles"}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if api_key:
        try:
            from ai.rewriter import ArticleRewriter

            rewriter = ArticleRewriter(
                api_key=api_key,
                model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
            )

            processed_count = 0
            processed_urls = set()

            # Citește URL-urile deja procesate pentru deduplicare
            for f in PROCESSED_DIR.glob("*.json"):
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        art = json.load(fh)
                        if art.get('url'):
                            processed_urls.add(art['url'])
                except Exception:
                    pass

            # Clasifică articolele brute în 3 categorii
            local_articles = []
            national_articles = []
            intl_articles = []

            # Cuvinte cheie pentru detectare internațional
            intl_keywords = ['ue ', 'europa', 'european', 'nato', 'bruxelles', 'ucraina', 'rusia',
                           'sua', 'america', 'china', 'trump', 'putin', 'macron', 'berlin',
                           'paris', 'londra', 'washington', 'mondial', 'global', 'internațional',
                           'comisia europeană', 'parlamentul european', 'onu', 'g7', 'g20']

            # Doar articole din ultimele 48h pentru a evita citirea a mii de fișiere vechi
            cutoff_time = time.time() - 48 * 3600
            article_files = [f for f in ARTICLES_DIR.glob("**/*.json")
                            if f.stat().st_mtime > cutoff_time]
            article_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            logger.info(f"   Fișiere articole recente (48h): {len(article_files)}")

            for f in article_files:
                if f.name.startswith("_") or "processed" in f.name:
                    continue
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        article = json.load(fh)

                    articles_list = article if isinstance(article, list) else [article]

                    for art in articles_list:
                        if art.get('url') in processed_urls:
                            continue

                        # Clasificare: local vs national vs international
                        source_cat = art.get('source_category', art.get('category', '')).lower()
                        title_lower = (art.get('title', '') + ' ' + (art.get('content') or art.get('text') or '')[:300]).lower()

                        # Verifică dacă e internațional
                        is_intl = any(kw in title_lower for kw in intl_keywords)

                        if source_cat in ('local',) or 'brașov' in title_lower or 'brasov' in title_lower or 'covasna' in title_lower:
                            local_articles.append(art)
                        elif is_intl:
                            intl_articles.append(art)
                        else:
                            national_articles.append(art)

                except Exception as e:
                    logger.error(f"Eroare la citirea {f.name}: {e}")

            logger.info(f"   Clasificare: {len(local_articles)} locale, {len(national_articles)} naționale, {len(intl_articles)} internaționale")

            # === 1. RESCRIE ARTICOLE LOCALE INDIVIDUAL (max 5) ===
            logger.info(f"📝 Rescriu {min(len(local_articles), max_local)} articole locale...")
            for idx, art in enumerate(local_articles[:max_local], 1):
                title = art.get('title', 'Fără titlu')
                logger.info(f"   Local {idx}/{min(len(local_articles), max_local)}: {title[:60]}...")

                rewritten = rewriter.rewrite_article(art)
                if rewritten:
                    dest = PROCESSED_DIR / f"{rewritten['id']}.json"
                    with open(dest, 'w', encoding='utf-8') as fh:
                        json.dump(rewritten, fh, ensure_ascii=False, indent=2)
                    processed_count += 1
                    processed_urls.add(rewritten.get('url', ''))
                else:
                    logger.warning(f"   ⚠️ Nu s-a putut rescrie: {title[:50]}")

            # === 2. EDITORIAL NAȚIONAL (compilare din max 5 știri) ===
            if national_articles:
                logger.info(f"📰 Scriu editorial național din {min(len(national_articles), max_national_editorial)} știri...")
                editorial = rewriter.write_editorial(
                    national_articles[:max_national_editorial],
                    editorial_type="national"
                )
                if editorial:
                    dest = PROCESSED_DIR / f"{editorial['id']}.json"
                    with open(dest, 'w', encoding='utf-8') as fh:
                        json.dump(editorial, fh, ensure_ascii=False, indent=2)
                    processed_count += 1
                    logger.info(f"   ✅ Editorial național salvat: {editorial['title'][:50]}...")
                else:
                    logger.warning("   ⚠️ Nu s-a putut scrie editorialul național")

            # === 3. EDITORIAL INTERNAȚIONAL (compilare din max 5 știri) ===
            if intl_articles:
                logger.info(f"🌍 Scriu editorial internațional din {min(len(intl_articles), max_intl_editorial)} știri...")
                editorial = rewriter.write_editorial(
                    intl_articles[:max_intl_editorial],
                    editorial_type="international"
                )
                if editorial:
                    dest = PROCESSED_DIR / f"{editorial['id']}.json"
                    with open(dest, 'w', encoding='utf-8') as fh:
                        json.dump(editorial, fh, ensure_ascii=False, indent=2)
                    processed_count += 1
                    logger.info(f"   ✅ Editorial internațional salvat: {editorial['title'][:50]}...")
                else:
                    logger.warning("   ⚠️ Nu s-a putut scrie editorialul internațional")

            logger.info(f"✅ Procesare AI finalizată. Total procesat: {processed_count} (locale: {min(len(local_articles), max_local)}, editoriale: {processed_count - min(len(local_articles), max_local)})")
            return {"status": "completed", "processed": processed_count}

        except ImportError as e:
            logger.warning(f"⚠️ Modul AI nu e disponibil: {e}. Copiez articolele brute...")
        except Exception as e:
            logger.warning(f"⚠️ Procesare AI eșuată: {e}. Copiez articolele brute...")

    # Fallback: copiază articolele brute în processed (din subdirectoare)
    logger.info("📋 Copiez articolele brute fără procesare AI...")
    copied = 0
    import uuid

    # Caută recursiv în subdirectoare (doar ultimele 48h)
    fallback_cutoff = time.time() - 48 * 3600
    for f in ARTICLES_DIR.glob("**/*.json"):
        if f.name.startswith("_") or "processed" in f.name:
            continue
        if f.stat().st_mtime < fallback_cutoff:
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                article = json.load(fh)

            # Dacă e o listă, procesăm fiecare articol
            articles_list = article if isinstance(article, list) else [article]

            for art in articles_list:
                # Verifică dacă e deja procesat (are id în processed dir)
                art_id = art.get('id') or art.get('url_hash') or str(uuid.uuid4())
                dest = PROCESSED_DIR / f"{art_id}.json"
                if dest.exists():
                    continue

                # Formatează articolul pentru web
                art_image = art.get('image_url') or art.get('image', '')
                art_title = art.get('title', 'Fără titlu')
                art_category = art.get('category', 'local')
                if not art_image:
                    # Try og:image from original HTML first
                    try:
                        from bs4 import BeautifulSoup as _BS
                        orig_html = art.get('original_text', '')
                        if orig_html and '<' in orig_html:
                            _soup = _BS(orig_html, 'html.parser')
                            og = _soup.find('meta', property='og:image')
                            if og and og.get('content', '').strip():
                                art_image = og['content'].strip()
                    except Exception:
                        pass
                if not art_image:
                    try:
                        from utils.pixabay import get_article_image
                        art_image = get_article_image(art_title, art_category)
                    except Exception:
                        pass
                processed_art = {
                    'id': art_id,
                    'title': art_title,
                    'content': art.get('text') or art.get('content') or art.get('original_text', ''),
                    'excerpt': (art.get('text') or art.get('content') or '')[:200],
                    'category': art_category,
                    'type': 'national' if art.get('category') == 'national' or art.get('source_category') == 'national' else 'local',
                    'source': art.get('source', ''),
                    'url': art.get('url', ''),
                    'image': art_image,
                    'date': art.get('date') or art.get('published') or datetime.now().isoformat(),
                    'author': 'Redacția KronPapir',
                    'processed': False,
                }
                with open(dest, 'w', encoding='utf-8') as fh:
                    json.dump(processed_art, fh, ensure_ascii=False, indent=2)
                copied += 1

        except Exception as e:
            logger.error(f"Eroare la copierea {f.name}: {e}")

    logger.info(f"📋 Copiate {copied} articole noi în processed.")

    # Run deduplication before returning
    dedup_results = deduplicate_articles(PROCESSED_DIR)

    return {"status": "fallback", "copied": copied, "deduplication": dedup_results}


def run_ai_processing_balanced():
    """Procesare echilibrată: un articol per sursă, cel mai recent neprocesat."""
    logger.info("🤖 Pornesc procesarea AI echilibrată (unul per sursă)...")

    # Collect all raw articles grouped by source
    by_source = defaultdict(list)
    processed_urls = set()

    for f in PROCESSED_DIR.glob("*.json"):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                art = json.load(fh)
                if art.get('url'):
                    processed_urls.add(art['url'])
        except Exception:
            pass

    # Doar articole din ultimele 48h
    cutoff_time = time.time() - 48 * 3600
    recent_files = [f for f in ARTICLES_DIR.glob("**/*.json")
                    if f.stat().st_mtime > cutoff_time]
    logger.info(f"   Fișiere articole recente (48h): {len(recent_files)}")

    for f in recent_files:
        if f.name.startswith("_") or "processed" in f.name or f.name == "scraper_stats.json":
            continue
        if f.parent == ARTICLES_DIR:
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            articles_list = data if isinstance(data, list) else [data]
            for art in articles_list:
                if art.get('url') in processed_urls:
                    continue
                art_id = art.get('id') or art.get('url_hash') or f.stem
                art['id'] = art_id
                dest = PROCESSED_DIR / f"{art_id}.json"
                if not dest.exists():
                    source = f.parent.name
                    by_source[source].append(art)
        except Exception as e:
            logger.error(f"Eroare la citirea {f.name}: {e}")

    # Pick latest per source
    to_process = []
    for source, articles in by_source.items():
        articles.sort(key=lambda x: x.get('date', ''), reverse=True)
        to_process.append(articles[0])
        logger.info(f"   Selectat din {source}: {articles[0].get('title', '')[:50]}...")

    logger.info(f"   De procesat: {len(to_process)} (unul per sursă)")

    if not to_process:
        logger.info("✅ Toate articolele sunt deja procesate.")
        return {"status": "completed", "processed": 0}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    processed_count = 0
    failed_count = 0

    if api_key:
        try:
            from ai.rewriter import ArticleRewriter

            rewriter = ArticleRewriter(
                api_key=api_key,
                model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
            )

            for art in to_process:
                try:
                    result = rewriter.rewrite_article(art)
                    if result:
                        dest = PROCESSED_DIR / f"{result['id']}.json"
                        with open(dest, 'w', encoding='utf-8') as fh:
                            json.dump(result, fh, ensure_ascii=False, indent=2)
                        processed_count += 1
                        logger.info(f"   ✅ {result.get('title', '')[:60]}...")
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"   ❌ Eroare la procesarea articolului: {e}")
                    failed_count += 1

            # Editorial din articolele naționale procesate
            intl_keywords = ['ue ', 'europa', 'european', 'nato', 'bruxelles', 'ucraina', 'rusia',
                           'sua', 'america', 'china', 'trump', 'putin', 'macron']
            national_articles = []
            for art in to_process:
                source_cat = art.get('source_category', art.get('category', '')).lower()
                title_lower = (art.get('title', '') + ' ' + (art.get('content') or art.get('text') or '')[:300]).lower()
                if source_cat not in ('local',) and 'brașov' not in title_lower and 'brasov' not in title_lower:
                    national_articles.append(art)

            if len(national_articles) >= 3:
                try:
                    editorial = rewriter.write_editorial(national_articles, editorial_type="national")
                    if editorial:
                        dest = PROCESSED_DIR / f"{editorial['id']}.json"
                        with open(dest, 'w', encoding='utf-8') as fh:
                            json.dump(editorial, fh, ensure_ascii=False, indent=2)
                        logger.info(f"   ✅ Editorial generat: {editorial.get('title', '')[:60]}")
                except Exception as e:
                    logger.warning(f"   ⚠️ Nu am putut genera editorialul: {e}")

            logger.info(f"✅ Procesare echilibrată finalizată. Procesate: {processed_count}, Eșuate: {failed_count}")
            return {"status": "completed", "processed": processed_count, "failed": failed_count}

        except Exception as e:
            logger.warning(f"⚠️ Procesare AI eșuată: {e}")

    # Fallback
    logger.info("📋 Copiez articolele brute fără procesare AI...")
    import uuid as uuid_mod
    copied = 0
    for art in to_process:
        try:
            art_id = art.get('id') or str(uuid_mod.uuid4())
            dest = PROCESSED_DIR / f"{art_id}.json"
            if not dest.exists():
                art_image = art.get('image_url') or art.get('image', '')
                art_title = art.get('title', 'Fără titlu')
                art_category = art.get('category', 'local')
                if not art_image:
                    try:
                        from bs4 import BeautifulSoup as _BS
                        orig_html = art.get('original_text', '')
                        if orig_html and '<' in orig_html:
                            _soup = _BS(orig_html, 'html.parser')
                            og = _soup.find('meta', property='og:image')
                            if og and og.get('content', '').strip():
                                art_image = og['content'].strip()
                    except Exception:
                        pass
                if not art_image:
                    try:
                        from utils.pixabay import get_article_image
                        art_image = get_article_image(art_title, art_category)
                    except Exception:
                        pass
                processed_art = {
                    'id': art_id,
                    'title': art_title,
                    'content': art.get('content') or art.get('text') or '',
                    'excerpt': (art.get('content') or art.get('text') or '')[:200],
                    'category': art_category,
                    'type': 'national' if art.get('category') == 'national' else 'local',
                    'source': art.get('source', ''),
                    'url': art.get('url', ''),
                    'image': art_image,
                    'date': art.get('date') or datetime.now().isoformat(),
                    'author': 'Redacția KronPapir',
                    'processed': False,
                }
                with open(dest, 'w', encoding='utf-8') as fh:
                    json.dump(processed_art, fh, ensure_ascii=False, indent=2)
                copied += 1
        except Exception as e:
            logger.error(f"Eroare la copierea articolului: {e}")

    logger.info(f"📋 Copiate {copied} articole (unul per sursă) în processed.")
    return {"status": "fallback", "copied": copied}


def run_web_server(host="0.0.0.0", port=5000, debug=False):
    """Pornește serverul web Flask."""
    logger.info(f"🌐 Pornesc serverul web pe {host}:{port}...")

    try:
        sys.path.insert(0, str(BASE_DIR / "web"))
        from web.app import app

        app.config['PROCESSED_DIR'] = str(PROCESSED_DIR)
        app.run(host=host, port=port, debug=debug)

    except ImportError:
        logger.error("❌ Modulul web nu este disponibil.")
        logger.info("Instalează dependențele: pip install flask jinja2")
    except Exception as e:
        logger.error(f"❌ Eroare la pornirea serverului: {e}")


def run_editorials():
    """Rulează agentul editorial — scrie 3 editoriale: național, internațional, tematic."""
    logger.info("=" * 60)
    logger.info("📰 KronPapir.ro - Agent Editorial (Andrei Varga)")
    logger.info("=" * 60)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("❌ ANTHROPIC_API_KEY nu e setat. Nu pot scrie editoriale.")
        return {"status": "no_api_key"}

    try:
        from ai.editorial import EditorialAgent

        agent = EditorialAgent(
            api_key=api_key,
            model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929"),
        )

        # Clasifică articolele brute
        intl_keywords = ['ue ', 'europa', 'european', 'nato', 'bruxelles', 'ucraina', 'rusia',
                        'sua', 'america', 'china', 'trump', 'putin', 'macron', 'berlin',
                        'paris', 'londra', 'washington', 'mondial', 'global', 'internațional',
                        'comisia europeană', 'parlamentul european', 'onu', 'g7', 'g20']

        national_articles = []
        intl_articles = []
        all_articles = []

        for f in ARTICLES_DIR.glob("**/*.json"):
            if f.name.startswith("_"):
                continue
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                articles_list = data if isinstance(data, list) else [data]

                for art in articles_list:
                    all_articles.append(art)
                    title_lower = (art.get('title', '') + ' ' + (art.get('content') or art.get('text') or '')[:300]).lower()
                    source_cat = art.get('source_category', art.get('category', '')).lower()

                    is_intl = any(kw in title_lower for kw in intl_keywords)

                    if is_intl:
                        intl_articles.append(art)
                    elif source_cat not in ('local',) and 'brașov' not in title_lower and 'brasov' not in title_lower:
                        national_articles.append(art)
            except Exception:
                pass

        logger.info(f"   Articole disponibile: {len(national_articles)} naționale, {len(intl_articles)} internaționale, {len(all_articles)} total")

        # Scrie cele 3 editoriale
        results = agent.run_all_editorials(national_articles, intl_articles, all_articles)

        # Salvează editorialele
        saved = 0
        for key in ['national', 'international', 'tematic']:
            editorial = results.get(key)
            if editorial:
                dest = PROCESSED_DIR / f"{editorial['id']}.json"
                with open(dest, 'w', encoding='utf-8') as fh:
                    json.dump(editorial, fh, ensure_ascii=False, indent=2)
                saved += 1
                logger.info(f"   💾 Salvat: {editorial['title'][:60]}")

        logger.info(f"✅ Editoriale finalizate: {saved}/3 salvate")
        return {"status": "completed", "editorials_written": saved}

    except ImportError as e:
        logger.error(f"❌ Modul editorial nu e disponibil: {e}")
        return {"status": "error", "error": str(e)}
    except Exception as e:
        logger.error(f"❌ Eroare la editoriale: {e}")
        return {"status": "error", "error": str(e)}


def cleanup_old_articles(max_age_days=7):
    """Șterge articolele brute mai vechi de max_age_days zile."""
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for f in ARTICLES_DIR.glob("**/*.json"):
        if f.name.startswith("_") or "processed" in f.name:
            continue
        if f.parent == ARTICLES_DIR:
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception:
            pass
    if deleted:
        logger.info(f"🧹 Cleanup: {deleted} articole brute vechi șterse (>{max_age_days} zile)")


def run_full_pipeline():
    """Rulează pipeline-ul complet: scrape → process."""
    logger.info("=" * 60)
    logger.info("🚀 KronPapir.ro - Pipeline Complet")
    logger.info("=" * 60)

    start_time = time.time()

    # Pas 0: Cleanup articole vechi
    cleanup_old_articles()

    # Pas 1: Scraping
    scrape_results = run_scraping()

    if shutdown_event.is_set():
        return

    # Pas 2: Procesare AI
    process_results = run_ai_processing()

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info(f"✅ Pipeline finalizat în {elapsed:.1f} secunde")
    logger.info(f"   Scraping: {scrape_results.get('status', 'unknown')}")
    logger.info(f"   Procesare: {process_results.get('status', 'unknown')}")
    logger.info("=" * 60)


def run_auto_mode(scrape_interval=3600):
    """Mod automat: scraping periodic + server web."""
    logger.info("=" * 60)
    logger.info("🤖 KronPapir.ro - Mod Automat")
    logger.info(f"   Interval scraping: {scrape_interval}s ({scrape_interval/60:.0f} min)")
    logger.info("=" * 60)

    # Rulează pipeline-ul inițial
    run_full_pipeline()

    if shutdown_event.is_set():
        return

    # Pornește serverul web într-un thread separat
    web_thread = Thread(
        target=run_web_server,
        kwargs={"host": "0.0.0.0", "port": 5000},
        daemon=True
    )
    web_thread.start()
    logger.info("🌐 Server web pornit pe http://localhost:5000")

    # Loop de scraping periodic
    while not shutdown_event.is_set():
        logger.info(f"⏳ Următorul scraping în {scrape_interval/60:.0f} minute...")

        # Așteaptă intervalul sau până la shutdown
        if shutdown_event.wait(timeout=scrape_interval):
            break

        logger.info("🔄 Rulând ciclul de actualizare...")
        run_scraping()
        run_ai_processing()

    logger.info("🛑 KronPapir oprit.")


def show_status():
    """Afișează starea sistemului."""
    print("\n" + "=" * 50)
    print("📊 KronPapir.ro - Status Sistem")
    print("=" * 50)

    # Verifică directoare
    print(f"\n📁 Directoare:")
    print(f"   Base:      {BASE_DIR}")
    print(f"   Articole:  {ARTICLES_DIR} {'✅' if ARTICLES_DIR.exists() else '❌'}")
    print(f"   Procesate: {PROCESSED_DIR} {'✅' if PROCESSED_DIR.exists() else '❌'}")
    print(f"   Loguri:    {LOGS_DIR} {'✅' if LOGS_DIR.exists() else '❌'}")

    # Numără articole
    raw_count = get_article_count(ARTICLES_DIR)
    processed_count = get_article_count(PROCESSED_DIR)

    print(f"\n📰 Articole:")
    print(f"   Brute (raw):     {raw_count}")
    print(f"   Procesate (AI):  {processed_count}")

    # Verifică configurarea
    config_path = CONFIG_DIR / "sources.yaml"
    env_path = BASE_DIR / ".env"

    print(f"\n⚙️  Configurare:")
    print(f"   sources.yaml: {'✅' if config_path.exists() else '❌ Lipsește!'}")
    print(f"   .env:         {'✅' if env_path.exists() else '⚠️  Lipsește (necesar pentru AI)'}")

    # Verifică dependențe
    print(f"\n📦 Module:")
    modules = {
        'requests': 'Scraping HTTP',
        'bs4': 'Parsing HTML',
        'feedparser': 'Parsing RSS',
        'yaml': 'Configurare',
        'anthropic': 'Claude AI',
        'flask': 'Server Web',
        'jinja2': 'Template-uri',
    }

    for mod, desc in modules.items():
        try:
            __import__(mod)
            print(f"   {mod:15s} ({desc}): ✅")
        except ImportError:
            print(f"   {mod:15s} ({desc}): ❌")

    # Ultimul articol
    latest = None
    latest_time = None
    for f in PROCESSED_DIR.glob("*.json"):
        mtime = f.stat().st_mtime
        if latest_time is None or mtime > latest_time:
            latest_time = mtime
            latest = f

    if latest:
        dt = datetime.fromtimestamp(latest_time)
        print(f"\n🕐 Ultima actualizare: {dt.strftime('%d.%m.%Y %H:%M')}")
    else:
        print(f"\n🕐 Nicio actualizare încă.")

    print("\n" + "=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="KronPapir.ro - Agregator de Știri Locale",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Comenzi disponibile:
  scrape          Fetchuiește articole din toate sursele
  scrape-local    Fetchuiește doar din surse locale (Brașov/Covasna)
  scrape-national Fetchuiește doar din surse naționale
  process         Procesează articolele locale cu Claude AI (5 per rulare)
  editorial       Scrie editoriale zilnice (național + internațional + tematic)
  serve           Pornește serverul web
  full            Pipeline complet (scrape + process)
  auto            Mod automat (scrape periodic + serve)
  status          Verifică starea sistemului

Exemple:
  python run_pipeline.py full              # Scraping + AI + afișare status
  python run_pipeline.py auto              # Mod autonom complet
  python run_pipeline.py serve --port 8080 # Server pe port custom
        """
    )

    parser.add_argument('command', choices=[
        'scrape', 'scrape-local', 'scrape-national',
        'process', 'process-balanced', 'editorial', 'serve', 'full', 'auto', 'status'
    ], help='Comanda de executat')

    parser.add_argument('--port', type=int, default=5000, help='Port server web (default: 5000)')
    parser.add_argument('--host', default='0.0.0.0', help='Host server web (default: 0.0.0.0)')
    parser.add_argument('--interval', type=int, default=3600, help='Interval scraping în secunde (default: 3600)')
    parser.add_argument('--debug', action='store_true', help='Mod debug')

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    commands = {
        'scrape': lambda: run_scraping("all"),
        'scrape-local': lambda: run_scraping("local"),
        'scrape-national': lambda: run_scraping("national"),
        'process': run_ai_processing,
        'process-balanced': run_ai_processing_balanced,
        'editorial': run_editorials,
        'serve': lambda: run_web_server(args.host, args.port, args.debug),
        'full': run_full_pipeline,
        'auto': lambda: run_auto_mode(args.interval),
        'status': show_status,
    }

    commands[args.command]()


if __name__ == "__main__":
    main()
