"""
Kronpapir - Romanian Local News Aggregator
Focus: Brașov/Covasna area local news

A Python-based web scraping system for aggregating news from multiple Romanian sources.
"""

__version__ = "1.0.0"
__author__ = "Kronpapir Team"
__description__ = "Romanian Local News Aggregator for Brașov/Covasna"

from .scrapers import ScraperManager, BaseScraper, RSSscraper, WebScraper, Article

__all__ = [
    "ScraperManager",
    "BaseScraper",
    "RSSscraper",
    "WebScraper",
    "Article",
]
