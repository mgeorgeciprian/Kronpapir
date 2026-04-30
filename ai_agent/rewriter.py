"""
Main Claude AI article rewriter for kronpapir.ro.
Handles article rewriting, summarization, headline generation, and categorization.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import anthropic

from .prompts import (
    SYSTEM_PERSONA,
    REWRITE_ARTICLE_PROMPT,
    SUMMARIZE_NATIONAL_PROMPT,
    HEADLINE_PROMPT,
    CATEGORIZE_PROMPT,
    CONTENT_MODERATION_PROMPT,
    REFINE_ARTICLE_PROMPT,
)


@dataclass
class TokenUsage:
    """Track token usage for cost monitoring."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @property
    def total_cost(self) -> float:
        """Estimate cost in USD. Sonnet 4.5: $3/$15 per MTok."""
        input_cost = (self.input_tokens / 1_000_000) * 3
        output_cost = (self.output_tokens / 1_000_000) * 15
        return input_cost + output_cost

    def __str__(self) -> str:
        return (f"Tokens: {self.total_tokens} | "
                f"Input: {self.input_tokens} | "
                f"Output: {self.output_tokens} | "
                f"Cost: ${self.total_cost:.4f}")


class RateLimiter:
    """Simple rate limiter for API calls."""
    def __init__(self, max_requests_per_minute: int = 60):
        self.max_requests = max_requests_per_minute
        self.request_times: List[float] = []

    def wait_if_needed(self):
        """Wait if necessary to maintain rate limit."""
        now = time.time()
        # Remove timestamps older than 1 minute
        self.request_times = [t for t in self.request_times if now - t < 60]

        if len(self.request_times) >= self.max_requests:
            sleep_time = 60 - (now - self.request_times[0])
            if sleep_time > 0:
                logging.info(f"Rate limit: sleeping for {sleep_time:.2f}s")
                time.sleep(sleep_time)

        self.request_times.append(now)


class ArticleRewriter:
    """Main class for rewriting articles using Claude AI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens_per_article: int = 1500,
        daily_token_budget: int = 500_000,
        rate_limit_requests_per_minute: int = 60,
    ):
        """Initialize the rewriter with API configuration."""
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in environment or parameters")

        self.model = model
        self.max_tokens_per_article = max_tokens_per_article
        self.daily_token_budget = daily_token_budget

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.rate_limiter = RateLimiter(max_requests_per_minute)

        # Token tracking
        self.session_tokens = TokenUsage()
        self.daily_tokens = TokenUsage()

        # Setup logging
        self.logger = self._setup_logging()
        self.logger.info(f"ArticleRewriter initialized with model: {self.model}")

    def _setup_logging(self) -> logging.Logger:
        """Configure logging."""
        logger = logging.getLogger("kronpapir.rewriter")
        logger.setLevel(logging.INFO)

        # Create logs directory if needed
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # File handler
        fh = logging.FileHandler(log_dir / "rewriter.log")
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

    def rewrite_article(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rewrite a single article to make it original while preserving facts.

        Args:
            article: Article dict with 'text' key and optional 'title', 'source'

        Returns:
            Dict with rewritten article and metadata
        """
        if not article.get("text"):
            self.logger.warning("Article missing text field")
            return {
                "status": "error",
                "error": "Missing article text",
                "original": article,
            }

        # Check budget
        if not self._check_budget(self.max_tokens_per_article):
            self.logger.warning("Daily token budget exceeded")
            return {
                "status": "budget_exceeded",
                "original": article,
                "fallback": True,
            }

        try:
            prompt = REWRITE_ARTICLE_PROMPT.format(article_text=article["text"])
            rewritten_text, token_usage = self._call_claude(prompt, temperature=0.85)

            result = {
                "status": "success",
                "original_text": article["text"],
                "rewritten_text": rewritten_text,
                "original_title": article.get("title", ""),
                "source": article.get("source", "unknown"),
                "author": "Redacția KronPapir",
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            self.logger.info(
                f"Article rewritten. Source: {article.get('source', 'unknown')}, "
                f"Tokens: {token_usage.total_tokens}, Cost: ${token_usage.total_cost:.4f}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error rewriting article: {e}")
            return {
                "status": "error",
                "error": str(e),
                "original": article,
                "fallback": True,
            }

    def summarize_national(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate a daily national news summary from multiple articles.

        Args:
            articles: List of article dicts

        Returns:
            Daily summary with categorized top stories
        """
        if not articles:
            return {"status": "error", "error": "No articles provided"}

        # Check budget (more generous for summaries)
        max_summary_tokens = self.max_tokens_per_article * 2
        if not self._check_budget(max_summary_tokens):
            self.logger.warning("Daily token budget exceeded for summary")
            return {"status": "budget_exceeded"}

        try:
            # Format articles for the prompt
            articles_text = "\n\n---\n\n".join(
                [
                    f"Titlu: {a.get('title', 'N/A')}\n"
                    f"Sursă: {a.get('source', 'N/A')}\n"
                    f"Text: {a.get('text', '')}"
                    for a in articles
                ]
            )

            prompt = SUMMARIZE_NATIONAL_PROMPT.format(articles_list=articles_text)
            summary_text, token_usage = self._call_claude(
                prompt, max_tokens=max_summary_tokens, temperature=0.5
            )

            result = {
                "status": "success",
                "summary": summary_text,
                "article_count": len(articles),
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            self.logger.info(
                f"Daily summary generated. Articles: {len(articles)}, "
                f"Tokens: {token_usage.total_tokens}, Cost: ${token_usage.total_cost:.4f}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error generating summary: {e}")
            return {"status": "error", "error": str(e)}

    def generate_headline(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate catchy yet professional headlines for an article.

        Args:
            article: Article dict with 'text' key

        Returns:
            Dict with 3 alternative headlines and explanations
        """
        if not article.get("text"):
            return {"status": "error", "error": "Missing article text"}

        # Check budget
        if not self._check_budget(800):
            return {"status": "budget_exceeded"}

        try:
            prompt = HEADLINE_PROMPT.format(article_text=article["text"])
            headline_text, token_usage = self._call_claude(
                prompt, max_tokens=800, temperature=0.8
            )

            result = {
                "status": "success",
                "headlines_raw": headline_text,
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            # Try to parse headlines from response
            try:
                lines = headline_text.split("\n")
                headlines = [
                    line.strip().lstrip("0123456789. ").strip()
                    for line in lines
                    if line.strip() and any(c.isalpha() for c in line)
                ]
                result["headlines"] = headlines[:3]
            except Exception as parse_e:
                self.logger.warning(f"Could not parse headlines: {parse_e}")

            self.logger.info(
                f"Headlines generated. Tokens: {token_usage.total_tokens}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error generating headlines: {e}")
            return {"status": "error", "error": str(e)}

    def categorize(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        Auto-categorize an article into predefined categories.

        Categories: Politică, Economie, Sport, Cultură, Social, Educație,
                   Sănătate, Meteo, Evenimente, Accidente

        Args:
            article: Article dict with 'text' key

        Returns:
            Dict with category, confidence, and explanation
        """
        if not article.get("text"):
            return {"status": "error", "error": "Missing article text"}

        # Check budget
        if not self._check_budget(500):
            return {"status": "budget_exceeded"}

        try:
            prompt = CATEGORIZE_PROMPT.format(article_text=article["text"])
            category_text, token_usage = self._call_claude(
                prompt, max_tokens=500, temperature=0.3
            )

            result = {
                "status": "success",
                "tokens_used": token_usage.total_tokens,
                "cost": token_usage.total_cost,
                "timestamp": datetime.now().isoformat(),
            }

            # Parse JSON response
            try:
                # Extract JSON from response
                json_start = category_text.find("{")
                json_end = category_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = category_text[json_start:json_end]
                    category_data = json.loads(json_str)
                    result.update(category_data)
                else:
                    result["raw_response"] = category_text
            except json.JSONDecodeError as je:
                self.logger.warning(f"Could not parse category JSON: {je}")
                result["raw_response"] = category_text

            self.logger.info(
                f"Article categorized. Tokens: {token_usage.total_tokens}"
            )

            return result

        except Exception as e:
            self.logger.error(f"Error categorizing article: {e}")
            return {"status": "error", "error": str(e)}

    def moderate_content(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check article content for policy violations and misinformation indicators.

        Args:
            article: Article dict with 'text' key

        Returns:
            Dict with moderation status and recommendations
        """
        if not article.get("text"):
            return {"status": "error", "error": "Missing article text"}

        # Check budget
        if not self._check_budget(600):
            return {"status": "budget_exceeded"}

        try:
            prompt = CONTENT_MODERATION_PROMPT.format(article_text=article["text"])
            moderation_text, token_usage = self._call_claude(
                prompt, max_tokens=600, temperature=0.2
            )

            result = {
                "status": "success",
                "tokens_used": token_usage.total_tokens,
                "timestamp": datetime.now().isoformat(),
            }

            # Parse JSON response
            try:
                json_start = moderation_text.find("{")
                json_end = moderation_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = moderation_text[json_start:json_end]
                    mod_data = json.loads(json_str)
                    result.update(mod_data)
                else:
                    result["raw_response"] = moderation_text
            except json.JSONDecodeError:
                result["raw_response"] = moderation_text

            return result

        except Exception as e:
            self.logger.error(f"Error moderating content: {e}")
            return {"status": "error", "error": str(e)}

    def refine_article(self, rewritten_text: str) -> Dict[str, Any]:
        """
        Check quality of rewritten article and suggest improvements.

        Args:
            rewritten_text: The rewritten article text

        Returns:
            Dict with quality score, issues, and suggestions
        """
        if not rewritten_text:
            return {"status": "error", "error": "Missing article text"}

        # Check budget
        if not self._check_budget(800):
            return {"status": "budget_exceeded"}

        try:
            prompt = REFINE_ARTICLE_PROMPT.format(article_text=rewritten_text)
            refine_text, token_usage = self._call_claude(
                prompt, max_tokens=800, temperature=0.3
            )

            result = {
                "status": "success",
                "tokens_used": token_usage.total_tokens,
                "timestamp": datetime.now().isoformat(),
            }

            # Parse JSON response
            try:
                json_start = refine_text.find("{")
                json_end = refine_text.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = refine_text[json_start:json_end]
                    refine_data = json.loads(json_str)
                    result.update(refine_data)
                else:
                    result["raw_response"] = refine_text
            except json.JSONDecodeError:
                result["raw_response"] = refine_text

            return result

        except Exception as e:
            self.logger.error(f"Error refining article: {e}")
            return {"status": "error", "error": str(e)}

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
