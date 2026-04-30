#!/usr/bin/env python3
"""
Test script for Kronpapir scraper system.
Provides examples and testing utilities for the scraping system.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

from scrapers import ScraperManager, Article
from scrapers.base_scraper import BaseScraper


def setup_logging():
    """Setup logging for tests."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(name)s - %(levelname)s - %(message)s",
    )


def test_article_creation():
    """Test creating and serializing an Article object."""
    print("\n=== Testing Article Creation ===")

    article = Article(
        title="Test Article: Noutăți din Brașov",
        content="This is test content with Romanian characters: ă, â, î, ș, ț",
        source="Test Source",
        url="https://example.com/article",
        image_url="https://example.com/image.jpg",
        category="local",
    )

    print(f"Title: {article.title}")
    print(f"Source: {article.source}")
    print(f"Category: {article.category}")
    print(f"URL Hash: {article.get_url_hash()}")

    article_dict = article.to_dict()
    print(f"Serialized: {json.dumps(article_dict, ensure_ascii=False, indent=2)}")

    return True


def test_config_loading():
    """Test loading configuration from YAML."""
    print("\n=== Testing Configuration Loading ===")

    try:
        manager = ScraperManager()
        print(f"Loaded {len(manager.sources)} sources")

        local_sources = [s for s in manager.sources if s.get("category") == "local"]
        national_sources = [s for s in manager.sources if s.get("category") == "national"]

        print(f"  - Local sources: {len(local_sources)}")
        for source in local_sources[:3]:
            print(f"    - {source['id']}: {source['name']}")

        print(f"  - National sources: {len(national_sources)}")
        for source in national_sources[:3]:
            print(f"    - {source['id']}: {source['name']}")

        return True

    except Exception as e:
        print(f"Error: {str(e)}")
        return False


def test_scraper_creation():
    """Test creating scraper instances."""
    print("\n=== Testing Scraper Creation ===")

    try:
        manager = ScraperManager()

        # Test RSS scraper creation
        rss_source = None
        web_source = None

        for source in manager.sources:
            if source.get("type") == "rss" and not rss_source:
                rss_source = source
            elif source.get("type") == "scrape" and not web_source:
                web_source = source

        if rss_source:
            print(f"Creating RSS scraper for: {rss_source['name']}")
            scraper = manager._create_scraper(rss_source)
            if scraper:
                print(f"  - Scraper type: {scraper.__class__.__name__}")
                print(f"  - Source: {scraper.source_name}")
                scraper.close()
            else:
                print("  - Failed to create RSS scraper")

        if web_source:
            print(f"Creating web scraper for: {web_source['name']}")
            scraper = manager._create_scraper(web_source)
            if scraper:
                print(f"  - Scraper type: {scraper.__class__.__name__}")
                print(f"  - Source: {scraper.source_name}")
                scraper.close()
            else:
                print("  - Failed to create web scraper")

        return True

    except Exception as e:
        print(f"Error: {str(e)}")
        return False


def test_article_storage():
    """Test storing and retrieving articles."""
    print("\n=== Testing Article Storage ===")

    try:
        manager = ScraperManager()

        # Create test articles
        test_articles = [
            Article(
                title="Test Article 1: Brașov News",
                content="Content about Brașov with special chars: ă, ț",
                source="Test Source",
                url="https://example.com/article1",
                category="local",
            ),
            Article(
                title="Test Article 2: National News",
                content="Content about national events",
                source="Test Source",
                url="https://example.com/article2",
                category="national",
            ),
        ]

        data_dir = Path("data/test_articles")
        data_dir.mkdir(parents=True, exist_ok=True)

        for article in test_articles:
            filepath = data_dir / f"{article.get_url_hash()}.json"
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(article.to_dict(), f, ensure_ascii=False, indent=2)
            print(f"Saved: {article.title[:40]}...")

        # Read back
        articles_read = []
        for filepath in data_dir.glob("*.json"):
            with open(filepath, "r", encoding="utf-8") as f:
                articles_read.append(json.load(f))

        print(f"Read back {len(articles_read)} articles")

        for article in articles_read:
            print(f"  - {article['title'][:40]}... ({article['category']})")

        return True

    except Exception as e:
        print(f"Error: {str(e)}")
        return False


def test_deduplication():
    """Test deduplication logic."""
    print("\n=== Testing Deduplication ===")

    article1 = Article(
        title="Test Article",
        content="Test content",
        source="Test",
        url="https://example.com/article",
        category="local",
    )

    article2 = Article(
        title="Test Article",
        content="Test content",
        source="Test",
        url="https://example.com/article",  # Same URL
        category="local",
    )

    url_hash_1 = article1.get_url_hash()
    url_hash_2 = article2.get_url_hash()
    content_hash_1 = article1.get_content_hash()
    content_hash_2 = article2.get_content_hash()

    print(f"Article 1 URL hash: {url_hash_1}")
    print(f"Article 2 URL hash: {url_hash_2}")
    print(f"URL hashes match: {url_hash_1 == url_hash_2}")

    print(f"Article 1 content hash: {content_hash_1}")
    print(f"Article 2 content hash: {content_hash_2}")
    print(f"Content hashes match: {content_hash_1 == content_hash_2}")

    return True


def test_statistics():
    """Test statistics generation."""
    print("\n=== Testing Statistics ===")

    try:
        manager = ScraperManager()
        stats = manager.get_statistics()

        print(f"Total scrape runs: {len(stats.get('runs', []))}")

        if stats.get("runs"):
            latest_run = stats["runs"][-1]
            print(f"Latest run: {latest_run['timestamp']}")
            print(f"  - Total sources: {latest_run['total_sources']}")
            print(f"  - Successful: {latest_run['summary']['successful_sources']}")
            print(f"  - Failed: {latest_run['summary']['failed_sources']}")
            print(f"  - Articles saved: {latest_run['summary']['total_articles_saved']}")
            print(f"  - Duplicates: {latest_run['summary']['total_duplicates']}")

        return True

    except Exception as e:
        print(f"Error: {str(e)}")
        return False


def test_article_retrieval():
    """Test retrieving articles."""
    print("\n=== Testing Article Retrieval ===")

    try:
        manager = ScraperManager()

        print("Retrieving articles...")
        articles = manager.get_articles(limit=10)
        print(f"Found {len(articles)} articles")

        if articles:
            print("\nLatest articles:")
            for i, article in enumerate(articles[:5], 1):
                print(
                    f"{i}. {article['title'][:50]}..."
                    f" ({article['source']}, {article['category']})"
                )

        # By category
        print("\nLocal articles:")
        local_articles = manager.get_articles(category="local", limit=5)
        print(f"  Found {len(local_articles)} local articles")

        print("National articles:")
        national_articles = manager.get_articles(category="national", limit=5)
        print(f"  Found {len(national_articles)} national articles")

        return True

    except Exception as e:
        print(f"Error: {str(e)}")
        return False


def test_romanian_encoding():
    """Test Romanian character encoding."""
    print("\n=== Testing Romanian Character Encoding ===")

    romanian_chars = {
        "ă": "a with breve",
        "â": "a with circumflex",
        "î": "i with circumflex",
        "ș": "s with comma below",
        "ț": "t with comma below",
    }

    test_text = "Brașov și Covasna sunt în Transilvania"

    print(f"Test text: {test_text}")
    print(f"Text length: {len(test_text)}")

    article = Article(
        title=test_text,
        content=f"Informații din {', '.join(romanian_chars.keys())} - test",
        source="Test",
        url="https://example.com",
        category="local",
    )

    article_dict = article.to_dict()
    serialized = json.dumps(article_dict, ensure_ascii=False, indent=2)

    print("\nSerialized JSON with Romanian characters:")
    print(serialized[:200] + "...")

    # Verify characters are preserved
    deserialized = json.loads(serialized)
    print(f"\nTitle after deserialization: {deserialized['title']}")
    print(f"Characters preserved: {deserialized['title'] == test_text}")

    return True


def print_summary(results):
    """Print test summary."""
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)

    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {test_name}: {status}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\nTotal: {passed}/{total} tests passed")

    return all(results.values())


def main():
    """Run all tests."""
    print("=" * 50)
    print("KRONPAPIR SCRAPER TEST SUITE")
    print("=" * 50)

    setup_logging()

    results = {}

    # Run tests
    results["Article Creation"] = test_article_creation()
    results["Configuration Loading"] = test_config_loading()
    results["Scraper Creation"] = test_scraper_creation()
    results["Article Storage"] = test_article_storage()
    results["Deduplication"] = test_deduplication()
    results["Statistics"] = test_statistics()
    results["Article Retrieval"] = test_article_retrieval()
    results["Romanian Encoding"] = test_romanian_encoding()

    # Print summary
    all_passed = print_summary(results)

    print("\nTo run actual scraping:")
    print("  python3 main.py scrape --all")
    print("  python3 main.py scrape --local")
    print("  python3 main.py articles --limit 20")

    return 0 if all_passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
