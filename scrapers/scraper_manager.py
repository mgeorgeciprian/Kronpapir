"""
Scraper manager for Kronpapir news aggregator.
Orchestrates scraping from multiple sources with scheduling and error handling.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import schedule
import argparse

import yaml

from .base_scraper import BaseScraper
from .rss_scraper import RSSscraper
from .web_scraper import WebScraper


class ScraperManager:
    """
    Manages scraping from multiple news sources.
    Handles scheduling, statistics tracking, and error recovery.
    """

    def __init__(self, config_file: str = "config/sources.yaml", data_dir: str = "data/articles"):
        self.config_file = Path(config_file)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging
        self.logger = self._setup_logging()

        # Load configuration
        self.config = self._load_config()
        self.sources = self.config.get("sources", [])
        self.scraper_config = self.config.get("scraper_config", {})

        # Tracking
        self.stats_file = self.data_dir / "scraper_stats.json"
        self.stats = self._load_stats()
        self.active_scrapers: Dict[str, BaseScraper] = {}

    def _setup_logging(self) -> logging.Logger:
        """Setup logger for the manager."""
        logger = logging.getLogger("kronpapir.manager")
        logger.setLevel(logging.INFO)

        # Create logs directory
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)

        # File handler
        fh = logging.FileHandler(logs_dir / "manager.log")
        fh.setLevel(logging.INFO)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

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

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            self.logger.info(f"Loaded configuration from {self.config_file}")
            return config
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {str(e)}")
            return {"sources": [], "scraper_config": {}}

    def _load_stats(self) -> Dict[str, Any]:
        """Load scraping statistics from file."""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed to load stats: {str(e)}")
        return {"runs": []}

    def _save_stats(self):
        """Save scraping statistics to file."""
        try:
            with open(self.stats_file, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save stats: {str(e)}")

    def _create_scraper(self, source_config: Dict[str, Any]) -> Optional[BaseScraper]:
        """
        Create appropriate scraper based on source type.

        Args:
            source_config: Source configuration dictionary

        Returns:
            Scraper instance, or None if creation fails
        """
        try:
            scraper_type = source_config.get("type", "scrape")
            source_id = source_config.get("id", "unknown")

            # Add global config to source config
            source_config.update({
                "user_agents": self.scraper_config.get("user_agents", []),
                "rate_limit_delay": self.scraper_config.get("rate_limit_delay", 1),
                "dedup_strategy": self.scraper_config.get("deduplication", {}).get("strategy", "url_hash"),
            })

            if scraper_type == "rss":
                self.logger.debug(f"Creating RSS scraper for {source_id}")
                return RSSscraper(source_config, data_dir=self.data_dir)
            elif scraper_type == "scrape":
                self.logger.debug(f"Creating web scraper for {source_id}")
                return WebScraper(source_config, data_dir=self.data_dir)
            else:
                self.logger.error(f"Unknown scraper type: {scraper_type}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to create scraper: {str(e)}")
            return None

    def scrape_source(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape a single source.

        Args:
            source_config: Source configuration dictionary

        Returns:
            Statistics dictionary
        """
        source_id = source_config.get("id", "unknown")
        enabled = source_config.get("enabled", True)

        if not enabled:
            self.logger.info(f"Source {source_id} is disabled, skipping")
            return {
                "source_id": source_id,
                "status": "skipped",
                "reason": "disabled",
            }

        self.logger.info(f"Starting scrape for source: {source_id}")

        scraper = None
        try:
            scraper = self._create_scraper(source_config)
            if not scraper:
                return {
                    "source_id": source_id,
                    "status": "error",
                    "error": "Failed to create scraper",
                }

            # Run scraper
            stats = scraper.run()
            stats["status"] = "success"

            return stats

        except Exception as e:
            self.logger.error(f"Error scraping {source_id}: {str(e)}")
            return {
                "source_id": source_id,
                "status": "error",
                "error": str(e),
            }

        finally:
            if scraper:
                scraper.close()

    def scrape_all(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scrape all or filtered sources.

        Args:
            category: Category to filter by (local/national), or None for all

        Returns:
            List of statistics dictionaries
        """
        self.logger.info(f"Starting scrape run (category: {category or 'all'})")
        start_time = time.time()

        all_stats = []

        # Filter sources
        sources_to_scrape = self.sources
        if category:
            sources_to_scrape = [s for s in self.sources if s.get("category") == category]

        self.logger.info(f"Scraping {len(sources_to_scrape)} sources")

        for source_config in sources_to_scrape:
            try:
                stats = self.scrape_source(source_config)
                all_stats.append(stats)
            except Exception as e:
                self.logger.error(f"Fatal error processing source: {str(e)}")
                continue

        # Compile overall statistics
        elapsed_time = time.time() - start_time

        run_stats = {
            "timestamp": datetime.now().isoformat(),
            "category": category or "all",
            "total_sources": len(sources_to_scrape),
            "sources": all_stats,
            "elapsed_time": elapsed_time,
            "summary": self._summarize_stats(all_stats),
        }

        # Save statistics
        self.stats["runs"].append(run_stats)
        self._save_stats()

        self.logger.info(
            f"Scrape run complete. "
            f"Success: {run_stats['summary']['successful_sources']}, "
            f"Failed: {run_stats['summary']['failed_sources']}, "
            f"Time: {elapsed_time:.2f}s"
        )

        return all_stats

    @staticmethod
    def _summarize_stats(stats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Summarize statistics from multiple sources.

        Args:
            stats: List of statistics dictionaries

        Returns:
            Summary dictionary
        """
        summary = {
            "successful_sources": 0,
            "failed_sources": 0,
            "skipped_sources": 0,
            "total_articles_fetched": 0,
            "total_articles_saved": 0,
            "total_duplicates": 0,
            "total_errors": 0,
        }

        for stat in stats:
            if stat.get("status") == "success":
                summary["successful_sources"] += 1
                summary["total_articles_fetched"] += stat.get("articles_fetched", 0)
                summary["total_articles_saved"] += stat.get("articles_saved", 0)
                summary["total_duplicates"] += stat.get("duplicates", 0)
            elif stat.get("status") == "error":
                summary["failed_sources"] += 1
                summary["total_errors"] += 1
            elif stat.get("status") == "skipped":
                summary["skipped_sources"] += 1

        return summary

    def schedule_scraping(self):
        """Setup scheduled scraping jobs."""
        scheduling = self.config.get("scheduling", {})

        local_interval = scheduling.get("local_sources_interval", 3600)
        national_interval = scheduling.get("national_sources_interval", 7200)
        cleanup_interval = scheduling.get("cleanup_interval", 86400)

        # Schedule local sources
        schedule.every(local_interval).seconds.do(self.scrape_all, category="local")
        self.logger.info(f"Scheduled local sources scraping every {local_interval}s")

        # Schedule national sources
        schedule.every(national_interval).seconds.do(self.scrape_all, category="national")
        self.logger.info(f"Scheduled national sources scraping every {national_interval}s")

        # Schedule cleanup
        schedule.every(cleanup_interval).seconds.do(self.cleanup_old_articles)
        self.logger.info(f"Scheduled article cleanup every {cleanup_interval}s")

    def cleanup_old_articles(self):
        """Remove articles older than retention period."""
        retention_days = self.config.get("scraper_config", {}).get("article_retention_days", 30)
        cutoff_date = datetime.now() - timedelta(days=retention_days)

        self.logger.info(f"Cleaning up articles older than {retention_days} days")

        deleted_count = 0

        try:
            for source_dir in self.data_dir.glob("*"):
                if not source_dir.is_dir():
                    continue

                for article_file in source_dir.glob("*.json"):
                    try:
                        with open(article_file, "r", encoding="utf-8") as f:
                            article_data = json.load(f)

                        article_date = datetime.fromisoformat(
                            article_data.get("created_at", datetime.now().isoformat())
                        )

                        if article_date < cutoff_date:
                            article_file.unlink()
                            deleted_count += 1

                    except Exception as e:
                        self.logger.debug(f"Error processing article file {article_file}: {str(e)}")
                        continue

        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")

        self.logger.info(f"Deleted {deleted_count} old articles")

    def run_scheduler(self):
        """Run the scheduler loop."""
        self.logger.info("Starting scheduler...")
        self.schedule_scraping()

        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            self.logger.info("Scheduler stopped by user")
        except Exception as e:
            self.logger.error(f"Scheduler error: {str(e)}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get accumulated statistics."""
        return self.stats

    def get_articles(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        source_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get scraped articles.

        Args:
            category: Filter by category (local/national)
            limit: Maximum number of articles to return
            source_id: Filter by source ID

        Returns:
            List of article dictionaries
        """
        articles = []

        try:
            for source_dir in self.data_dir.glob("*"):
                if not source_dir.is_dir():
                    continue

                source_name = source_dir.name

                # Filter by source ID if specified
                if source_id and source_name != source_id:
                    continue

                for article_file in sorted(
                    source_dir.glob("*.json"),
                    key=lambda x: x.stat().st_mtime,
                    reverse=True,
                ):
                    if len(articles) >= limit:
                        return articles

                    try:
                        with open(article_file, "r", encoding="utf-8") as f:
                            article_data = json.load(f)

                        # Filter by category if specified
                        if category and article_data.get("category") != category:
                            continue

                        article_data["source_id"] = source_name
                        articles.append(article_data)

                    except Exception as e:
                        self.logger.debug(f"Error reading article {article_file}: {str(e)}")
                        continue

        except Exception as e:
            self.logger.error(f"Error getting articles: {str(e)}")

        return articles

    def get_source_config(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific source."""
        for source in self.sources:
            if source.get("id") == source_id:
                return source
        return None


def main():
    """CLI interface for the scraper manager."""
    parser = argparse.ArgumentParser(
        description="Kronpapir News Scraper Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scrapers.scraper_manager --mode run-all
  python -m scrapers.scraper_manager --mode run-local
  python -m scrapers.scraper_manager --mode run-national
  python -m scrapers.scraper_manager --mode run --source mybrasov
  python -m scrapers.scraper_manager --mode schedule
  python -m scrapers.scraper_manager --mode cleanup
  python -m scrapers.scraper_manager --mode stats
  python -m scrapers.scraper_manager --mode articles --category local --limit 50
        """,
    )

    parser.add_argument(
        "--mode",
        choices=[
            "run-all",
            "run-local",
            "run-national",
            "run",
            "schedule",
            "cleanup",
            "stats",
            "articles",
        ],
        default="run-all",
        help="Operation mode (default: run-all)",
    )

    parser.add_argument(
        "--source",
        help="Source ID to scrape (for 'run' mode)",
    )

    parser.add_argument(
        "--category",
        choices=["local", "national"],
        help="Category filter (for 'articles' and 'run' modes)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Limit number of articles (for 'articles' mode)",
    )

    parser.add_argument(
        "--config",
        default="config/sources.yaml",
        help="Path to configuration file",
    )

    parser.add_argument(
        "--data-dir",
        default="data/articles",
        help="Path to data directory",
    )

    args = parser.parse_args()

    # Create manager
    manager = ScraperManager(config_file=args.config, data_dir=args.data_dir)

    # Handle commands
    if args.mode == "run-all":
        manager.scrape_all()

    elif args.mode == "run-local":
        manager.scrape_all(category="local")

    elif args.mode == "run-national":
        manager.scrape_all(category="national")

    elif args.mode == "run":
        if args.source:
            source_config = manager.get_source_config(args.source)
            if source_config:
                manager.scrape_source(source_config)
            else:
                print(f"Source '{args.source}' not found")
        else:
            manager.scrape_all(category=args.category)

    elif args.mode == "schedule":
        manager.run_scheduler()

    elif args.mode == "cleanup":
        manager.cleanup_old_articles()

    elif args.mode == "stats":
        stats = manager.get_statistics()
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    elif args.mode == "articles":
        articles = manager.get_articles(
            category=args.category,
            limit=args.limit,
            source_id=args.source,
        )
        print(json.dumps(articles, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
