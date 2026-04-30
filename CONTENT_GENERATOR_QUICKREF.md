# Content Generator - Quick Reference

## Quick Start (30 seconds)

```python
from ai_agent.content_generator import ContentGenerator

gen = ContentGenerator(api_key="sk-...")

# Generate weekly summary
result = gen.generate_weekly_summary(articles, week_start=None)
print(result['content'])

# Generate local guide
result = gen.generate_local_guide("Top restaurante în Brașov")

# Generate opinion piece
result = gen.generate_opinion_piece(
    "De ce cresc prețurile chiriilor",
    context_articles
)

# Generate daily editorial
result = gen.generate_daily_editorial(top_articles)
```

## 5 Main Methods

| Method | Purpose | Length | Output |
|--------|---------|--------|--------|
| `generate_weekly_summary()` | Full week analysis | 800-1200 | Title + content |
| `generate_local_guide()` | Evergreen guides | 600-1000 | Content only |
| `generate_opinion_piece()` | Opinion/analysis | 600-900 | Content only |
| `generate_daily_editorial()` | Homepage intro | 400-600 | Content only |
| `schedule_content_calendar()` | Weekly plan | N/A | Dict of schedules |

## Input/Output

### Input Requirements
```python
# For summaries
articles_list = [
    {
        "title": "...",
        "source": "...",
        "text": "...",
        "date": "2025-02-09"
    },
    # ... more articles
]

# For guides
topic = "Top 10 restaurante în Brașov"

# For opinions
topic = "De ce cresc chiriile"
articles_context = [...]  # Background articles

# For editorials
top_articles = [...]  # Top 3-5 articles
```

### Output Format
```python
{
    "status": "success",  # or "error", "budget_exceeded"
    "content": "Full article text...",
    "content_type": "weekly_summary",  # For database filtering
    "tokens_used": 1234,
    "cost": 0.0185,
    "timestamp": "2025-02-09T15:30:00"
}
```

## Weekly Schedule

```
Monday    → Weekly Summary
Tuesday   → Daily Editorial
Wednesday → Local Guide
Thursday  → Daily Editorial
Friday    → Opinion Piece
Saturday  → Local Guide
Sunday    → Daily Editorial
```

Get today's plan:
```python
plan = gen.get_today_content_plan()
print(f"Type: {plan.content_type}, Topic: {plan.topic}")
```

## Error Handling

```python
result = gen.generate_weekly_summary(articles)

if result['status'] == 'success':
    # Save content
    save_to_db(result)
elif result['status'] == 'budget_exceeded':
    # Too many tokens used
    log("Try again tomorrow")
elif result['status'] == 'error':
    # API or validation error
    log(result['error'])
```

## Token Tracking

```python
stats = gen.get_usage_stats()

# Session stats
print(stats['session']['total_tokens'])
print(stats['session']['estimated_cost'])

# Daily stats
print(stats['daily']['total_tokens'])
print(stats['daily']['budget_remaining'])
print(stats['daily']['budget_remaining_percent'])
```

## Configuration

### Environment Variables
```bash
export ANTHROPIC_API_KEY="sk-..."
export CLAUDE_MODEL="claude-sonnet-4-5-20250929"  # Optional
export DAILY_TOKEN_BUDGET="500000"  # Optional
```

### Constructor Parameters
```python
ContentGenerator(
    api_key="sk-...",  # Or env var
    model="claude-sonnet-4-5-20250929",
    max_tokens_per_article=2000,
    daily_token_budget=500_000,
    rate_limit_requests_per_minute=60,
    processed_dir="data/processed"
)
```

## File Locations

| File | Purpose |
|------|---------|
| `ai_agent/content_generator.py` | Main implementation |
| `ai_agent/prompts.py` | All prompts (Romanian) |
| `example_content_generator.py` | Usage examples |
| `CONTENT_GENERATOR.md` | Full documentation |
| `data/processed/` | Generated content (JSON) |
| `logs/content_generator.log` | Activity log |

## Common Tasks

### Generate All Weekly Content
```python
articles = load_articles()

# Monday
weekly = gen.generate_weekly_summary(articles)

# Tuesday
daily = gen.generate_daily_editorial(articles[:5])

# Wednesday
guide1 = gen.generate_local_guide("Restaurante în Brașov")

# Friday
opinion = gen.generate_opinion_piece(
    "Impact turism",
    articles
)
```

### Batch Generation
```python
topics = [
    "Top 10 atracții în Brașov",
    "Trasee montane din Covasna",
    "Sfaturi pentru turiști",
]

results = []
for topic in topics:
    result = gen.generate_local_guide(topic)
    if result['status'] == 'success':
        results.append(result)
```

### Monitor Budget Before Generating
```python
stats = gen.get_usage_stats()

if stats['daily']['budget_remaining'] > 5000:
    result = gen.generate_weekly_summary(articles)
else:
    print("Budget low, skip expensive generation")
```

## Prompts (Romanian)

All prompts are in `/sessions/friendly-affectionate-meitner/kronpapir/ai_agent/prompts.py`:

- `WEEKLY_SUMMARY_PROMPT` - Editorial analysis
- `LOCAL_GUIDE_PROMPT` - Evergreen guides
- `OPINION_PIECE_PROMPT` - Opinion/analysis
- `DAILY_EDITORIAL_PROMPT` - Homepage intro

## Features

- ✓ Original content (not paraphrased)
- ✓ Token tracking & budget management
- ✓ Rate limiting (60 req/min)
- ✓ Comprehensive logging
- ✓ Romanian with proper diacritics
- ✓ SEO optimization
- ✓ AdSense approval ready
- ✓ Content type flagging
- ✓ Error handling

## Token Costs (Sonnet 4.5)

- Input: $3 per 1M tokens
- Output: $15 per 1M tokens

Estimates:
- Weekly Summary: ~$0.020
- Local Guide: ~$0.020
- Opinion: ~$0.018
- Daily Editorial: ~$0.014

## Logging

Activity logged to `logs/content_generator.log`:

```
2025-02-09 15:30:00 - kronpapir.content_generator - INFO - ContentGenerator initialized
2025-02-09 15:35:00 - kronpapir.content_generator - INFO - Weekly summary generated. Tokens: 1456, Cost: $0.0219
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| API Key error | `export ANTHROPIC_API_KEY='sk-...'` |
| Budget exceeded | Reduce generation frequency or increase budget |
| Bad diacritics | Ensure UTF-8 encoding in database |
| Slow responses | Check rate limiting, reduce batch size |

## Examples

Run example file:
```bash
python3 example_content_generator.py
```

View detailed docs:
```bash
cat CONTENT_GENERATOR.md
```

## Integration

```python
# With existing processor
from ai_agent.processor import ArticleProcessor
from ai_agent.content_generator import ContentGenerator

processor = ArticleProcessor(rewriter)
processor.process_articles()  # Regular news

# Then generate long-form
gen = ContentGenerator(api_key)
gen.generate_daily_editorial(articles)
```

## Content Type Flag

All output includes `content_type` to distinguish from regular news:

```json
{
  "content_type": "weekly_summary",  // Flag for database
  "status": "success",
  ...
}
```

Save to database with this flag for filtering.

---

**For complete docs:** See `CONTENT_GENERATOR.md`
**For examples:** See `example_content_generator.py`
**For implementation:** See `ai_agent/content_generator.py`
