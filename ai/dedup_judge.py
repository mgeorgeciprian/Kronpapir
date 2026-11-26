"""Redactorul-șef decide, pentru perechile la limită, dacă două știri sunt același eveniment.

Folosit de run_pipeline.py prin editorial.dedup.check(..., judge=make_judge()).
Modelul și plafonul: config/agents.yaml, cheia `redactor-sef`. Prompt: .claude/agents/redactor-sef.md.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from ai import costs

log = logging.getLogger("ai.dedup_judge")

AGENT = "redactor-sef"
DEFAULT_MODEL = "claude-opus-5-5"
PROMPT_FILE = Path(__file__).resolve().parent.parent / ".claude" / "agents" / "redactor-sef.md"
SCHEMA = {
    "type": "object",
    "properties": {"aceeasi_stire": {"type": "boolean"}, "motiv": {"type": "string"}},
    "required": ["aceeasi_stire", "motiv"],
    "additionalProperties": False,
}


def _prompt():
    text = PROMPT_FILE.read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def _brief(article, label):
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", article.get("content") or article.get("text") or ""))[:900]
    return (f"{label}\nSursa: {article.get('source') or '?'}\nData: {(article.get('date') or '?')[:16]}\n"
            f"Titlu: {article.get('source_title') or article.get('title') or ''}\nText: {body}")


def make_judge(client=None):
    """Întoarce judge(candidat, existent) -> (bool, motiv), sau None dacă nu avem cheie/buget.

    La orice eroare sau la plafon atins, răspunsul e „știri diferite” (nu pierdem știri).
    """
    cfg = costs.settings(AGENT, DEFAULT_MODEL)
    try:
        costs.check(cfg, datetime.now())
    except costs.BudgetExceeded as e:
        log.warning("%s Verificarea AI a duplicatelor e oprită; rămâne doar scorul automat.", e)
        return None
    if client is None:
        try:
            from anthropic import Anthropic
            client = Anthropic()
        except Exception as e:  # lipsă modul sau cheie
            log.warning("Fără client Claude pentru duplicate: %s", e)
            return None
    system = _prompt()

    def judge(candidate, existing):
        now = datetime.now()
        try:
            costs.check(cfg, now)
            msg = client.beta.messages.create(
                model=cfg["model"],
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content":
                           "Verificare de duplicat. Sunt același eveniment?\n\n"
                           + _brief(candidate, "ȘTIREA CANDIDATĂ") + "\n\n"
                           + _brief(existing, "ȘTIREA EXISTENTĂ")}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
            )
            costs.record(AGENT, cfg["model"], msg.usage, now)
            if msg.stop_reason != "end_turn":
                return False, f"răspuns neutilizabil ({msg.stop_reason})"
            text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
            data = json.loads(text)
            return bool(data.get("aceeasi_stire")), str(data.get("motiv") or "")[:200]
        except costs.BudgetExceeded as e:
            return False, str(e)
        except Exception as e:
            log.warning("Verificarea AI a duplicatului a eșuat: %s", e)
            return False, f"eroare: {str(e)[:120]}"

    return judge
