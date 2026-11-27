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


# Google (2023) și Bing (2022) au închis endpoint-urile /ping pentru sitemap
# (răspund 404/410). Google citește sitemap-ul din Search Console și robots.txt;
# Bing și Yandex primesc URL-urile noi prin IndexNow.


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

    if new_urls:
        submit_indexnow(new_urls)

    logger.info("✅ Notificări SEO trimise.")
