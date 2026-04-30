# Kronpapir Files Index

Complete reference of all files in the Kronpapir news aggregator project.

## Project Root Files

### Configuration & Dependencies
- **requirements.txt** (185 bytes)
  - List of all Python dependencies (11 packages)
  - Compatible with pip install -r

- **.env.example** (554 bytes)
  - Template for environment variables
  - Copy to .env and customize as needed
  - Includes logging level, intervals, retention settings

### Main Application
- **main.py** (5.0K)
  - CLI entry point for the application
  - 5 commands: scrape, schedule, cleanup, stats, articles
  - argparse-based user-friendly interface
  - Error handling and user feedback

- **__init__.py** (494 bytes)
  - Package initialization
  - Exports public API: ScraperManager, scrapers
  - Version and metadata

### Testing
- **test_scraper.py** (11K)
  - Comprehensive test suite with 8 test functions
  - Tests article creation, storage, deduplication
  - Configuration and scraper instantiation tests
  - Statistics and retrieval validation
  - Romanian character encoding tests
  - Runnable with: python3 test_scraper.py

### Documentation
- **README.md** (9.5K)
  - Complete feature documentation
  - Installation instructions
  - Configuration reference
  - Usage examples and API
  - Troubleshooting guide
  - Advanced usage patterns

- **SETUP_GUIDE.md** (12K)
  - Step-by-step installation guide
  - Virtual environment setup
  - Configuration walkthroughs
  - Common usage patterns
  - CSS selector debugging guide
  - Systemd service setup
  - Docker deployment
  - Performance optimization
  - Monitoring and maintenance

- **FILES_INDEX.md** (this file)
  - Reference of all project files
  - File descriptions and purposes

## Configuration Directory (config/)

- **__init__.py** (minimal)
  - Package marker for config module

- **sources.yaml** (8.3K)
  - **Core configuration file**
  - 14 news sources (8 local + 6 national)
  - Each source includes:
    - id, name, url, type (rss/scrape)
    - category (local/national)
    - enabled flag
    - CSS selectors for title, content, date, image, links
    - retry_attempts, timeout settings
  - Global scraper settings:
    - rate_limit_delay (1 second default)
    - max_retries (3 default)
    - user_agents (4 variations)
    - deduplication strategy
    - article retention (30 days)
  - Scheduling configuration:
    - local_sources_interval (3600 seconds / 1 hour)
    - national_sources_interval (7200 seconds / 2 hours)
    - cleanup_interval (86400 seconds / 1 day)

## Scrapers Module (scrapers/)

### Core Classes

- **__init__.py** (357 bytes)
  - Module exports: BaseScraper, Article, RSSscraper, WebScraper, ScraperManager
  - Makes classes easily importable

- **base_scraper.py** (17K)
  - **Article class** (data model)
    - Fields: title, content, source, url, date, image_url, category, original_text
    - Methods: to_dict(), get_url_hash(), get_content_hash()
  - **BaseScraper abstract class** (main file)
    - HTTP request handling with retry logic
    - Session management with connection pooling
    - HTML parsing using BeautifulSoup
    - CSS selector-based content extraction
    - Deduplication (URL or content hash)
    - JSON file storage with UTF-8 encoding
    - Multi-level logging (file + console)
    - User-agent rotation
    - Rate limiting between requests
    - Methods:
      - fetch_page(): HTTP request with retries
      - parse_html(): BeautifulSoup wrapper
      - extract_text(): CSS selector extraction
      - extract_attribute(): Attribute extraction
      - parse_article(): Article parsing
      - is_duplicate(): Deduplication check
      - mark_as_processed(): Track processed articles
      - save_article(): Store to JSON
      - run(): Main execution with stats
      - close(): Resource cleanup

- **rss_scraper.py** (5.1K)
  - **RSSscraper class** (inherits BaseScraper)
  - Specialized for RSS/Atom feeds
  - Uses feedparser library
  - Follows article links to get full content
  - Date parsing from feed metadata
  - Methods:
    - scrape(): Main RSS scraping logic
    - _parse_rss_entry(): Parse individual entries
    - _parse_date(): Date extraction and parsing

- **web_scraper.py** (6.2K)
  - **WebScraper class** (inherits BaseScraper)
  - Specialized for traditional web pages
  - Supports pagination automatically
  - Extracts article links from listings
  - Parses individual article pages
  - Flexible date format parsing
  - Methods:
    - scrape(): Main web scraping logic
    - _extract_article_links(): Homepage link extraction
    - _fetch_and_parse_article(): Individual article parsing
    - _extract_date(): Date parsing from pages

- **scraper_manager.py** (17K)
  - **ScraperManager class** (orchestrator)
  - Loads configuration from YAML
  - Creates appropriate scraper instances
  - Manages scheduled scraping
  - Tracks comprehensive statistics
  - Handles error recovery
  - CLI command handler
  - Methods:
    - scrape_source(): Scrape single source
    - scrape_all(): Batch scraping with filters
    - schedule_scraping(): Setup scheduled jobs
    - run_scheduler(): Main scheduler loop
    - cleanup_old_articles(): Remove old data
    - get_statistics(): Retrieve stats
    - get_articles(): Query stored articles
    - get_source_config(): Configuration lookup

## Data Directory (data/) - Auto-created

Structure created during scraping:

```
data/
├── articles/
│   ├── mybrasov/
│   │   ├── abc123def.json      (Article hash as filename)
│   │   ├── def456ghi.json
│   │   └── ...
│   ├── newsbv/
│   │   └── ...
│   ├── <source_id>/
│   │   └── <url_hash>.json
│   ├── <source_id>_processed.json (Deduplication tracking)
│   └── scraper_stats.json      (Statistics file)
└── processed/
    └── (Reserved for future processing)
```

## Logs Directory (logs/) - Auto-created

Log files created during execution:

```
logs/
├── manager.log           (ScraperManager activity)
├── mybrasov.log         (Source-specific logs)
├── newsbv.log
├── brasovstiri.log
└── <source_id>.log
```

## File Statistics

| Category | Count | Size |
|----------|-------|------|
| Python files | 9 | 70K |
| Configuration | 1 | 8.3K |
| Documentation | 3 | 31.5K |
| Support files | 2 | 1K |
| **Total** | **15** | **110.8K** |

## Code Statistics

| Metric | Count |
|--------|-------|
| Total lines of code | 3,330+ |
| Python source lines | 2,500+ |
| Documentation lines | 830+ |
| Classes | 7 |
| Methods | 60+ |
| CLI commands | 5 |
| News sources configured | 14 |
| CSS selectors defined | 50+ |

## Key File Purposes

### For Users
1. Start with **README.md** - understand features
2. Follow **SETUP_GUIDE.md** - install and configure
3. Run **test_scraper.py** - verify installation
4. Use **main.py** - daily operations

### For Developers
1. Review **config/sources.yaml** - understand configuration
2. Study **scrapers/base_scraper.py** - core functionality
3. Check **scrapers/rss_scraper.py** - RSS implementation
4. Check **scrapers/web_scraper.py** - web scraping implementation
5. Review **scrapers/scraper_manager.py** - orchestration logic

### For DevOps
1. Check **requirements.txt** - dependencies
2. Review **SETUP_GUIDE.md** sections on Systemd and Docker
3. Monitor **logs/** directory
4. Configure **config/sources.yaml** scheduling

## File Dependencies

```
main.py
├── scrapers.scraper_manager.ScraperManager
│   ├── config/sources.yaml
│   ├── scrapers/scraper_manager.py
│   │   ├── scrapers/base_scraper.py (Article class)
│   │   ├── scrapers/rss_scraper.py
│   │   ├── scrapers/web_scraper.py
│   │   └── external libraries (feedparser, requests, bs4, yaml)

test_scraper.py
└── scrapers module (all above)
```

## Configuration Locations

- Source configuration: `config/sources.yaml`
- Environment variables: `.env` (copied from .env.example)
- Scraping output: `data/articles/<source_id>/`
- Logs: `logs/<source_id>.log`
- Statistics: `data/articles/scraper_stats.json`
- Processed URLs: `data/articles/<source_id>_processed.json`

## Quick File Reference

Need to...

- **Change news sources?** → Edit `config/sources.yaml`
- **Adjust scraping intervals?** → Edit `config/sources.yaml` scheduling section
- **Fix CSS selectors?** → Edit `config/sources.yaml` selectors
- **Start scraping?** → Run `python3 main.py scrape --all`
- **Add new functionality?** → Modify `scrapers/scraper_manager.py` or extend base classes
- **Debug issues?** → Check `logs/manager.log` or specific source logs
- **Test everything?** → Run `python3 test_scraper.py`
- **Deploy to production?** → See SETUP_GUIDE.md Systemd/Docker sections

## File Sizes & Modification Dates

All files created on 2026-02-09:

| File | Size | Purpose |
|------|------|---------|
| config/sources.yaml | 8.3K | Configuration |
| scrapers/base_scraper.py | 17K | Core logic |
| scrapers/scraper_manager.py | 17K | Orchestration |
| main.py | 5.0K | CLI interface |
| test_scraper.py | 11K | Testing |
| README.md | 9.5K | User docs |
| SETUP_GUIDE.md | 12K | Setup docs |
| requirements.txt | 185B | Dependencies |

## Final Notes

- All Python files are Python 3.10+ compatible
- All files use UTF-8 encoding for Romanian character support
- Configuration is externalized in YAML for easy modification
- Logging is comprehensive with file and console output
- Code includes type hints throughout
- Docstrings document all public methods
- Error handling is production-quality

---

**Total Project**: 15 files, 3,330+ lines of code, complete documentation
