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
import json
import glob
import time
import signal
import logging
import argparse
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread, Event

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

        logger.info(f"✅ Scraping finalizat. Articole noi: {results.get('new_articles', 0)}")
        return results

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


def run_ai_processing():
    """Procesează articolele cu Claude AI."""
    logger.info("🤖 Pornesc procesarea AI...")

    raw_count = get_article_count(ARTICLES_DIR)
    processed_count = get_article_count(PROCESSED_DIR)

    logger.info(f"   Articole brute: {raw_count}, Procesate: {processed_count}")

    if raw_count == 0:
        logger.warning("⚠️ Nu există articole de procesat.")
        return {"status": "no_articles"}

    try:
        from ai_agent.processor import ArticleProcessor

        processor = ArticleProcessor(
            input_dir=str(ARTICLES_DIR),
            output_dir=str(PROCESSED_DIR)
        )

        results = processor.process_articles(generate_summary=True)
        logger.info(f"✅ Procesare AI finalizată. Articole procesate: {results.get('processed', 0)}")
        return results

    except ImportError:
        logger.warning("⚠️ Modulul AI nu este disponibil. Copiez articolele brute...")
        # Fallback: copiază articolele brute în processed
        copied = 0
        for f in ARTICLES_DIR.glob("*.json"):
            dest = PROCESSED_DIR / f.name
            if not dest.exists():
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        articles = json.load(fh)

                    if isinstance(articles, list):
                        for art in articles:
                            art['processed'] = False
                            art['processing_note'] = 'Articol original - procesare AI indisponibilă'

                    with open(dest, 'w', encoding='utf-8') as fh:
                        json.dump(articles, fh, ensure_ascii=False, indent=2)
                    copied += 1
                except Exception as e:
                    logger.error(f"Eroare la copierea {f.name}: {e}")

        logger.info(f"📋 Copiate {copied} fișiere fără procesare AI.")
        return {"status": "fallback", "copied": copied}
    except Exception as e:
        logger.error(f"❌ Eroare la procesarea AI: {e}")
        return {"status": "error", "error": str(e)}


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


def run_full_pipeline():
    """Rulează pipeline-ul complet: scrape → process."""
    logger.info("=" * 60)
    logger.info("🚀 KronPapir.ro - Pipeline Complet")
    logger.info("=" * 60)

    start_time = time.time()

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
  process         Procesează articolele cu Claude AI
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
        'process', 'serve', 'full', 'auto', 'status'
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
        'serve': lambda: run_web_server(args.host, args.port, args.debug),
        'full': run_full_pipeline,
        'auto': lambda: run_auto_mode(args.interval),
        'status': show_status,
    }

    commands[args.command]()


if __name__ == "__main__":
    main()
