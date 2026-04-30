# Kronpapir.ro AI Article Rewriter - Setup Guide

## Quick Start

### 1. Install Dependencies

```bash
pip install anthropic
```

### 2. Configure API Key

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
CLAUDE_MODEL=claude-sonnet-4-5-20250929
MAX_TOKENS_PER_ARTICLE=1500
DAILY_TOKEN_BUDGET=500000
```

### 3. Test Installation

Run the example script:

```bash
python example_usage.py
```

## Project Structure

```
kronpapir/
├── ai_agent/                    # Main package
│   ├── __init__.py             # Package init
│   ├── prompts.py              # All prompts in Romanian (125 lines)
│   ├── rewriter.py             # Main rewriter class (530 lines)
│   └── processor.py            # Processing pipeline (412 lines)
│
├── data/                        # Data directories
│   ├── articles/               # Input raw articles (JSON)
│   └── processed/              # Output processed articles
│
├── logs/                        # Application logs
│
├── example_usage.py            # Complete usage examples
├── .env.example                # Environment template
├── README.md                   # Full documentation
└── SETUP.md                    # This file
```

## Core Components

### 1. ArticleRewriter (`ai_agent/rewriter.py`)
Main class for all AI operations.

**Key Methods:**
- `rewrite_article(article)` - Rewrite with fact preservation
- `generate_headline(article)` - Create 3 headline alternatives
- `categorize(article)` - Auto-categorize into 10 categories
- `summarize_national(articles)` - Generate daily summary
- `moderate_content(article)` - Check for policy violations
- `refine_article(text)` - Analyze quality and suggest improvements
- `get_usage_stats()` - Track tokens and costs

**Features:**
- Automatic rate limiting (60 req/min)
- Token usage tracking with cost estimation
- Daily budget enforcement
- Comprehensive error handling
- Structured logging

### 2. ArticleProcessor (`ai_agent/processor.py`)
Batch processing pipeline.

**Key Methods:**
- `process_articles()` - Process all articles in batch
- `get_stats()` - Get processing statistics

**Features:**
- Automatic deduplication
- Batch processing (configurable size)
- Daily summary generation
- Content moderation support
- Quality refinement checks
- Processing statistics

### 3. Prompts (`ai_agent/prompts.py`)
All prompts in professional Romanian.

**Included Prompts:**
- REWRITE_ARTICLE_PROMPT - Article rewriting
- SUMMARIZE_NATIONAL_PROMPT - Daily summary
- HEADLINE_PROMPT - Headline generation
- CATEGORIZE_PROMPT - Auto-categorization
- CONTENT_MODERATION_PROMPT - Content checking
- REFINE_ARTICLE_PROMPT - Quality analysis

## Usage Examples

### Single Article Rewrite

```python
from ai_agent.rewriter import ArticleRewriter

rewriter = ArticleRewriter(api_key="your-key")

article = {
    "title": "Titlu articol",
    "text": "Conținut articol...",
    "source": "Sursa"
}

result = rewriter.rewrite_article(article)
print(result["rewritten_text"])
print(f"Cost: ${result['cost']:.4f}")
```

### Generate Headlines

```python
result = rewriter.generate_headline(article)
for headline in result.get("headlines", []):
    print(headline)
```

### Auto-Categorize

```python
result = rewriter.categorize(article)
print(f"Category: {result['categoria']}")
print(f"Confidence: {result['certitudine']}")
```

### Daily Summary

```python
articles = [article1, article2, article3]
result = rewriter.summarize_national(articles)
print(result["summary"])
```

### Batch Processing

```python
from ai_agent.processor import ArticleProcessor

processor = ArticleProcessor(rewriter)
stats = processor.process_articles(
    batch_size=5,
    generate_summary=True,
    moderate_content=True
)

print(f"Processed: {stats.processed_articles}")
print(f"Cost: ${stats.total_cost:.2f}")
```

### Command Line

```bash
# Process all articles
python -m ai_agent.processor

# With options
python -m ai_agent.processor --batch-size 10 --refine --no-moderation

# Custom directories
python -m ai_agent.processor --articles-dir /path/to/articles --processed-dir /path/to/output
```

## Input/Output Format

### Input (data/articles/)

JSON files with structure:

```json
{
  "title": "Titlu articol",
  "text": "Conținut complet al articolului în limba română",
  "source": "Denumirea sursei",
  "url": "https://example.com/article",
  "published_at": "2024-01-15T10:30:00"
}
```

### Output (data/processed/)

Comprehensive JSON with all results:

```json
{
  "original": { ... },
  "rewritten": {
    "status": "success",
    "original_text": "...",
    "rewritten_text": "...",
    "tokens_used": 450,
    "cost": 0.0042
  },
  "headlines": {
    "status": "success",
    "headlines": ["Titlu 1", "Titlu 2", "Titlu 3"]
  },
  "category": {
    "status": "success",
    "categoria": "Economie",
    "certitudine": 0.95,
    "explicație": "..."
  },
  "moderation": { ... },
  "quality_review": { ... },
  "processed_at": "2024-01-15T10:35:22.123456"
}
```

## Categories

Articles are categorized into:

1. **Politică** - Political news and government
2. **Economie** - Economics and business
3. **Sport** - Sports and athletics
4. **Cultură** - Culture, arts, entertainment
5. **Social** - Social issues and community
6. **Educație** - Education and learning
7. **Sănătate** - Health and medicine
8. **Meteo** - Weather and climate
9. **Evenimente** - Events and announcements
10. **Accidente** - Accidents and incidents

## Cost Tracking

Token usage is tracked automatically:

```python
stats = rewriter.get_usage_stats()

# Cost per model (Claude Sonnet 4.5):
# Input: $3 per 1M tokens
# Output: $15 per 1M tokens

print(f"Session cost: {stats['session']['estimated_cost']}")
print(f"Daily budget remaining: {stats['daily']['budget_remaining_percent']:.1f}%")
```

## Logging

Logs are saved to `logs/` directory:

- **rewriter.log** - Rewriter operations, errors, API calls
- **processor.log** - Processing pipeline events

Logs include:
- Timestamp, log level, message
- Token usage per operation
- Error details and stack traces
- Rate limiting information

Monitor logs in real-time:

```bash
tail -f logs/rewriter.log
tail -f logs/processor.log
```

## Configuration Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key (required) | - |
| `CLAUDE_MODEL` | Model to use | `claude-sonnet-4-5-20250929` |
| `MAX_TOKENS_PER_ARTICLE` | Max tokens per article | `1500` |
| `DAILY_TOKEN_BUDGET` | Daily token budget | `500000` |
| `BATCH_SIZE` | Articles per batch | `5` |
| `LOG_LEVEL` | Logging level | `INFO` |

### ArticleRewriter Parameters

```python
ArticleRewriter(
    api_key: str,                        # Anthropic API key
    model: str = "claude-sonnet-4-5-20250929",
    max_tokens_per_article: int = 1500,
    daily_token_budget: int = 500_000,
    rate_limit_requests_per_minute: int = 60
)
```

## Error Handling

Common errors and solutions:

### API Key Error

```
ValueError: ANTHROPIC_API_KEY not set
```

**Solution:** Set API key in `.env` or pass to `ArticleRewriter()`

### Budget Exceeded

```
Daily token budget exceeded
```

**Solution:** Increase `DAILY_TOKEN_BUDGET` or process fewer articles

### Rate Limit

```
Rate limit: sleeping for X seconds
```

**Solution:** Automatic - system waits and retries

### Invalid Input

```
status: "error", error: "Missing article text"
```

**Solution:** Ensure articles have `text` field

## Performance Tips

1. **Batch Size**: Use 5-10 articles per batch for optimal efficiency
2. **Token Budget**: Set realistic daily budget based on your needs
3. **Deduplication**: Let system automatically skip processed articles
4. **Moderation**: Enable for quality control, disable for speed
5. **Logging**: Monitor logs for issues but expect INFO level noise
6. **Cost Monitoring**: Check stats regularly to avoid overspending

## Troubleshooting

### Articles Not Processing

Check that JSON files are in `data/articles/` with correct structure.

### Slow Processing

- Reduce batch size
- Disable content moderation
- Disable quality refinement
- Increase `MAX_TOKENS_PER_ARTICLE` if needed

### High Costs

- Reduce `DAILY_TOKEN_BUDGET` check frequency
- Process fewer articles per session
- Disable quality refinement
- Use smaller batch sizes

### JSON Parse Errors

Some responses may not be valid JSON. Check logs - the system includes raw responses in output.

## Next Steps

1. Review `example_usage.py` for complete usage patterns
2. Start with a small batch (2-3 articles) to test
3. Monitor `logs/rewriter.log` for any issues
4. Adjust batch size and token limits based on your needs
5. Integrate into your workflow

## Support

For questions or issues, check:
- `logs/` directory for error details
- `README.md` for comprehensive documentation
- `example_usage.py` for usage patterns
- Comments in source code for implementation details
