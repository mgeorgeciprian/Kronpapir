"""
Article processing pipeline for kronpapir.ro.
Handles batch processing, deduplication, and daily summaries.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib

from .rewriter import ArticleRewriter


@dataclass
class ProcessingStats:
    """Statistics for a processing run."""
    total_articles: int = 0
    processed_articles: int = 0
    skipped_articles: int = 0
    failed_articles: int = 0
    total_tokens_used: int = 0
    total_cost: float = 0.0
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0


class ArticleProcessor:
    """Pipeline for processing articles from raw to processed."""

    def __init__(
        self,
        rewriter: ArticleRewriter,
        articles_dir: str = "data/articles",
        processed_dir: str = "data/processed",
    ):
        """Initialize processor."""
        self.rewriter = rewriter
        self.articles_dir = Path(articles_dir)
        self.processed_dir = Path(processed_dir)

        # Ensure directories exist
        self.articles_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger("kronpapir.processor")
        self.logger.setLevel(logging.INFO)

        # Add file handler if not exists
        if not self.logger.handlers:
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            fh = logging.FileHandler(log_dir / "processor.log")
            fh.setLevel(logging.INFO)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            fh.setFormatter(formatter)
            self.logger.addHandler(fh)

        # Track processed article hashes to avoid duplicates
        self.processed_hashes = self._load_processed_hashes()

    def _load_processed_hashes(self) -> set:
        """Load hashes of already processed articles."""
        hashes_file = self.processed_dir / "processed_hashes.json"
        if hashes_file.exists():
            try:
                with open(hashes_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data.get("hashes", []))
            except Exception as e:
                self.logger.warning(f"Could not load processed hashes: {e}")
        return set()

    def _save_processed_hashes(self):
        """Save processed article hashes."""
        hashes_file = self.processed_dir / "processed_hashes.json"
        try:
            with open(hashes_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "hashes": list(self.processed_hashes),
                        "updated": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            self.logger.error(f"Could not save processed hashes: {e}")

    def _hash_article(self, article: Dict[str, Any]) -> str:
        """Generate hash for article deduplication."""
        text = article.get("text", "") + article.get("title", "")
        return hashlib.md5(text.encode()).hexdigest()

    def _load_article(self, filepath: Path) -> Optional[Dict[str, Any]]:
        """Load article from JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading article {filepath}: {e}")
            return None

    def _save_processed_article(self, article_data: Dict[str, Any], filename: str):
        """Save processed article to processed directory."""
        try:
            output_path = self.processed_dir / filename
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(article_data, f, indent=2, ensure_ascii=False)
            self.logger.debug(f"Saved processed article: {filename}")
        except Exception as e:
            self.logger.error(f"Error saving processed article: {e}")

    def _get_raw_articles(self) -> List[tuple[Path, Dict[str, Any]]]:
        """Get all unprocessed articles from articles directory."""
        articles = []
        json_files = list(self.articles_dir.glob("*.json"))

        if not json_files:
            self.logger.info(f"No JSON articles found in {self.articles_dir}")
            return articles

        for filepath in json_files:
            article = self._load_article(filepath)
            if article:
                articles.append((filepath, article))

        return articles

    def process_articles(
        self,
        batch_size: int = 5,
        generate_summary: bool = True,
        moderate_content: bool = True,
        refine_output: bool = False,
    ) -> ProcessingStats:
        """
        Process articles in batches.

        Args:
            batch_size: Number of articles to process at once
            generate_summary: Whether to generate daily summary
            moderate_content: Whether to check articles for policy violations
            refine_output: Whether to check quality and suggest refinements

        Returns:
            ProcessingStats with results
        """
        stats = ProcessingStats(start_time=datetime.now().isoformat())

        raw_articles = self._get_raw_articles()
        if not raw_articles:
            self.logger.info("No articles to process")
            stats.end_time = datetime.now().isoformat()
            return stats

        self.logger.info(
            f"Found {len(raw_articles)} articles in {self.articles_dir}"
        )

        # Filter out already processed articles
        articles_to_process = []
        for filepath, article in raw_articles:
            article_hash = self._hash_article(article)
            if article_hash in self.processed_hashes:
                stats.skipped_articles += 1
                self.logger.debug(f"Skipping already processed article: {filepath.name}")
            else:
                articles_to_process.append((filepath, article, article_hash))

        stats.total_articles = len(articles_to_process)
        self.logger.info(
            f"Processing {stats.total_articles} new articles "
            f"(skipped {stats.skipped_articles} duplicates)"
        )

        # Process in batches
        for i in range(0, len(articles_to_process), batch_size):
            batch = articles_to_process[i : i + batch_size]
            self._process_batch(batch, stats, moderate_content, refine_output)

        # Generate daily summary if requested
        if generate_summary and articles_to_process:
            self._generate_daily_summary(articles_to_process)

        # Save updated hashes
        self._save_processed_hashes()

        stats.end_time = datetime.now().isoformat()
        start = datetime.fromisoformat(stats.start_time)
        end = datetime.fromisoformat(stats.end_time)
        stats.duration_seconds = (end - start).total_seconds()

        # Get final stats from rewriter
        usage_stats = self.rewriter.get_usage_stats()
        stats.total_tokens_used = usage_stats["session"]["total_tokens"]
        stats.total_cost = float(
            usage_stats["session"]["estimated_cost"].replace("$", "")
        )

        self.logger.info(f"Processing complete: {stats}")
        return stats

    def _process_batch(
        self,
        batch: List[tuple[Path, Dict[str, Any], str]],
        stats: ProcessingStats,
        moderate_content: bool,
        refine_output: bool,
    ):
        """Process a batch of articles."""
        for filepath, article, article_hash in batch:
            try:
                self.logger.info(f"Processing: {filepath.name}")

                # Main rewriting
                rewrite_result = self.rewriter.rewrite_article(article)

                if rewrite_result["status"] != "success":
                    self.logger.warning(
                        f"Failed to rewrite article {filepath.name}: "
                        f"{rewrite_result.get('error', 'unknown')}"
                    )
                    stats.failed_articles += 1
                    continue

                # Generate headlines
                headline_result = self.rewriter.generate_headline(article)

                # Categorize
                category_result = self.rewriter.categorize(article)

                # Moderate if requested
                moderation_result = None
                if moderate_content:
                    moderation_result = self.rewriter.moderate_content(article)

                # Refine if requested
                refine_result = None
                if refine_output:
                    refine_result = self.rewriter.refine_article(
                        rewrite_result["rewritten_text"]
                    )

                # Compile results
                processed_article = {
                    "original": article,
                    "rewritten": rewrite_result,
                    "headlines": headline_result,
                    "category": category_result,
                    "moderation": moderation_result,
                    "quality_review": refine_result,
                    "processed_at": datetime.now().isoformat(),
                }

                # Save
                output_filename = f"processed_{filepath.stem}.json"
                self._save_processed_article(processed_article, output_filename)

                # Mark as processed
                self.processed_hashes.add(article_hash)
                stats.processed_articles += 1

                self.logger.info(f"Successfully processed: {filepath.name}")

            except Exception as e:
                self.logger.error(f"Error processing article {filepath.name}: {e}")
                stats.failed_articles += 1

    def _generate_daily_summary(self, articles: List[tuple[Path, Dict[str, Any], str]]):
        """Generate daily national summary from processed articles."""
        try:
            # Extract just the article dicts
            article_dicts = [article for _, article, _ in articles]

            if not article_dicts:
                self.logger.warning("No articles for summary")
                return

            self.logger.info(f"Generating daily summary for {len(article_dicts)} articles")

            summary_result = self.rewriter.summarize_national(article_dicts)

            if summary_result["status"] != "success":
                self.logger.warning(
                    f"Failed to generate summary: {summary_result.get('error')}"
                )
                return

            # Save summary
            summary_data = {
                "type": "daily_national_summary",
                "article_count": len(article_dicts),
                "summary": summary_result["summary"],
                "generated_at": datetime.now().isoformat(),
                "tokens_used": summary_result.get("tokens_used", 0),
                "cost": summary_result.get("cost", 0),
            }

            summary_filename = f"daily_summary_{datetime.now().strftime('%Y%m%d')}.json"
            self._save_processed_article(summary_data, summary_filename)

            self.logger.info(f"Daily summary saved: {summary_filename}")

        except Exception as e:
            self.logger.error(f"Error generating daily summary: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get current processing statistics."""
        return {
            "processed_articles_count": len(self.processed_hashes),
            "articles_directory": str(self.articles_dir),
            "processed_directory": str(self.processed_dir),
            "rewriter_stats": self.rewriter.get_usage_stats(),
        }


def run_cli():
    """CLI entry point for article processing."""
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Process articles for kronpapir.ro using Claude AI"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Number of articles per batch (default: 5)",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip daily summary generation",
    )
    parser.add_argument(
        "--no-moderation",
        action="store_true",
        help="Skip content moderation",
    )
    parser.add_argument(
        "--refine",
        action="store_true",
        help="Enable quality refinement checks",
    )
    parser.add_argument(
        "--articles-dir",
        default="data/articles",
        help="Directory with raw articles",
    )
    parser.add_argument(
        "--processed-dir",
        default="data/processed",
        help="Directory for processed articles",
    )

    args = parser.parse_args()

    # Load configuration from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
    max_tokens = int(os.getenv("MAX_TOKENS_PER_ARTICLE", "1500"))
    daily_budget = int(os.getenv("DAILY_TOKEN_BUDGET", "500000"))

    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment")
        return

    # Initialize
    rewriter = ArticleRewriter(
        api_key=api_key,
        model=model,
        max_tokens_per_article=max_tokens,
        daily_token_budget=daily_budget,
    )

    processor = ArticleProcessor(
        rewriter=rewriter,
        articles_dir=args.articles_dir,
        processed_dir=args.processed_dir,
    )

    # Process
    stats = processor.process_articles(
        batch_size=args.batch_size,
        generate_summary=not args.no_summary,
        moderate_content=not args.no_moderation,
        refine_output=args.refine,
    )

    # Print results
    print("\n" + "=" * 60)
    print("PROCESSING COMPLETE")
    print("=" * 60)
    print(f"Total articles: {stats.total_articles}")
    print(f"Processed: {stats.processed_articles}")
    print(f"Skipped (duplicates): {stats.skipped_articles}")
    print(f"Failed: {stats.failed_articles}")
    print(f"Duration: {stats.duration_seconds:.2f}s")
    print(f"Tokens used: {stats.total_tokens_used}")
    print(f"Estimated cost: ${stats.total_cost:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    run_cli()
