"""
Long-form content generator for kronpapir.ro.
Generates original editorial content for SEO and AdSense approval.
Includes weekly summaries, local guides, opinion pieces, and daily editorials.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

from .prompts import (
    SYSTEM_PERSONA,
    WEEKLY_SUMMARY_PROMPT,
    LOCAL_GUIDE_PROMPT,
    OPINION_PIECE_PROMPT,
    DAILY_EDITORIAL_PROMPT,
)
from .rewriter import TokenUsage, RateLimiter


@dataclass
class ContentCalendarEntry:
    """Represents a scheduled content generation task."""
    day_of_week: int  # 0=Monday, 6=Sunday
    day_name: str
    content_type: str  # "weekly_summary", "guide", "opinion", "daily_editorial"
    topic: Optional[str] = None  # For guides and opinions


class ContentGenerator:
    """Generator for long-form original editorial content."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens_per_article: int = 2000,
        daily_token_budget: int = 500_000,
        rate_limit_requests_per_minute: int = 60,
        processed_dir: str = "data/processed",
    ):
        """Initialize the content generator with API configuration."""
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment or parameters")

        self.model = model
        self.max_tokens_per_article = max_tokens_per_article
        self.daily_token_budget = daily_token_budget
        self.processed_dir = Path(processed_dir)

        # Ensure processed directory exists
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.rate_limiter = RateLimiter(max_requests_per_minute)

        # Token tracking
        self.session_tokens = TokenUsage()
        self.daily_tokens = TokenUsage()

        # Setup logging
        self.logger = self._setup_logging()
        self.logger.info(f"ContentGenerator initialized with model: {self.model}")

    def _setup_logging(self) -> logging.Logger:
        """Configure logging."""
        logger = logging.getLogger("kronpapir.content_generator")
        logger.setLevel(logging.INFO)

        # Create logs directory if needed
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # File handler
        fh = logging.FileHandler(log_dir / "content_generator.log")
        fh.setLevel(logging.INFO)

        # Console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

        return logger

    def _check_budget(self, estimated_tokens: int) -> bool:
        """Check if we have token budget remaining."""
        remaining = self.daily_token_budget - self.daily_tokens.total_tokens
        if estimated_tokens > remaining:
            self.logger.warning(
                f"Daily token budget exceeded. Remaining: {remaining}, "
                f"Estimated needed: {estimated_tokens}"
            )
            return False
        return True

    def _update_token_usage(self, usage: anthropic.types.Usage):
        """Update token usage tracking."""
        self.session_tokens.input_tokens += usage.input_tokens
        self.session_tokens.output_tokens += usage.output_tokens
        self.session_tokens.total_tokens += (
            usage.input_tokens + usage.output_tokens
        )

        self.daily_tokens.input_tokens += usage.input_tokens
        self.daily_tokens.output_tokens += usage.output_tokens
        self.daily_tokens.total_tokens += usage.input_tokens + usage.output_tokens

    def _call_claude(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        system: Optional[str] = None,
    ) -> tuple[str, TokenUsage]:
        """Call Claude API with rate limiting and error handling."""
        max_tokens = max_tokens or self.max_tokens_per_article

        self.rate_limiter.wait_if_needed()

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system or SYSTEM_PERSONA,
                messages=[{"role": "user", "content": prompt}],
            )

            self._update_token_usage(message.usage)

            return message.content[0].text, TokenUsage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                total_tokens=(
                    message.usage.input_tokens + message.usage.output_tokens
                ),
            )

        except anthropic.APIError as e:
            self.logger.error(f"Claude API error: {e}")
            raise

    def _save_generated_content(
        self,
        content_data: Dict[str, Any],
        content_type: str,
        filename_prefix: str = "",
    ) -> str:
        """Save generated content to processed directory."""
        try:
            # Generate filename
            if filename_prefix:
                filename = f"{filename_prefix}_{content_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            else:
                filename = f"{content_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            output_path = self.processed_dir / filename

            # Add content_type flag
            content_data["content_type"] = content_type

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(content_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Saved generated content: {filename}")
            return str(output_path)

        except Exception as e:
            self.logger.error(f"Error saving generated content: {e}")
            raise

    def generate_weekly_summary(
        self,
        articles_list: List[Dict[str, Any]],
        week_start: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Generate an 800-1200 word weekly summary article.

        Title format: "Săptămâna în Brașov: [date range]"

        Args:
            articles_list: List of article dicts from the week
            week_start: Start date of the week (defaults to Monday of current week)

        Returns:
            Dict with generated content and metadata
        """
        if not articles_list:
            self.logger.warning("No articles provided for weekly summary")
            return {
                "status": "error",
                "error": "No articles provided",
            }

        # Determine week dates
        if week_start is None:
            today = datetime.now()
            week_start = today - timedelta(days=today.weekday())

        week_end = week_start + timedelta(days=6)

        # Format articles for prompt
        articles_text = "\n\n---\n\n".join(
            [
                f"Titlu: {a.get('title', 'N/A')}\n"
                f"Sursă: {a.get('source', 'N/A')}\n"
                f"Data: {a.get('date', 'N/A')}\n"
                f"Text: {a.get('text', '')}"
                for a in articles_list[:20]  # Limit to 20 articles for token budget
            ]
        )

        # Check budget (generous for longer articles)
        max_summary_tokens = self.max_tokens_per_article * 2
        if not self._check_budget(max_summary_tokens):
            self.logger.warning("Daily token budget exceeded for weekly summary")
            return {"status": "budget_exceeded"}

        try:
            date_range = f"{week_start.strftime('%d')} - {week_end.strftime('%d %B').lower()}"

            prompt = WEEKLY_SUMMARY_PROMPT.format(articles_list=articles_text)
            generated_text, token_usage = self._call_claude(
                prompt,
                max_tokens=max_summary_tokens,
                temperature=0.85,
            )

            result = {
                "status": "success",
                "title": f"Săptămâna în Brașov: {date_range}",
                "content": generated_text,
                "article_count": len(articles_list),
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            # Save content
            self._save_generated_content(result, "weekly_summary", "brasov")

            self.logger.info(
                f"Weekly summary generated. Articles: {len(articles_list)}, "
                f"Tokens: {token_usage.total_tokens}, Cost: ${token_usage.total_cost:.4f}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error generating weekly summary: {e}")
            return {"status": "error", "error": str(e)}

    def generate_local_guide(
        self,
        topic: str,
    ) -> Dict[str, Any]:
        """
        Generate a 600-1000 word evergreen local guide article.

        Topics like: "Top evenimente în Brașov luna aceasta",
        "Ghid complet: Trasee montane lângă Brașov", etc.

        Args:
            topic: The guide topic

        Returns:
            Dict with generated content and metadata
        """
        if not topic:
            self.logger.warning("No topic provided for local guide")
            return {
                "status": "error",
                "error": "No topic provided",
            }

        # Check budget
        max_guide_tokens = int(self.max_tokens_per_article * 1.5)
        if not self._check_budget(max_guide_tokens):
            self.logger.warning("Daily token budget exceeded for guide")
            return {"status": "budget_exceeded"}

        try:
            prompt = LOCAL_GUIDE_PROMPT.format(topic=topic)
            generated_text, token_usage = self._call_claude(
                prompt,
                max_tokens=max_guide_tokens,
                temperature=0.9,
            )

            result = {
                "status": "success",
                "topic": topic,
                "content": generated_text,
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            # Save content
            self._save_generated_content(result, "guide", "brasov")

            self.logger.info(
                f"Local guide generated. Topic: {topic}, "
                f"Tokens: {token_usage.total_tokens}, Cost: ${token_usage.total_cost:.4f}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error generating local guide: {e}")
            return {"status": "error", "error": str(e)}

    def generate_opinion_piece(
        self,
        topic: str,
        articles_context: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate a 600-900 word opinion/analysis piece on a local topic.

        Args:
            topic: The opinion topic
            articles_context: Recent articles providing context for the opinion

        Returns:
            Dict with generated content and metadata
        """
        if not topic:
            self.logger.warning("No topic provided for opinion piece")
            return {
                "status": "error",
                "error": "No topic provided",
            }

        if not articles_context:
            self.logger.warning("No context articles for opinion piece")
            articles_context = []

        # Format context articles
        context_text = "\n\n---\n\n".join(
            [
                f"Titlu: {a.get('title', 'N/A')}\n"
                f"Text: {a.get('text', '')[:500]}..."  # Limit to first 500 chars
                for a in articles_context[:10]
            ]
        )

        # Check budget
        max_opinion_tokens = int(self.max_tokens_per_article * 1.5)
        if not self._check_budget(max_opinion_tokens):
            self.logger.warning("Daily token budget exceeded for opinion piece")
            return {"status": "budget_exceeded"}

        try:
            prompt = OPINION_PIECE_PROMPT.format(
                topic=topic,
                articles_context=context_text or "Fără context specific",
            )
            generated_text, token_usage = self._call_claude(
                prompt,
                max_tokens=max_opinion_tokens,
                temperature=0.9,
            )

            result = {
                "status": "success",
                "topic": topic,
                "content": generated_text,
                "context_articles": len(articles_context),
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            # Save content
            self._save_generated_content(result, "opinion", "brasov")

            self.logger.info(
                f"Opinion piece generated. Topic: {topic}, "
                f"Tokens: {token_usage.total_tokens}, Cost: ${token_usage.total_cost:.4f}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error generating opinion piece: {e}")
            return {"status": "error", "error": str(e)}

    def generate_daily_editorial(
        self,
        top_articles: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate a 400-600 word daily editorial intro for homepage.

        Args:
            top_articles: Top 3-5 articles of the day

        Returns:
            Dict with generated content and metadata
        """
        if not top_articles:
            self.logger.warning("No articles provided for daily editorial")
            return {
                "status": "error",
                "error": "No articles provided",
            }

        # Format articles for prompt
        articles_text = "\n\n---\n\n".join(
            [
                f"Titlu: {a.get('title', 'N/A')}\n"
                f"Sursă: {a.get('source', 'N/A')}\n"
                f"Text: {a.get('text', '')[:400]}..."  # First 400 chars
                for a in top_articles[:5]
            ]
        )

        # Check budget
        max_editorial_tokens = int(self.max_tokens_per_article * 1.2)
        if not self._check_budget(max_editorial_tokens):
            self.logger.warning("Daily token budget exceeded for editorial")
            return {"status": "budget_exceeded"}

        try:
            prompt = DAILY_EDITORIAL_PROMPT.format(top_articles=articles_text)
            generated_text, token_usage = self._call_claude(
                prompt,
                max_tokens=max_editorial_tokens,
                temperature=0.85,
            )

            result = {
                "status": "success",
                "content": generated_text,
                "article_count": len(top_articles),
                "date": datetime.now().date().isoformat(),
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            # Save content
            self._save_generated_content(result, "daily_editorial", "brasov")

            self.logger.info(
                f"Daily editorial generated. Articles: {len(top_articles)}, "
                f"Tokens: {token_usage.total_tokens}, Cost: ${token_usage.total_cost:.4f}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error generating daily editorial: {e}")
            return {"status": "error", "error": str(e)}

    def schedule_content_calendar(self) -> Dict[str, ContentCalendarEntry]:
        """
        Return a content plan: which type of long article to generate on which day.

        Returns:
            Dict mapping day number to ContentCalendarEntry
        """
        calendar = {
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
            2: ContentCalendarEntry(  # Wednesday
                day_of_week=2,
                day_name="Miercuri",
                content_type="guide",
                topic="Top evenimente în Brașov luna aceasta",
            ),
            3: ContentCalendarEntry(  # Thursday
                day_of_week=3,
                day_name="Joi",
                content_type="daily_editorial",
                topic=None,
            ),
            4: ContentCalendarEntry(  # Friday
                day_of_week=4,
                day_name="Vineri",
                content_type="opinion",
                topic="Impact local",
            ),
            5: ContentCalendarEntry(  # Saturday
                day_of_week=5,
                day_name="Sâmbătă",
                content_type="guide",
                topic="Trasee și atracții în Brașov",
            ),
            6: ContentCalendarEntry(  # Sunday
                day_of_week=6,
                day_name="Duminică",
                content_type="daily_editorial",
                topic=None,
            ),
        }

        self.logger.info("Content calendar scheduled")
        return calendar

    def get_today_content_plan(self) -> Optional[ContentCalendarEntry]:
        """Get the content plan for today."""
        calendar = self.schedule_content_calendar()
        today = datetime.now().weekday()
        return calendar.get(today)

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get current token usage statistics."""
        return {
            "session": {
                "input_tokens": self.session_tokens.input_tokens,
                "output_tokens": self.session_tokens.output_tokens,
                "total_tokens": self.session_tokens.total_tokens,
                "estimated_cost": f"${self.session_tokens.total_cost:.4f}",
            },
            "daily": {
                "input_tokens": self.daily_tokens.input_tokens,
                "output_tokens": self.daily_tokens.output_tokens,
                "total_tokens": self.daily_tokens.total_tokens,
                "estimated_cost": f"${self.daily_tokens.total_cost:.4f}",
                "budget_remaining": (
                    self.daily_token_budget - self.daily_tokens.total_tokens
                ),
                "budget_remaining_percent": (
                    (self.daily_token_budget - self.daily_tokens.total_tokens)
                    / self.daily_token_budget
                    * 100
                ),
            },
        }
