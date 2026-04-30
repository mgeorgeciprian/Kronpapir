"""
Kronpapir scraper module.
Provides RSS and web scrapers for news aggregation.
"""

from .base_scraper import BaseScraper, Article
from .rss_scraper import RSSscraper
from .web_scraper import WebScraper
from .scraper_manager import ScraperManager

__all__ = [
    "BaseScraper",
    "Article",
    "RSSscraper",
    "WebScraper",
    "ScraperManager",
]
