"""
Base scraper class for Kronpapir news aggregator.
Handles common operations: HTTP requests, parsing, deduplication, and storage.
"""

import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse
from abc import ABC, abstractmethod
import time
import random

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class Article:
    """Data model for a scraped article."""

    def __init__(
        self,
        title: str,
        content: str,
        source: str,
        url: str,
        date: Optional[datetime] = None,
        image_url: Optional[str] = None,
        category: str = "local",
        original_text: Optional[str] = None,
    ):
        self.title = title.strip() if title else ""
        self.content = content.strip() if content else ""
        self.source = source
        self.url = url.strip() if url else ""
        self.date = date or datetime.now()
        self.image_url = image_url
        self.category = category
        self.original_text = original_text or content
        self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert article to dictionary."""
        return {
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "url": self.url,
            "date": self.date.isoformat() if self.date else None,
            "image_url": self.image_url,
            "category": self.category,
            "original_text": self.original_text,
            "created_at": self.created_at.isoformat(),
        }

    def get_url_hash(self) -> str:
        """Get hash of URL for deduplication."""
        return hashlib.md5(self.url.encode("utf-8")).hexdigest()

    def get_content_hash(self) -> str:
        """Get hash of title+content for deduplication."""
        combined = f"{self.title}{self.content}".encode("utf-8")
        return hashlib.md5(combined).hexdigest()


class BaseScraper(ABC):
    """
    Abstract base class for all scrapers.
    Provides common functionality for HTTP requests, parsing, and storage.
    """

    def __init__(
        self,
        source_config: Dict[str, Any],
        data_dir: Path = Path("data/articles"),
        log_level: str = "INFO",
    ):
        self.source_config = source_config
        self.source_id = source_config.get("id", "unknown")
        self.source_name = source_config.get("name", "Unknown Source")
        self.base_url = source_config.get("url", "")
        self.category = source_config.get("category", "local")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging
        self.logger = self._setup_logging(log_level)

        # Session with retry logic
        self.session = self._create_session(
            max_retries=source_config.get("retry_attempts", 3)
        )

        # Rate limiting
        self.last_request_time = 0
        self.rate_limit_delay = source_config.get("rate_limit_delay", 1)

        # User agents for rotation
        self.user_agents = source_config.get("user_agents", self._get_default_user_agents())

        # Deduplication tracking
        self.processed_urls = self._load_processed_urls()
        self.dedup_strategy = source_config.get("dedup_strategy", "url_hash")

    def _setup_logging(self, log_level: str) -> logging.Logger:
        """Setup logger for this scraper."""
        logger = logging.getLogger(f"kronpapir.{self.source_id}")
        logger.setLevel(getattr(logging, log_level.upper()))

        # Create logs directory
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        # File handler
        fh = logging.FileHandler(logs_dir / f"{self.source_id}.log")
        fh.setLevel(getattr(logging, log_level.upper()))

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, log_level.upper()))

        # Formatter
        formatter = logging.Formatter(
            "[%(asctime)s] %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

        return logger

    def _create_session(self, max_retries: int = 3) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    @staticmethod
    def _get_default_user_agents() -> List[str]:
        """Get list of default user agents."""
        return [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
        ]

    def _get_random_user_agent(self) -> str:
        """Get a random user agent for request."""
        return random.choice(self.user_agents)

    def fetch_page(
        self,
        url: str,
        timeout: Optional[int] = None,
        verify_ssl: bool = True,
    ) -> Optional[str]:
        """
        Fetch a web page with retry logic and rate limiting.

        Args:
            url: URL to fetch
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates

        Returns:
            Page content as string, or None if failed
        """
        # Rate limiting
        time_since_last = time.time() - self.last_request_time
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)

        timeout = timeout or self.source_config.get("timeout", 10)

        try:
            headers = {
                "User-Agent": self._get_random_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ro-RO,ro;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }

            response = self.session.get(
                url,
                headers=headers,
                timeout=timeout,
                verify=verify_ssl,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"

            self.last_request_time = time.time()
            self.logger.debug(f"Successfully fetched: {url}")
            return response.text

        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch {url}: {str(e)}")
            return None

    def parse_html(self, html_content: str) -> Optional[BeautifulSoup]:
        """
        Parse HTML content using BeautifulSoup.

        Args:
            html_content: HTML content as string

        Returns:
            BeautifulSoup object, or None if parsing fails
        """
        try:
            return BeautifulSoup(html_content, "lxml")
        except Exception as e:
            self.logger.error(f"Failed to parse HTML: {str(e)}")
            return None

    def extract_text(self, soup: BeautifulSoup, selector: str) -> str:
        """
        Extract text from HTML using CSS selector.

        Args:
            soup: BeautifulSoup object
            selector: CSS selector string

        Returns:
            Extracted text, or empty string if not found
        """
        try:
            elements = soup.select(selector)
            if elements:
                # Try to get all text
                texts = [elem.get_text(strip=True) for elem in elements]
                return " ".join(texts) if texts else ""
            return ""
        except Exception as e:
            self.logger.debug(f"Failed to extract text with selector {selector}: {str(e)}")
            return ""

    def extract_attribute(
        self,
        soup: BeautifulSoup,
        selector: str,
        attribute: str = "href",
    ) -> List[str]:
        """
        Extract attribute values from HTML using CSS selector.

        Args:
            soup: BeautifulSoup object
            selector: CSS selector string
            attribute: Attribute name to extract (default: href)

        Returns:
            List of attribute values
        """
        try:
            elements = soup.select(selector)
            values = []
            for elem in elements:
                value = elem.get(attribute, "").strip()
                if value:
                    values.append(value)
            return values
        except Exception as e:
            self.logger.debug(f"Failed to extract {attribute} with selector {selector}: {str(e)}")
            return []

    def parse_article(
        self,
        article_html: str,
        article_url: str,
    ) -> Optional[Article]:
        """
        Parse article HTML and extract structured data.
        Override in subclasses for specific parsing logic.

        Args:
            article_html: Article HTML content
            article_url: URL of the article

        Returns:
            Article object, or None if parsing fails
        """
        soup = self.parse_html(article_html)
        if not soup:
            return None

        selectors = self.source_config.get("selectors", {})

        title = self.extract_text(soup, selectors.get("title", "h1, h2"))
        content = self.extract_text(soup, selectors.get("content", "article, div.content"))
        image_url = self.extract_attribute(soup, selectors.get("image", "img"), "src")
        image_url = image_url[0] if image_url else None

        # Make image URL absolute
        if image_url and not image_url.startswith("http"):
            image_url = urljoin(self.base_url, image_url)

        if not title or not content:
            self.logger.warning(f"Failed to parse article at {article_url}: missing title or content")
            return None

        article = Article(
            title=title,
            content=content,
            source=self.source_name,
            url=article_url,
            image_url=image_url,
            category=self.category,
            original_text=article_html,
        )

        return article

    def _load_processed_urls(self) -> set:
        """Load set of already processed URLs from storage."""
        processed_file = self.data_dir / f"{self.source_id}_processed.json"
        if processed_file.exists():
            try:
                with open(processed_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data.get("processed_urls", []))
            except Exception as e:
                self.logger.warning(f"Failed to load processed URLs: {str(e)}")
        return set()

    def _save_processed_urls(self):
        """Save set of processed URLs to storage."""
        processed_file = self.data_dir / f"{self.source_id}_processed.json"
        try:
            with open(processed_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"processed_urls": list(self.processed_urls)},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            self.logger.error(f"Failed to save processed URLs: {str(e)}")

    def is_duplicate(self, article: Article) -> bool:
        """
        Check if article is a duplicate based on deduplication strategy.

        Args:
            article: Article to check

        Returns:
            True if article is a duplicate, False otherwise
        """
        if self.dedup_strategy == "url_hash":
            url_hash = article.get_url_hash()
            return url_hash in self.processed_urls
        elif self.dedup_strategy == "content_hash":
            content_hash = article.get_content_hash()
            return content_hash in self.processed_urls
        return article.url in self.processed_urls

    def mark_as_processed(self, article: Article):
        """Mark article as processed for deduplication."""
        if self.dedup_strategy == "url_hash":
            self.processed_urls.add(article.get_url_hash())
        elif self.dedup_strategy == "content_hash":
            self.processed_urls.add(article.get_content_hash())
        else:
            self.processed_urls.add(article.url)

    def save_article(self, article: Article) -> bool:
        """
        Save article as JSON file.

        Args:
            article: Article to save

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Create source-specific directory
            source_dir = self.data_dir / self.source_id
            source_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename from URL
            url_hash = hashlib.md5(article.url.encode("utf-8")).hexdigest()
            filename = f"{url_hash}.json"
            filepath = source_dir / filename

            # Save article data
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(
                    article.to_dict(),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            self.logger.info(f"Saved article: {article.title[:50]}... to {filepath}")
            self.mark_as_processed(article)

            return True

        except Exception as e:
            self.logger.error(f"Failed to save article: {str(e)}")
            return False

    @abstractmethod
    def scrape(self) -> List[Article]:
        """
        Main scraping method. Must be implemented by subclasses.

        Returns:
            List of scraped articles
        """
        pass

    def run(self) -> Dict[str, Any]:
        """
        Run the scraper and return statistics.

        Returns:
            Dictionary with scraping statistics
        """
        self.logger.info(f"Starting scrape for {self.source_name}...")
        start_time = time.time()

        articles_fetched = 0
        articles_saved = 0
        duplicates = 0
        errors = 0

        try:
            articles = self.scrape()

            for article in articles:
                if self.is_duplicate(article):
                    duplicates += 1
                    self.logger.debug(f"Duplicate found: {article.title[:50]}")
                    continue

                if self.save_article(article):
                    articles_saved += 1
                else:
                    errors += 1

                articles_fetched += 1

            self._save_processed_urls()

        except Exception as e:
            self.logger.error(f"Fatal error during scraping: {str(e)}")
            errors += 1

        elapsed_time = time.time() - start_time

        stats = {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "articles_fetched": articles_fetched,
            "articles_saved": articles_saved,
            "duplicates": duplicates,
            "errors": errors,
            "elapsed_time": elapsed_time,
            "timestamp": datetime.now().isoformat(),
        }

        self.logger.info(
            f"Scraping complete. Fetched: {articles_fetched}, "
            f"Saved: {articles_saved}, Duplicates: {duplicates}, "
            f"Errors: {errors}, Time: {elapsed_time:.2f}s"
        )

        return stats

    def close(self):
        """Clean up resources."""
        self.session.close()
        self.logger.info(f"Closed scraper for {self.source_name}")
