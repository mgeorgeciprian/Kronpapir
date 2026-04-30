"""
RSS feed scraper for Kronpapir news aggregator.
Fetches articles from RSS feeds and extracts full content from individual article pages.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

import feedparser

from .base_scraper import BaseScraper, Article


class RSSscraper(BaseScraper):
    """
    Scraper for RSS feed sources.
    Parses RSS feeds and follows links to get full article content.
    """

    def __init__(self, source_config: Dict[str, Any], **kwargs):
        super().__init__(source_config, **kwargs)
        self.rss_url = source_config.get("rss_url", "")
        self.max_articles = source_config.get("max_articles_per_feed", 50)

    def scrape(self) -> List[Article]:
        """
        Scrape articles from RSS feed.

        Returns:
            List of Article objects
        """
        articles = []

        if not self.rss_url:
            self.logger.error(f"No RSS URL configured for {self.source_name}")
            return articles

        self.logger.info(f"Fetching RSS feed: {self.rss_url}")

        try:
            # Fetch and parse RSS feed
            feed = feedparser.parse(self.rss_url)

            if feed.bozo:
                self.logger.warning(
                    f"Malformed RSS feed detected: {feed.bozo_exception}"
                )

            entries = feed.get("entries", [])
            self.logger.info(f"Found {len(entries)} entries in RSS feed")

            # Process each entry
            for entry in entries[: self.max_articles]:
                try:
                    article = self._parse_rss_entry(entry)
                    if article:
                        articles.append(article)
                except Exception as e:
                    self.logger.error(f"Failed to parse RSS entry: {str(e)}")
                    continue

        except Exception as e:
            self.logger.error(f"Failed to fetch RSS feed: {str(e)}")

        return articles

    def _parse_rss_entry(self, entry: Dict[str, Any]) -> Optional[Article]:
        """
        Parse a single RSS entry and get full article content.

        Args:
            entry: RSS entry dictionary from feedparser

        Returns:
            Article object, or None if parsing fails
        """
        try:
            # Extract basic info from RSS entry
            title = entry.get("title", "").strip()
            article_url = entry.get("link", "").strip()
            description = entry.get("summary", entry.get("description", "")).strip()

            if not title or not article_url:
                self.logger.debug("Skipping entry without title or URL")
                return None

            # Try to get full article content by fetching the URL
            full_content = description
            article_html = None

            try:
                article_html = self.fetch_page(article_url)
                if article_html:
                    # Parse the full article page to get more content
                    soup = self.parse_html(article_html)
                    if soup:
                        selectors = self.source_config.get("selectors", {})
                        content = self.extract_text(soup, selectors.get("content", "article, div.content"))
                        if content:
                            full_content = content
            except Exception as e:
                self.logger.debug(f"Failed to fetch full article from {article_url}: {str(e)}")
                # Fall back to description from RSS
                pass

            # Extract image if available
            image_url = None
            if "image" in entry:
                image_url = entry["image"].get("href", "")
            elif "media_content" in entry:
                image_url = entry["media_content"][0].get("url", "")

            # Parse date
            date = self._parse_date(entry)

            article = Article(
                title=title,
                content=full_content,
                source=self.source_name,
                url=article_url,
                date=date,
                image_url=image_url,
                category=self.category,
                original_text=article_html or description,
            )

            return article

        except Exception as e:
            self.logger.error(f"Error parsing RSS entry: {str(e)}")
            return None

    def _parse_date(self, entry: Dict[str, Any]) -> datetime:
        """
        Parse publication date from RSS entry.

        Args:
            entry: RSS entry dictionary

        Returns:
            datetime object
        """
        try:
            # Try different date fields
            date_tuple = (
                entry.get("published_parsed")
                or entry.get("updated_parsed")
                or entry.get("created_parsed")
            )

            if date_tuple:
                return datetime.fromtimestamp(
                    __import__("calendar").timegm(date_tuple)
                )

        except Exception as e:
            self.logger.debug(f"Failed to parse date: {str(e)}")

        # Return current time if parsing fails
        return datetime.now()
