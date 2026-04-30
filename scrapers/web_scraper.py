"""
Web page scraper for Kronpapir news aggregator.
Scrapes article listings from homepages and category pages, then follows individual links.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from urllib.parse import urljoin

from .base_scraper import BaseScraper, Article


class WebScraper(BaseScraper):
    """
    Scraper for traditional web pages.
    Extracts article links from homepage/category pages and parses individual articles.
    """

    def __init__(self, source_config: Dict[str, Any], **kwargs):
        super().__init__(source_config, **kwargs)
        self.homepage = source_config.get("homepage", self.base_url)
        self.pagination_pattern = source_config.get("pagination", "")
        self.max_articles = source_config.get("max_articles_per_source", 50)
        self.max_pages = source_config.get("max_pages", 3)

    def scrape(self) -> List[Article]:
        """
        Scrape articles from web pages.

        Returns:
            List of Article objects
        """
        articles = []
        article_urls = []

        # Collect article URLs from homepage and pagination
        for page_num in range(1, self.max_pages + 1):
            if page_num == 1:
                page_url = self.homepage
            else:
                if not self.pagination_pattern:
                    break
                page_url = urljoin(
                    self.homepage,
                    self.pagination_pattern.format(page=page_num)
                )

            self.logger.info(f"Scraping page {page_num}: {page_url}")
            urls = self._extract_article_links(page_url)
            article_urls.extend(urls)

            if not urls:  # Stop if no articles found on this page
                break

        self.logger.info(f"Found {len(article_urls)} article URLs")

        # Fetch and parse individual articles
        for url in article_urls[: self.max_articles]:
            try:
                article = self._fetch_and_parse_article(url)
                if article:
                    articles.append(article)
            except Exception as e:
                self.logger.error(f"Failed to fetch/parse article {url}: {str(e)}")
                continue

        return articles

    def _extract_article_links(self, page_url: str) -> List[str]:
        """
        Extract article links from a page.

        Args:
            page_url: URL of the page to scrape

        Returns:
            List of article URLs
        """
        article_urls = []

        try:
            html_content = self.fetch_page(page_url)
            if not html_content:
                return article_urls

            soup = self.parse_html(html_content)
            if not soup:
                return article_urls

            selectors = self.source_config.get("selectors", {})
            article_link_selector = selectors.get("article_link", "a.post-link, h2 a, article a")

            # Extract all article links
            links = self.extract_attribute(soup, article_link_selector, "href")

            for link in links:
                # Convert relative URLs to absolute
                absolute_url = urljoin(self.base_url, link)

                # Validate URL
                if absolute_url.startswith("http") and absolute_url.startswith(
                    self.base_url
                ):
                    article_urls.append(absolute_url)

            self.logger.debug(
                f"Extracted {len(article_urls)} article links from {page_url}"
            )

        except Exception as e:
            self.logger.error(f"Failed to extract article links: {str(e)}")

        return article_urls

    def _fetch_and_parse_article(self, article_url: str) -> Optional[Article]:
        """
        Fetch and parse a single article page.

        Args:
            article_url: URL of the article

        Returns:
            Article object, or None if parsing fails
        """
        try:
            html_content = self.fetch_page(article_url)
            if not html_content:
                self.logger.warning(f"Failed to fetch article: {article_url}")
                return None

            article = self.parse_article(html_content, article_url)
            if article:
                # Try to parse the date if not set
                if not article.date or article.date.year == datetime.now().year:
                    soup = self.parse_html(html_content)
                    if soup:
                        date = self._extract_date(soup)
                        if date:
                            article.date = date

                self.logger.debug(f"Parsed article: {article.title[:50]}")
                return article
            else:
                self.logger.warning(f"Failed to parse article: {article_url}")
                return None

        except Exception as e:
            self.logger.error(f"Error fetching/parsing article: {str(e)}")
            return None

    def _extract_date(self, soup) -> Optional[datetime]:
        """
        Extract publication date from article page.

        Args:
            soup: BeautifulSoup object

        Returns:
            datetime object, or None if not found
        """
        try:
            selectors = self.source_config.get("selectors", {})
            date_selector = selectors.get("date", "span.post-date, time, span.date")

            date_text = self.extract_text(soup, date_selector)
            if not date_text:
                return None

            # Try to parse common date formats
            date_formats = [
                "%d.%m.%Y",  # 01.01.2024
                "%d.%m.%Y %H:%M",  # 01.01.2024 12:30
                "%Y-%m-%d",  # 2024-01-01
                "%Y-%m-%d %H:%M:%S",  # 2024-01-01 12:30:45
                "%d %B %Y",  # 01 January 2024
                "%d %b %Y",  # 01 Jan 2024
            ]

            for date_format in date_formats:
                try:
                    return datetime.strptime(date_text.strip(), date_format)
                except ValueError:
                    continue

            self.logger.debug(f"Could not parse date: {date_text}")
            return None

        except Exception as e:
            self.logger.debug(f"Error extracting date: {str(e)}")
            return None
