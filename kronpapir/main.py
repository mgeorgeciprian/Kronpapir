#!/usr/bin/env python3
"""
Main entry point for Kronpapir news aggregator.
Provides CLI interface and orchestration.
"""

import argparse
import sys
from pathlib import Path

from scrapers.scraper_manager import ScraperManager


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="kronpapir",
        description="Kronpapir - Romanian Local News Aggregator (Brașov/Covasna)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
USAGE EXAMPLES:

Scraping:
  python main.py scrape --all              # Scrape all sources
  python main.py scrape --local            # Scrape local sources only
  python main.py scrape --national         # Scrape national sources only
  python main.py scrape --source mybrasov  # Scrape specific source

Scheduling:
  python main.py schedule                  # Run continuous scheduler

Maintenance:
  python main.py cleanup                   # Remove old articles
  python main.py stats                     # Show statistics

Retrieval:
  python main.py articles                  # Show recent articles
  python main.py articles --category local # Show local news
  python main.py articles --limit 50       # Show 50 articles
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Scrape command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape news sources")
    scrape_group = scrape_parser.add_mutually_exclusive_group(required=True)
    scrape_group.add_argument("--all", action="store_true", help="Scrape all sources")
    scrape_group.add_argument("--local", action="store_true", help="Scrape local sources only")
    scrape_group.add_argument("--national", action="store_true", help="Scrape national sources only")
    scrape_group.add_argument("--source", type=str, help="Scrape specific source by ID")

    # Schedule command
    subparsers.add_parser("schedule", help="Run continuous scheduler")

    # Cleanup command
    subparsers.add_parser("cleanup", help="Clean up old articles")

    # Statistics command
    subparsers.add_parser("stats", help="Show scraping statistics")

    # Articles command
    articles_parser = subparsers.add_parser("articles", help="Get scraped articles")
    articles_parser.add_argument(
        "--category",
        choices=["local", "national"],
        help="Filter by category",
    )
    articles_parser.add_argument(
        "--source",
        type=str,
        help="Filter by source ID",
    )
    articles_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of articles to display (default: 50)",
    )

    # Global options
    parser.add_argument(
        "--config",
        default="config/sources.yaml",
        help="Path to configuration file (default: config/sources.yaml)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/articles",
        help="Path to data directory (default: data/articles)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    # Check if command was provided
    if not args.command:
        parser.print_help()
        return 1

    # Create manager
    try:
        manager = ScraperManager(config_file=args.config, data_dir=args.data_dir)
    except Exception as e:
        print(f"Error: Failed to initialize scraper manager: {str(e)}", file=sys.stderr)
        return 1

    # Execute commands
    try:
        if args.command == "scrape":
            if args.all:
                manager.scrape_all()
            elif args.local:
                manager.scrape_all(category="local")
            elif args.national:
                manager.scrape_all(category="national")
            elif args.source:
                source_config = manager.get_source_config(args.source)
                if source_config:
                    manager.scrape_source(source_config)
                else:
                    print(f"Error: Source '{args.source}' not found", file=sys.stderr)
                    return 1

        elif args.command == "schedule":
            manager.run_scheduler()

        elif args.command == "cleanup":
            manager.cleanup_old_articles()

        elif args.command == "stats":
            import json
            stats = manager.get_statistics()
            print(json.dumps(stats, ensure_ascii=False, indent=2))

        elif args.command == "articles":
            import json
            articles = manager.get_articles(
                category=args.category,
                limit=args.limit,
                source_id=args.source,
            )
            print(json.dumps(articles, ensure_ascii=False, indent=2))

        return 0

    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
