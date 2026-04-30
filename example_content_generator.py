#!/usr/bin/env python3
"""
Example usage of the ContentGenerator module.
Demonstrates how to generate long-form editorial content for KronPapir.ro.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# Add project to path if running from different directory
import sys
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ai_agent.content_generator import ContentGenerator


def example_weekly_summary():
    """Example: Generate a weekly summary article."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Weekly Summary Generation")
    print("="*60)

    # Initialize generator
    generator = ContentGenerator(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        processed_dir="data/processed",
    )

    # Example articles (in real use, these would come from scrapers)
    sample_articles = [
        {
            "title": "Pregătiri pentru Sărbătorile de Paște la Brașov",
            "source": "Brașov.live",
            "date": "2025-02-10",
            "text": "Piața Sfatului din Brașov se pregătește pentru decorații tradiționale de Paște. "
                   "Autorități locale au anunțat programul evenimentelor culturale.",
        },
        {
            "title": "Transport Public: Noi rute în zona de nord a Brașovului",
            "source": "Brașov Transport",
            "date": "2025-02-11",
            "text": "Compania de transport public anunță deschiderea a trei noi rute "
                   "în zona Bartolomeu pentru a îmbunătăți conectivitatea.",
        },
        {
            "title": "Turismul de iarnă: Sezonul final la Poiana Brașov",
            "source": "Turism Covasna",
            "date": "2025-02-12",
            "text": "Stația de schi Poiana Brașov înregistrează o creștere de 15% a vizitatorilor "
                   "în comparație cu sezonul trecut.",
        },
    ]

    # Generate weekly summary
    week_start = datetime.now() - timedelta(days=datetime.now().weekday())
    result = generator.generate_weekly_summary(
        articles_list=sample_articles,
        week_start=week_start,
    )

    if result["status"] == "success":
        print(f"\n✓ Generated: {result['title']}")
        print(f"  Articles used: {result['article_count']}")
        print(f"  Tokens used: {result['tokens_used']}")
        print(f"  Cost: ${result['cost']:.4f}")
        print(f"\n--- Content Preview (first 300 chars) ---")
        print(result['content'][:300] + "...")
    else:
        print(f"\n✗ Error: {result.get('error')}")


def example_local_guide():
    """Example: Generate a local guide article."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Local Guide Generation")
    print("="*60)

    generator = ContentGenerator(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        processed_dir="data/processed",
    )

    topics = [
        "Top 10 restaurante și cafenele în Brașov",
        "Ghid complet: Trasee montane din Brașov și Covasna",
        "Ce să vizitezi în Brașov iarna - atracții și activități",
    ]

    # Generate guide for first topic
    topic = topics[0]
    print(f"\nTopic: {topic}")

    result = generator.generate_local_guide(topic=topic)

    if result["status"] == "success":
        print(f"✓ Generated guide article")
        print(f"  Topic: {result['topic']}")
        print(f"  Tokens used: {result['tokens_used']}")
        print(f"  Cost: ${result['cost']:.4f}")
        print(f"\n--- Content Preview (first 300 chars) ---")
        print(result['content'][:300] + "...")
    else:
        print(f"✗ Error: {result.get('error')}")


def example_opinion_piece():
    """Example: Generate an opinion/analysis piece."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Opinion Piece Generation")
    print("="*60)

    generator = ContentGenerator(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        processed_dir="data/processed",
    )

    topic = "Impactul creșterii prețurilor chiriilor asupra tinerilor din Brașov"

    # Context articles (would come from recent news)
    context_articles = [
        {
            "title": "Chiriile în Brașov: creștere de 20% în ultimul an",
            "text": "Piața imobiliară rezidențială din Brașov continuă să înregistreze "
                   "creșteri semnificative ale chiriilor, în special în zona centrală.",
        },
        {
            "title": "Tinerii pleacă din Brașov în căutarea unor orașe mai accesibile",
            "text": "Emigrația internă din Brașov se accelerează pe fondul creșterii costului "
                   "de viață și a lipsei oportunităților de angajare.",
        },
    ]

    print(f"\nTopic: {topic}")

    result = generator.generate_opinion_piece(
        topic=topic,
        articles_context=context_articles,
    )

    if result["status"] == "success":
        print(f"✓ Generated opinion piece")
        print(f"  Topic: {result['topic']}")
        print(f"  Context articles: {result['context_articles']}")
        print(f"  Tokens used: {result['tokens_used']}")
        print(f"  Cost: ${result['cost']:.4f}")
        print(f"\n--- Content Preview (first 300 chars) ---")
        print(result['content'][:300] + "...")
    else:
        print(f"✗ Error: {result.get('error')}")


def example_daily_editorial():
    """Example: Generate a daily editorial."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Daily Editorial Generation")
    print("="*60)

    generator = ContentGenerator(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        processed_dir="data/processed",
    )

    # Top articles of the day
    top_articles = [
        {
            "title": "Zona Piața Sfatului: lucrări de reabilitare în plin pregătire",
            "source": "Primăria Brașov",
            "text": "Autoritățile anunță reabilitarea spațiilor verzi din Piața Sfatului "
                   "pentru a îmbunătăți aspectul istoric al zonei.",
        },
        {
            "title": "Turism: Recorduri de ocupare în februarie la hotelurile din Brașov",
            "source": "Brașov Turism",
            "text": "Hotelurile din Brașov au înregistrat o ocupare de 85% în primele două "
                   "săptămâni ale acestei luni.",
        },
        {
            "title": "Transport Public: Actualizarea horарelor în perioada reparațiilor",
            "source": "Compania Transport",
            "text": "Din cauza lucrărilor de întreținere, unele rute vor funcționa cu "
                   "alterări de program în următoarele zile.",
        },
    ]

    result = generator.generate_daily_editorial(top_articles=top_articles)

    if result["status"] == "success":
        print(f"✓ Generated daily editorial")
        print(f"  Articles used: {result['article_count']}")
        print(f"  Date: {result['date']}")
        print(f"  Tokens used: {result['tokens_used']}")
        print(f"  Cost: ${result['cost']:.4f}")
        print(f"\n--- Content Preview (first 300 chars) ---")
        print(result['content'][:300] + "...")
    else:
        print(f"✗ Error: {result.get('error')}")


def example_content_calendar():
    """Example: Display the content scheduling calendar."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Content Calendar Scheduling")
    print("="*60)

    generator = ContentGenerator(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        processed_dir="data/processed",
    )

    calendar = generator.schedule_content_calendar()

    print("\nWeekly content plan:")
    print("-" * 60)

    for day_num in range(7):
        entry = calendar[day_num]
        print(f"\n{entry.day_name.capitalize()}:")
        print(f"  Type: {entry.content_type}")
        if entry.topic:
            print(f"  Topic: {entry.topic}")

    # Show today's plan
    print("\n" + "-" * 60)
    today_plan = generator.get_today_content_plan()
    if today_plan:
        print(f"\nToday's content plan:")
        print(f"  Type: {today_plan.content_type}")
        if today_plan.topic:
            print(f"  Topic: {today_plan.topic}")


def example_usage_stats():
    """Example: Display token usage statistics."""
    print("\n" + "="*60)
    print("EXAMPLE 6: Token Usage and Cost Tracking")
    print("="*60)

    generator = ContentGenerator(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        processed_dir="data/processed",
    )

    stats = generator.get_usage_stats()

    print("\nSession Statistics:")
    print(f"  Total tokens: {stats['session']['total_tokens']}")
    print(f"  Input tokens: {stats['session']['input_tokens']}")
    print(f"  Output tokens: {stats['session']['output_tokens']}")
    print(f"  Estimated cost: {stats['session']['estimated_cost']}")

    print("\nDaily Statistics:")
    print(f"  Total tokens used: {stats['daily']['total_tokens']}")
    print(f"  Budget remaining: {stats['daily']['budget_remaining']} tokens")
    print(f"  Budget remaining: {stats['daily']['budget_remaining_percent']:.1f}%")


def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("ContentGenerator Usage Examples")
    print("="*60)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\n⚠ Warning: ANTHROPIC_API_KEY not set in environment")
        print("  Please set it before running actual generation:")
        print("  export ANTHROPIC_API_KEY='sk-...'")
        return

    try:
        # Note: These examples assume the API is available
        # You can comment out examples that require API calls

        # example_weekly_summary()
        # example_local_guide()
        # example_opinion_piece()
        # example_daily_editorial()
        example_content_calendar()
        example_usage_stats()

        print("\n" + "="*60)
        print("Examples completed successfully!")
        print("="*60)

    except Exception as e:
        print(f"\n✗ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
