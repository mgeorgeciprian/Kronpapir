# ContentGenerator Module Documentation

## Overview

The `ContentGenerator` module generates original, long-form editorial content for KronPapir.ro. It uses the Anthropic Claude API to create:

- **Weekly Summaries**: Comprehensive editorial analysis of the week's local news
- **Local Guides**: Evergreen SEO-friendly articles about Brașov attractions and information
- **Opinion Pieces**: Analytical commentary on local topics
- **Daily Editorials**: Homepage intro content for the day's top stories

All content is:
- Original (not copied/paraphrased from source articles)
- Written in professional Romanian with proper diacritics
- Optimized for SEO and AdSense approval
- Tracking token usage and costs

## Installation

```bash
# The module requires the Anthropic SDK
pip install anthropic
```

## Quick Start

```python
from ai_agent.content_generator import ContentGenerator

# Initialize
generator = ContentGenerator(
    api_key="sk-...",  # or set ANTHROPIC_API_KEY env variable
    processed_dir="data/processed",
)

# Generate a weekly summary
articles = [
    {
        "title": "Local News Title",
        "source": "Source Name",
        "text": "Article content...",
    },
    # ... more articles
]

result = generator.generate_weekly_summary(articles)
print(result['content'])
```

## Module Components

### ContentCalendarEntry (Dataclass)

Represents a scheduled content generation task.

**Attributes:**
- `day_of_week` (int): 0=Monday, 6=Sunday
- `day_name` (str): Day name in Romanian
- `content_type` (str): Type of content ("weekly_summary", "guide", "opinion", "daily_editorial")
- `topic` (Optional[str]): Topic for guides and opinions

### ContentGenerator (Main Class)

#### Initialization

```python
ContentGenerator(
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-5-20250929",
    max_tokens_per_article: int = 2000,
    daily_token_budget: int = 500_000,
    rate_limit_requests_per_minute: int = 60,
    processed_dir: str = "data/processed",
)
```

**Parameters:**
- `api_key`: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
- `model`: Claude model to use
- `max_tokens_per_article`: Maximum tokens per generation
- `daily_token_budget`: Daily token budget limit
- `rate_limit_requests_per_minute`: API rate limit
- `processed_dir`: Directory to save generated content

#### Methods

##### 1. generate_weekly_summary()

Generates an 800-1200 word weekly summary article.

```python
result = generator.generate_weekly_summary(
    articles_list: List[Dict[str, Any]],
    week_start: Optional[datetime] = None,
)
```

**Parameters:**
- `articles_list`: List of article dicts with 'title', 'source', 'text', 'date'
- `week_start`: Start date of week (defaults to Monday of current week)

**Returns:**
```python
{
    "status": "success",
    "title": "Săptămâna în Brașov: 10 - 16 februarie",
    "content": "Full article text...",
    "article_count": 5,
    "week_start": "2025-02-10T00:00:00",
    "week_end": "2025-02-16T00:00:00",
    "tokens_used": 1234,
    "cost": 0.0185,
    "timestamp": "2025-02-09T15:30:00",
    "content_type": "weekly_summary"
}
```

**Format:** "Săptămâna în Brașov: [data-start] - [data-end]"

**Content Structure:**
- Intro: Context and tone of the week
- Topic sections: Grouped by category (Politics, Economy, Culture, etc.)
- Analysis: Not just headlines, but editorial analysis
- Conclusion: Reflection and outlook

---

##### 2. generate_local_guide()

Generates a 600-1000 word evergreen local guide article.

```python
result = generator.generate_local_guide(topic: str)
```

**Parameters:**
- `topic`: Guide topic (examples below)

**Example Topics:**
- "Top 10 restaurante și cafenele în Brașov"
- "Ghid complet: Trasee montane din Brașov și Covasna"
- "Ce să vizitezi în Brașov iarna - atracții și activități"
- "Ghid pentru turiști: Ce e de Vezi și De Făcut în Brașov"
- "Piața Sfatului și Centrul Istoric: Istorii și Atracții"

**Returns:**
```python
{
    "status": "success",
    "topic": "Top 10 restaurante și cafenele în Brașov",
    "content": "Full guide article...",
    "tokens_used": 1567,
    "cost": 0.0234,
    "timestamp": "2025-02-09T15:35:00",
    "content_type": "guide"
}
```

**Content Features:**
- SEO-optimized for local search
- References to real Brașov locations (Piața Sfatului, Centrul Istoric, Dealul Tâmpa)
- Practical information (hours, tariffs, contact)
- Multiple sections with sub-headings
- Natural keyword integration

---

##### 3. generate_opinion_piece()

Generates a 600-900 word opinion/analysis piece on a local topic.

```python
result = generator.generate_opinion_piece(
    topic: str,
    articles_context: List[Dict[str, Any]],
)
```

**Parameters:**
- `topic`: Opinion topic
- `articles_context`: Recent articles providing context

**Example Topics:**
- "De ce cresc prețurile chiriilor în centrul Brașovului"
- "Impactul turismului asupra infrastructurii locale"
- "Cum ar putea fi îmbunătățit transportul public în Brașov"
- "Conservarea patrimoniului istoric: O responsabilitate comună"

**Returns:**
```python
{
    "status": "success",
    "topic": "De ce cresc prețurile chiriilor în centrul Brașovului",
    "content": "Full opinion article...",
    "context_articles": 3,
    "tokens_used": 1445,
    "cost": 0.0216,
    "timestamp": "2025-02-09T15:40:00",
    "content_type": "opinion"
}
```

**Content Structure:**
- Personal introduction: Problem and relevance
- Main arguments: 2-3 arguments with details and examples
- Local context: How Brașov/Covasna is affected
- Conclusion: Summary and call to action
- Tone: Analytical, inviting discussion, not aggressive

---

##### 4. generate_daily_editorial()

Generates a 400-600 word daily editorial for the homepage.

```python
result = generator.generate_daily_editorial(
    top_articles: List[Dict[str, Any]],
)
```

**Parameters:**
- `top_articles`: Top 3-5 articles of the day

**Returns:**
```python
{
    "status": "success",
    "content": "Full editorial text...",
    "article_count": 4,
    "date": "2025-02-09",
    "tokens_used": 987,
    "cost": 0.0148,
    "timestamp": "2025-02-09T15:45:00",
    "content_type": "daily_editorial"
}
```

**Content Features:**
- Conversational but professional tone
- Greeting to readers
- "Line of the day" - main theme
- 3-4 top articles summarized (1-2 sentences each)
- Quick reflection and invitation to read more
- Suitable for homepage placement

---

##### 5. schedule_content_calendar()

Returns a content plan for the week.

```python
calendar = generator.schedule_content_calendar()
```

**Returns:**
```python
{
    0: ContentCalendarEntry(  # Monday
        day_of_week=0,
        day_name="Luni",
        content_type="weekly_summary",
        topic=None,
    ),
    1: ContentCalendarEntry(  # Tuesday
        day_of_week=1,
        day_name="Marți",
        content_type="daily_editorial",
        topic=None,
    ),
    # ... etc
}
```

**Schedule:**
- **Monday**: Weekly Summary
- **Tuesday**: Daily Editorial
- **Wednesday**: Local Guide
- **Thursday**: Daily Editorial
- **Friday**: Opinion Piece
- **Saturday**: Local Guide
- **Sunday**: Daily Editorial

---

##### 6. get_today_content_plan()

Get the content plan for today.

```python
plan = generator.get_today_content_plan()
if plan:
    print(f"Today: {plan.content_type}")
    if plan.topic:
        print(f"Topic: {plan.topic}")
```

---

##### 7. get_usage_stats()

Get token usage and cost statistics.

```python
stats = generator.get_usage_stats()
print(stats)
```

**Returns:**
```python
{
    "session": {
        "input_tokens": 12345,
        "output_tokens": 5678,
        "total_tokens": 18023,
        "estimated_cost": "$0.2704",
    },
    "daily": {
        "input_tokens": 50000,
        "output_tokens": 20000,
        "total_tokens": 70000,
        "estimated_cost": "$1.0500",
        "budget_remaining": 430000,
        "budget_remaining_percent": 86.0,
    },
}
```

## Prompts Used

All prompts are in **Romanian with professional journalistic tone**.

### WEEKLY_SUMMARY_PROMPT
- Instructs Claude to write editorial analysis (not list of headlines)
- Emphasizes Brașov local references
- Requires intro, sections by topic, conclusion
- 800-1200 words

### LOCAL_GUIDE_PROMPT
- Evergreen content guidelines
- Specific Brașov/Covasna location references
- SEO optimization
- Practical information integration
- 600-1000 words

### OPINION_PIECE_PROMPT
- Analytical tone
- Multiple arguments with examples
- Local context requirement
- Fact-based, no pure speculation
- 600-900 words

### DAILY_EDITORIAL_PROMPT
- Conversational professional tone
- Homepage-suitable format
- "Line of the day" concept
- Natural keyword integration
- 400-600 words

## Output Format

All generated content is saved to `data/processed/` as JSON files with:

```json
{
    "status": "success",
    "content": "The full article text...",
    "content_type": "weekly_summary|guide|opinion|daily_editorial",
    "title": "Article title (if applicable)",
    "tokens_used": 1234,
    "cost": 0.0185,
    "timestamp": "2025-02-09T15:30:00",
    ... (additional metadata)
}
```

## Integration with Article Pipeline

The ContentGenerator can be integrated with the existing ArticleProcessor:

```python
from ai_agent.rewriter import ArticleRewriter
from ai_agent.processor import ArticleProcessor
from ai_agent.content_generator import ContentGenerator

# Initialize both
rewriter = ArticleRewriter(api_key="sk-...")
processor = ArticleProcessor(rewriter=rewriter)

# Process regular articles
stats = processor.process_articles()

# Then generate long-form content
generator = ContentGenerator(api_key="sk-...")

# Generate daily editorial from processed articles
articles = load_articles_from_processed_dir()
daily_result = generator.generate_daily_editorial(articles[:5])

# Or weekly summary on Mondays
import datetime
if datetime.datetime.now().weekday() == 0:  # Monday
    weekly_result = generator.generate_weekly_summary(articles)
```

## Token Cost Management

**Pricing (Claude Sonnet 4.5):**
- Input: $3 per 1M tokens
- Output: $15 per 1M tokens

**Token Usage Examples:**
- Weekly Summary: ~1,200-1,500 tokens (cost: ~$0.020)
- Local Guide: ~1,200-1,500 tokens (cost: ~$0.020)
- Opinion Piece: ~1,200-1,400 tokens (cost: ~$0.018)
- Daily Editorial: ~800-1,000 tokens (cost: ~$0.014)

**Daily Budget Management:**
- Default budget: 500,000 tokens/day
- Generator checks budget before each call
- Tracks session and daily usage separately
- Returns `budget_exceeded` status if limit reached

## Error Handling

```python
result = generator.generate_weekly_summary(articles)

if result['status'] == 'success':
    print(result['content'])
elif result['status'] == 'budget_exceeded':
    print("Daily token budget exhausted")
elif result['status'] == 'error':
    print(f"Error: {result['error']}")
```

## Logging

All operations are logged to `logs/content_generator.log`:

```
2025-02-09 15:30:00 - kronpapir.content_generator - INFO - ContentGenerator initialized with model: claude-sonnet-4-5-20250929
2025-02-09 15:35:00 - kronpapir.content_generator - INFO - Weekly summary generated. Articles: 15, Tokens: 1456, Cost: $0.0219
```

## Best Practices

### 1. Provide Quality Article Context
- Use recent, well-written articles
- Include title, source, date, and full text
- Limit to 20 articles for weekly summaries (token efficiency)

### 2. Rotate Content Types
- Use the content calendar to vary content
- Ensures consistent editorial flow
- Balances SEO benefits across different content types

### 3. Monitor Token Usage
- Check stats before generating expensive content
- Plan content generation during off-peak hours
- Aggregate content generation to batch requests

### 4. Ensure Brașov Localization
- All content should reference local landmarks
- Examples: Piața Sfatului, Dealul Tâmpa, Igreja Neagră
- Include Covasna region when relevant

### 5. SEO Optimization
- Use naturally integrated keywords
- Brașov, Covasna, local topics
- Avoid keyword stuffing
- Follow journalistic standards

## Advanced Usage

### Custom Content Calendar

```python
from ai_agent.content_generator import ContentCalendarEntry

custom_calendar = {
    0: ContentCalendarEntry(
        day_of_week=0, day_name="Luni",
        content_type="weekly_summary"
    ),
    2: ContentCalendarEntry(
        day_of_week=2, day_name="Miercuri",
        content_type="guide",
        topic="Atracții naturale în Covasna"
    ),
}
```

### Batch Generation

```python
topics_for_week = [
    "Ghid iarnă în Brașov",
    "Restaurante cu specific local",
    "Trasee de drumeții pentru începători",
]

results = []
for topic in topics_for_week:
    result = generator.generate_local_guide(topic)
    if result['status'] == 'success':
        results.append(result)
```

## Troubleshooting

**Issue: "ANTHROPIC_API_KEY not set"**
- Set environment variable: `export ANTHROPIC_API_KEY='sk-...'`
- Or pass directly: `ContentGenerator(api_key="sk-...")`

**Issue: "Daily token budget exceeded"**
- Reduce generation frequency
- Check stats before generating expensive content
- Increase `daily_token_budget` parameter

**Issue: Content quality not meeting expectations**
- Provide more context articles
- Ensure input articles are well-written
- Adjust `temperature` parameter (0.5-0.8 for editorial)

**Issue: Romanian diacritics not rendering**
- Ensure UTF-8 file encoding
- Check `ensure_ascii=False` in JSON serialization

## See Also

- `ai_agent/prompts.py` - All prompt templates
- `ai_agent/rewriter.py` - Article rewriting engine
- `ai_agent/processor.py` - Main processing pipeline
- `example_content_generator.py` - Usage examples
