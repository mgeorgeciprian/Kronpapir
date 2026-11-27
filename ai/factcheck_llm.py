"""Fact-check, pasul 2: editorul de fact-check (Claude) compară rescrierea cu sursa.

Prompt: .claude/agents/editor-fact-check.md. Modelul și plafonul: config/agents.yaml (`editor-fact-check`).
La eroare sau plafon atins întoarce None, iar decizia devine `draft` (nimic nu se publică neverificat).
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from ai import costs
from editorial.factcheck import plain

log = logging.getLogger("ai.factcheck_llm")

AGENT = "editor-fact-check"
DEFAULT_MODEL = "claude-sonnet-5-5"
PROMPT_FILE = Path(__file__).resolve().parent.parent / ".claude" / "agents" / "editor-fact-check.md"
SOURCE_CHARS = 12000
ERROR = {
    "type": "object",
    "properties": {"tip": {"type": "string"}, "valoare": {"type": "string"}, "motiv": {"type": "string"}},
    "required": ["tip", "valoare", "motiv"],
    "additionalProperties": False,
}
SCHEMA = {
    "type": "object",
    "properties": {
        "scor": {"type": "integer"},
        "erori_blocante": {"type": "array", "items": ERROR},
        "subiect_sensibil": {"type": "boolean"},
        "motiv_sensibil": {"type": "string"},
        "recomandari": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["scor", "erori_blocante", "subiect_sensibil", "motiv_sensibil", "recomandari"],
    "additionalProperties": False,
}


def _prompt():
    text = PROMPT_FILE.read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


class FactChecker:
    def __init__(self, client=None):
        self.cfg = costs.settings(AGENT, DEFAULT_MODEL)
        self.client = client
        self.system = _prompt()

    def _client(self):
        if self.client is None:
            from anthropic import Anthropic
            self.client = Anthropic()
        return self.client

    def check(self, source_article, rewritten, source_chars=SOURCE_CHARS):
        now = datetime.now()
        try:
            costs.check(self.cfg, now)
        except costs.BudgetExceeded as e:
            log.warning("%s Rescrierile merg ca ciorne.", e)
            return None
        source = plain(source_article.get("content") or source_article.get("text")
                       or source_article.get("original_text") or "")[:source_chars]
        user = (f"TEXTUL SURSĂ ({source_article.get('source') or '?'}, {source_article.get('url') or ''}):\n"
                f"Titlu: {source_article.get('title') or ''}\n{source}\n\n"
                f"RESCRIEREA KRONPAPIR:\nTitlu: {rewritten.get('title') or ''}\n"
                f"Rezumat: {plain(rewritten.get('excerpt') or '')}\n{plain(rewritten.get('content') or '')}")
        try:
            msg = self._client().beta.messages.create(
                model=self.cfg["model"],
                max_tokens=8000,
                system=self.system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
            costs.record(AGENT, self.cfg["model"], msg.usage, now)
            if msg.stop_reason != "end_turn":
                log.warning("Fact-check neutilizabil (stop: %s)", msg.stop_reason)
                return None
            text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
            data = json.loads(text)
            data["scor"] = max(1, min(10, int(data.get("scor") or 1)))
            data["model"] = self.cfg["model"]
            return data
        except Exception as e:
            log.warning("Fact-check eșuat: %s", e)
            return None
