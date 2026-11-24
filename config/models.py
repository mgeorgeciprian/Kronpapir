"""Modelele Claude folosite de KronPapir, configurabile din .env.

- CLAUDE_MODEL            -> rescrierea știrilor, cuvinte cheie SEO (implicit Sonnet 5.5)
- CLAUDE_EDITORIAL_MODEL  -> editoriale (implicit Opus 5.5)
"""

import os

DEFAULT_ARTICLE_MODEL = "claude-sonnet-5-5"
DEFAULT_EDITORIAL_MODEL = "claude-opus-5-5"


def get_article_model() -> str:
    return os.environ.get("CLAUDE_MODEL") or DEFAULT_ARTICLE_MODEL


def get_editorial_model() -> str:
    return os.environ.get("CLAUDE_EDITORIAL_MODEL") or DEFAULT_EDITORIAL_MODEL
