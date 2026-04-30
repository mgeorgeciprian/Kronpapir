"""
SEO utilities — notificare motoare de căutare la publicarea de articole noi.
"""

import logging
import requests

logger = logging.getLogger("kronpapir.seo")

SITE_URL = "https://kronpapir.ro"
SITEMAP_URL = f"{SITE_URL}/sitemap.xml"
NEWS_SITEMAP_URL = f"{SITE_URL}/news-sitemap.xml"

# IndexNow key — fișierul trebuie să existe și la /{key}.txt pe site
INDEXNOW_KEY = "kronpapir2026seo"


def ping_google_sitemap():
    """Ping Google cu URL-ul sitemap-ului."""
    try:
        r = requests.get(
            "https://www.google.com/ping",
            params={"sitemap": SITEMAP_URL},
            timeout=10,
        )
        logger.info(f"Google ping: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"Google ping eșuat: {e}")
        return False


def ping_bing_sitemap():
    """Ping Bing cu URL-ul sitemap-ului."""
    try:
        r = requests.get(
            "https://www.bing.com/ping",
            params={"sitemap": SITEMAP_URL},
            timeout=10,
        )
        logger.info(f"Bing ping: {r.status_code}")
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"Bing ping eșuat: {e}")
        return False


def submit_indexnow(urls):
    """Trimite URL-uri noi prin IndexNow (Bing/Yandex)."""
    if not urls:
        return False
    try:
        payload = {
            "host": "kronpapir.ro",
            "key": INDEXNOW_KEY,
            "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": urls[:10000],
        }
        r = requests.post(
            "https://api.indexnow.org/indexnow",
            json=payload,
            timeout=15,
        )
        logger.info(f"IndexNow: {r.status_code} ({len(urls)} URL-uri)")
        return r.status_code in (200, 202)
    except Exception as e:
        logger.warning(f"IndexNow eșuat: {e}")
        return False


def notify_search_engines(new_urls=None):
    """Notifică toate motoarele de căutare. Apelat după publicarea de articole."""
    logger.info(f"🔔 Notific motoarele de căutare ({len(new_urls or [])} URL-uri noi)...")

    ping_google_sitemap()
    ping_bing_sitemap()

    if new_urls:
        submit_indexnow(new_urls)

    logger.info("✅ Notificări SEO trimise.")
