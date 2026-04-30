# Kronpapir Setup Guide

A complete guide to installing, configuring, and running the Kronpapir Romanian local news aggregator.

## Quick Start (5 minutes)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Test the Installation

```bash
# Verify imports work
python3 -c "from scrapers import ScraperManager; print('Installation OK')"

# Run a quick scrape
python3 main.py scrape --source mybrasov
```

### 3. View Results

```bash
# See recently scraped articles
python3 main.py articles --limit 10
```

## Detailed Setup

### Prerequisites

- Python 3.10+
- pip or conda
- 500MB free disk space (for articles cache)
- Internet connection for scraping

### Step 1: Environment Setup

#### Using Virtual Environment (Recommended)

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Upgrade pip
pip install --upgrade pip
```

#### Using Conda

```bash
conda create -n kronpapir python=3.10
conda activate kronpapir
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- **requests**: HTTP library
- **beautifulsoup4**: HTML parsing
- **lxml**: Fast XML parser
- **feedparser**: RSS feed parsing
- **schedule**: Job scheduling
- **pyyaml**: Configuration parsing
- **python-dotenv**: Environment variables

### Step 3: Verify Installation

```bash
# Check all imports
python3 << 'EOF'
import requests
import feedparser
from bs4 import BeautifulSoup
import yaml
import schedule
from scrapers import ScraperManager

print("All dependencies installed successfully!")
EOF
```

### Step 4: Configure Sources

1. Review `config/sources.yaml`:
```bash
cat config/sources.yaml | head -50
```

2. Enable/disable sources by setting `enabled: true/false`

3. Adjust CSS selectors if needed (see Debugging CSS Selectors below)

### Step 5: Create Output Directories

```bash
mkdir -p data/articles logs
```

These are created automatically on first run, but you can create them manually.

## Configuration

### Basic Configuration

Edit `config/sources.yaml`:

```yaml
sources:
  - id: mybrasov
    name: "My Brașov"
    url: "https://www.mybrasov.ro"
    type: "rss"
    enabled: true  # Set to false to disable

  - id: newsbv
    name: "News BV"
    url: "https://newsbv.ro"
    type: "scrape"
    enabled: true
```

### Scraping Intervals

Modify scheduling section:

```yaml
scheduling:
  local_sources_interval: 3600    # Scrape local sources every hour
  national_sources_interval: 7200  # Every 2 hours
  cleanup_interval: 86400         # Clean old articles daily
  max_articles_per_source: 100
```

### Rate Limiting

Adjust in scraper_config:

```yaml
scraper_config:
  rate_limit_delay: 1              # Seconds between requests
  default_timeout: 10              # Request timeout in seconds
  max_retries: 3                   # Retry failed requests
```

### Article Retention

```yaml
scraper_config:
  article_retention_days: 30       # Keep articles for 30 days
```

## Common Usage Patterns

### Pattern 1: Single Scrape

```bash
# Scrape all enabled sources
python3 main.py scrape --all

# Monitor output in real-time
python3 main.py scrape --all 2>&1 | tee scrape.log

# Scrape just local news
python3 main.py scrape --local
```

### Pattern 2: Continuous Monitoring

```bash
# Run scheduler in background
nohup python3 main.py schedule > logs/scheduler.log 2>&1 &

# Or in a screen session
screen -S kronpapir -d -m python3 main.py schedule

# Or with systemd (see Systemd Setup below)
```

### Pattern 3: Cron Job

Add to crontab:

```bash
# Edit crontab
crontab -e

# Add this line for hourly scraping
0 * * * * cd /path/to/kronpapir && python3 main.py scrape --local >> logs/cron.log 2>&1

# Every 2 hours for national news
0 */2 * * * cd /path/to/kronpapir && python3 main.py scrape --national >> logs/cron.log 2>&1
```

### Pattern 4: Analyze Articles

```bash
# Get statistics
python3 main.py stats | python3 -m json.tool

# Get articles as JSON (for processing)
python3 main.py articles --category local --limit 100 > articles.json

# Count articles
python3 main.py articles | python3 -c "import sys, json; print(len(json.load(sys.stdin)))"
```

## Debugging CSS Selectors

If articles aren't being scraped, CSS selectors may need adjustment.

### Method 1: Browser Developer Tools

1. Visit the source website
2. Right-click on article title → Inspect
3. Find the CSS class/ID/tag
4. Example: If you find `<h2 class="post-title">`, use selector `h2.post-title`

### Method 2: Test Selectors

```python
from bs4 import BeautifulSoup
import requests

# Fetch a page
url = "https://example.com"
html = requests.get(url).text
soup = BeautifulSoup(html, "lxml")

# Test selector
titles = soup.select("h2.post-title")
print(f"Found {len(titles)} titles")
for title in titles[:3]:
    print(f"  - {title.get_text(strip=True)[:50]}")
```

### Method 3: Update Configuration

In `config/sources.yaml`:

```yaml
selectors:
  title: "h2.post-title, h1.entry-title"  # Try multiple selectors
  content: "div.post-content, article.content"
  date: "span.post-date, time"
  image: "img.featured, img.thumbnail"
```

## Troubleshooting

### Issue: "Module not found" errors

**Solution**: Make sure you activated the virtual environment:
```bash
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows
```

### Issue: No articles being scraped

**Solution**:
1. Check logs: `cat logs/mybrasov.log`
2. Test manually: `python3 main.py scrape --source mybrasov -v`
3. Verify selectors (see Debugging CSS Selectors above)
4. Check if source website is accessible

### Issue: "Connection refused" or timeout errors

**Solution**:
1. Increase timeout: Edit `config/sources.yaml` - `timeout: 20`
2. Increase retry attempts: `retry_attempts: 5`
3. Add rate limiting delay: `rate_limit_delay: 2`
4. Check your internet connection

### Issue: Special characters showing as garbage

**Solution**:
1. Ensure UTF-8 encoding: `export LANG=en_US.UTF-8`
2. Check terminal supports UTF-8
3. View JSON files with UTF-8 support:
   ```bash
   python3 -c "import json; print(json.dumps(json.load(open('data/articles/mybrasov/*.json')), ensure_ascii=False, indent=2))"
   ```

### Issue: Scraping is very slow

**Solution**:
1. Reduce number of sources
2. Increase `rate_limit_delay` is fine for slow servers
3. Reduce `max_articles_per_source` to scrape fewer articles
4. Run local and national sources separately

### Issue: High memory usage

**Solution**:
1. Reduce `batch_size` in config
2. Run cleanup more frequently: `python3 main.py cleanup`
3. Reduce `article_retention_days`

## Advanced Setup

### Systemd Service

Create `/etc/systemd/system/kronpapir.service`:

```ini
[Unit]
Description=Kronpapir News Aggregator
After=network.target

[Service]
Type=simple
User=kronpapir
WorkingDirectory=/home/kronpapir/kronpapir
Environment="PATH=/home/kronpapir/kronpapir/venv/bin"
ExecStart=/home/kronpapir/kronpapir/venv/bin/python3 /home/kronpapir/kronpapir/main.py schedule
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable kronpapir
sudo systemctl start kronpapir
sudo systemctl status kronpapir
```

### Docker Deployment

Create `Dockerfile`:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py", "schedule"]
```

Build and run:
```bash
docker build -t kronpapir .
docker run -d -v kronpapir_data:/app/data kronpapir
```

### API Server

Create `api.py`:

```python
from flask import Flask, jsonify
from scrapers import ScraperManager

app = Flask(__name__)
manager = ScraperManager()

@app.route("/api/articles")
def articles():
    return jsonify(manager.get_articles())

@app.route("/api/stats")
def stats():
    return jsonify(manager.get_statistics())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

Run:
```bash
pip install flask
python3 api.py
```

## Performance Optimization

### For Production:

1. **Use PostgreSQL** instead of JSON files
2. **Add caching** (Redis, Memcached)
3. **Implement pagination** for articles
4. **Add full-text search** (Elasticsearch)
5. **Use async scraping** (asyncio, aiohttp)

### Configuration for High Volume:

```yaml
scraper_config:
  batch_size: 50                    # Process in larger batches
  rate_limit_delay: 0.5            # Faster requests (careful!)
  article_retention_days: 7        # Keep less data

scheduling:
  local_sources_interval: 1800     # Every 30 minutes
  max_articles_per_source: 50      # Fewer per source
```

## Monitoring

### View Live Logs

```bash
# Follow manager log
tail -f logs/manager.log

# Follow specific source
tail -f logs/mybrasov.log

# All sources
tail -f logs/*.log
```

### Check Health

```bash
# Is scheduler running?
ps aux | grep "python3 main.py schedule"

# Recent scrapes
python3 main.py stats | grep -A 20 '"runs"'

# Article count
python3 main.py articles | python3 -c "import sys,json; print(f'Total: {len(json.load(sys.stdin))}')"
```

### Set Up Alerts

Check if scheduler died:
```bash
while true; do
    if ! pgrep -f "python3 main.py schedule" > /dev/null; then
        echo "Kronpapir scheduler stopped!" | mail -s "Alert" admin@example.com
        # Restart it
        nohup python3 main.py schedule > logs/scheduler.log 2>&1 &
    fi
    sleep 3600  # Check every hour
done
```

## Maintenance

### Weekly Tasks

```bash
# Check logs for errors
grep "ERROR" logs/*.log

# Verify article count
python3 main.py stats | grep "articles_saved"

# Update selectors if needed
# Inspect source websites for structural changes
```

### Monthly Tasks

```bash
# Backup articles
tar -czf backups/articles_$(date +%Y%m%d).tar.gz data/articles/

# Review statistics
python3 main.py stats > reports/stats_$(date +%Y%m).txt

# Clean up very old articles
python3 main.py cleanup
```

### Quarterly Tasks

```bash
# Test all sources manually
for source in mybrasov newsbv brasovstiri; do
    python3 main.py scrape --source $source
done

# Verify no broken selectors in logs
grep "Failed to parse article" logs/*.log | wc -l
```

## Next Steps

1. **Review configuration**: Adjust `config/sources.yaml` for your needs
2. **Test scraping**: Run `python3 main.py scrape --local`
3. **View results**: Check `python3 main.py articles`
4. **Set up scheduling**: Run `python3 main.py schedule`
5. **Monitor logs**: Watch `logs/manager.log`

## Support Resources

- **Logs**: See `logs/` directory for detailed error messages
- **Configuration**: See `config/sources.yaml` comments
- **API**: See docstrings in `scrapers/*.py`
- **README**: See `README.md` for complete documentation

## Tips & Tricks

```bash
# Run multiple scrapers in parallel (if CPU allows)
for category in local national; do
    python3 main.py scrape --$category &
done
wait

# Export articles to CSV
python3 main.py articles | python3 << 'EOF'
import json, csv, sys
articles = json.load(sys.stdin)
writer = csv.DictWriter(sys.stdout, fieldnames=['title', 'source', 'date', 'url'])
writer.writeheader()
for a in articles:
    writer.writerow({k: a.get(k) for k in ['title', 'source', 'date', 'url']})
EOF

# Find all broken sources
python3 main.py scrape --all 2>&1 | grep "ERROR" | cut -d' ' -f4 | sort | uniq -c

# Compress old logs
find logs/ -mtime +30 -exec gzip {} \;
```

## Conclusion

You now have a fully configured Romanian news aggregator! Start scraping with:

```bash
python3 main.py scrape --all
```

For continuous operation:

```bash
python3 main.py schedule
```
