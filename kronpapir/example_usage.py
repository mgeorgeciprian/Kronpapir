"""
Example usage of the Kronpapir AI Article Rewriter Agent.
Demonstrates all main features and capabilities.
"""

import os
import json
from pathlib import Path
from ai_agent.rewriter import ArticleRewriter
from ai_agent.processor import ArticleProcessor

# Sample articles for demonstration
SAMPLE_ARTICLES = [
    {
        "title": "Noi investiții în domeniul energiei regenerabile",
        "text": """
        Guvernul României a anunțat azi un nou program de investiții în energia regenerabilă,
        cu o valoare de 500 de milioane de euro. Programul va fi implementat în următorii 5 ani
        și va include construcția de noi ferme de panouri solare și turbine eoliene în diferite
        regiuni ale țării. Oficialii guvernului au declarat că aceasta este o prioritate pentru
        tranziția energetică a României și reducerea emisiilor de carbon.
        """,
        "source": "Agenția de Știri România",
        "url": "https://example.com/energy-investment",
    },
    {
        "title": "Campionatul de Fotbal: Rezultatele weekendului",
        "text": """
        În weekend-ul trecut, Liga I a marcat cu pasul victoriile importante pentru echipele din
        elite. Dinamo a învins Steaua cu scorul de 2-1 într-un meci foarte disputat. CFR Cluj
        a continuat seria pozitivă cu o victorie 3-0 în deplasare. FCSB a remizat 1-1 cu Universitatea
        Craiova într-o întâlnire cu o mulțime de emoții. Clasamentul se apropie de punctul de cotitură
        sezonului cu doar 5 runde rămase din play-off.
        """,
        "source": "Sports Daily",
        "url": "https://example.com/football-results",
    },
    {
        "title": "Economia românească crește mai repede decât estimările",
        "text": """
        Banca Mondială a revizuit în sus prognozele de creștere economică pentru România în 2024.
        Noile estimări arată o creștere PIB-ului de 2.8%, în comparație cu 2.5% prognozate anterior.
        Creșterea este susținută de investițiile private, consumul populației și exporturile.
        Analiștii spun că inflația continuă să scadă, ajungând la 4.2% anul acesta. Aceasta oferă
        perspective bune pentru politica monetară a Băncii Naționale.
        """,
        "source": "Economistul",
        "url": "https://example.com/economy-growth",
    },
]


def example_1_single_article_rewrite():
    """Example 1: Rewrite a single article."""
    print("\n" + "=" * 70)
    print("EXAMPLE 1: Rewrite a Single Article")
    print("=" * 70)

    # Initialize rewriter
    rewriter = ArticleRewriter(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        model="claude-sonnet-4-5-20250929",
        max_tokens_per_article=1500,
        daily_token_budget=500_000,
    )

    article = SAMPLE_ARTICLES[0]
    print(f"\nOriginal Article:")
    print(f"Title: {article['title']}")
    print(f"Text: {article['text'][:200]}...")

    result = rewriter.rewrite_article(article)

    if result["status"] == "success":
        print(f"\nRewritten Article:")
        print(result["rewritten_text"])
        print(f"\nTokens used: {result['tokens_used']}")
        print(f"Cost: ${result['cost']:.4f}")
    else:
        print(f"Error: {result.get('error')}")


def example_2_generate_headlines():
    """Example 2: Generate multiple headlines for an article."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Generate Headlines")
    print("=" * 70)

    rewriter = ArticleRewriter(api_key=os.getenv("ANTHROPIC_API_KEY"))

    article = SAMPLE_ARTICLES[1]
    print(f"\nOriginal title: {article['title']}")

    result = rewriter.generate_headline(article)

    if result["status"] == "success":
        print("\nGenerated headlines:")
        for i, headline in enumerate(result.get("headlines", []), 1):
            print(f"{i}. {headline}")
        print(f"\nTokens used: {result['tokens_used']}")
    else:
        print(f"Raw response: {result.get('headlines_raw')}")


def example_3_categorize_articles():
    """Example 3: Auto-categorize articles."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Auto-Categorize Articles")
    print("=" * 70)

    rewriter = ArticleRewriter(api_key=os.getenv("ANTHROPIC_API_KEY"))

    for article in SAMPLE_ARTICLES:
        print(f"\nArticle: {article['title']}")

        result = rewriter.categorize(article)

        if result["status"] == "success" and "categoria" in result:
            print(f"Category: {result['categoria']}")
            print(f"Confidence: {result.get('certitudine', 'N/A')}")
        else:
            print(f"Category info: {result.get('raw_response', 'Unable to parse')}")


def example_4_daily_summary():
    """Example 4: Generate daily national summary."""
    print("\n" + "=" * 70)
    print("EXAMPLE 4: Generate Daily National Summary")
    print("=" * 70)

    rewriter = ArticleRewriter(api_key=os.getenv("ANTHROPIC_API_KEY"))

    print(f"\nGenerating summary for {len(SAMPLE_ARTICLES)} articles...")

    result = rewriter.summarize_national(SAMPLE_ARTICLES)

    if result["status"] == "success":
        print("\nDaily Summary:")
        print(result["summary"])
        print(f"\nTokens used: {result['tokens_used']}")
        print(f"Cost: ${result['cost']:.4f}")
    else:
        print(f"Error: {result.get('error')}")


def example_5_content_moderation():
    """Example 5: Moderate article content."""
    print("\n" + "=" * 70)
    print("EXAMPLE 5: Content Moderation")
    print("=" * 70)

    rewriter = ArticleRewriter(api_key=os.getenv("ANTHROPIC_API_KEY"))

    article = SAMPLE_ARTICLES[0]
    print(f"\nModeration check for: {article['title']}")

    result = rewriter.moderate_content(article)

    if result["status"] == "success":
        print(f"Moderation status: OK" if result.get("ok") else "Moderation status: Issues found")
        print(f"Risk level: {result.get('risc', 'unknown')}")
        if result.get("motivare"):
            print(f"Reason: {result['motivare']}")
    else:
        print(f"Raw response: {result.get('raw_response')}")


def example_6_usage_statistics():
    """Example 6: Track token usage and costs."""
    print("\n" + "=" * 70)
    print("EXAMPLE 6: Token Usage and Cost Tracking")
    print("=" * 70)

    rewriter = ArticleRewriter(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        daily_token_budget=500_000,
    )

    # Do some operations
    rewriter.rewrite_article(SAMPLE_ARTICLES[0])
    rewriter.generate_headline(SAMPLE_ARTICLES[1])
    rewriter.categorize(SAMPLE_ARTICLES[2])

    stats = rewriter.get_usage_stats()

    print("\nSession Statistics:")
    print(f"  Input tokens: {stats['session']['input_tokens']}")
    print(f"  Output tokens: {stats['session']['output_tokens']}")
    print(f"  Total tokens: {stats['session']['total_tokens']}")
    print(f"  Estimated cost: {stats['session']['estimated_cost']}")

    print("\nDaily Statistics:")
    print(f"  Total tokens: {stats['daily']['total_tokens']}")
    print(f"  Estimated cost: {stats['daily']['estimated_cost']}")
    print(f"  Budget remaining: {stats['daily']['budget_remaining']} tokens")
    print(
        f"  Budget usage: {100 - stats['daily']['budget_remaining_percent']:.1f}%"
    )


def example_7_batch_processing():
    """Example 7: Batch process articles using ArticleProcessor."""
    print("\n" + "=" * 70)
    print("EXAMPLE 7: Batch Processing with ArticleProcessor")
    print("=" * 70)

    # Create sample articles directory
    articles_dir = Path("data/articles")
    articles_dir.mkdir(parents=True, exist_ok=True)

    # Save sample articles
    for i, article in enumerate(SAMPLE_ARTICLES):
        filename = articles_dir / f"article_{i}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)
        print(f"Created: {filename}")

    # Initialize processor
    rewriter = ArticleRewriter(api_key=os.getenv("ANTHROPIC_API_KEY"))
    processor = ArticleProcessor(
        rewriter=rewriter,
        articles_dir=str(articles_dir),
        processed_dir="data/processed",
    )

    # Process articles
    print("\nProcessing articles...")
    stats = processor.process_articles(
        batch_size=2,
        generate_summary=True,
        moderate_content=False,
        refine_output=False,
    )

    print("\nProcessing Results:")
    print(f"  Total articles: {stats.total_articles}")
    print(f"  Processed: {stats.processed_articles}")
    print(f"  Skipped: {stats.skipped_articles}")
    print(f"  Failed: {stats.failed_articles}")
    print(f"  Duration: {stats.duration_seconds:.2f}s")
    print(f"  Total tokens: {stats.total_tokens_used}")
    print(f"  Total cost: ${stats.total_cost:.4f}")


def main():
    """Run all examples."""
    print("\n" + "=" * 70)
    print("KRONPAPIR.RO - CLAUDE AI ARTICLE REWRITER - EXAMPLES")
    print("=" * 70)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment")
        return

    try:
        # Run examples
        example_1_single_article_rewrite()
        example_2_generate_headlines()
        example_3_categorize_articles()
        example_4_daily_summary()
        example_5_content_moderation()
        example_6_usage_statistics()
        example_7_batch_processing()

        print("\n" + "=" * 70)
        print("All examples completed successfully!")
        print("=" * 70)

    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
