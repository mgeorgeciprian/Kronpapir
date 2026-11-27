"""Plafoanele de cost: alertă o singură dată pe prag și lună, oprire la 100%, jurnalistul și editorialul respectă plafonul."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from ai import costs

NOW = datetime(2026, 11, 27, 6, 0)


@pytest.fixture
def ledger_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(costs, "COSTS_DIR", tmp_path)
    monkeypatch.delenv("SMTP_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    return tmp_path


def _spend(folder, agent, usd):
    (folder / f"{agent}-2026-11.json").write_text(json.dumps({"usd": usd, "calls": 1}), encoding="utf-8")


def _cfg(agent="jurnalist", budget=10.0):
    return {"agent": agent, "budget": budget, "alert": 0.8, "model": "claude-sonnet-5-5"}


def test_under_threshold_no_alert(ledger_dir):
    _spend(ledger_dir, "jurnalist", 5.0)
    sent = []
    costs.check(_cfg(), NOW, send=lambda s, b: sent.append(s))
    assert sent == []


def test_alert_once_per_threshold(ledger_dir):
    _spend(ledger_dir, "jurnalist", 8.5)
    sent = []
    send = lambda s, b: sent.append(s)
    costs.check(_cfg(), NOW, send=send)
    costs.check(_cfg(), NOW, send=send)
    assert len(sent) == 1 and "80%" in sent[0]
    saved = json.loads((ledger_dir / "jurnalist-2026-11.json").read_text(encoding="utf-8"))
    assert saved["alerts_sent"] == ["80"] and saved["usd"] == 8.5


def test_stop_at_budget_with_alert(ledger_dir):
    _spend(ledger_dir, "jurnalist", 10.0)
    sent = []
    with pytest.raises(costs.BudgetExceeded):
        costs.check(_cfg(), NOW, send=lambda s, b: sent.append(s))
    assert len(sent) == 1 and "oprit" in sent[0]


def test_record_keeps_alert_markers(ledger_dir):
    _spend(ledger_dir, "jurnalist", 8.5)
    costs.check(_cfg(), NOW, send=lambda s, b: None)
    costs.record("jurnalist", "claude-sonnet-5-5", SimpleNamespace(input_tokens=1000, output_tokens=100), NOW)
    saved = json.loads((ledger_dir / "jurnalist-2026-11.json").read_text(encoding="utf-8"))
    assert saved["alerts_sent"] == ["80"] and saved["calls"] == 2


def test_failed_email_still_marks_and_continues(ledger_dir):
    _spend(ledger_dir, "jurnalist", 9.0)

    def boom(s, b):
        raise OSError("smtp down")
    costs.check(_cfg(), NOW, send=boom)  # nu ridică
    saved = json.loads((ledger_dir / "jurnalist-2026-11.json").read_text(encoding="utf-8"))
    assert saved["alerts_sent"] == ["80"]


def test_no_smtp_config_sends_nothing(ledger_dir):
    assert costs._send_email("x", "y") is False


class _Client:
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        raise AssertionError("API-ul nu trebuia apelat")


def test_rewriter_skips_api_over_budget(ledger_dir, monkeypatch):
    from ai import rewriter
    _spend(ledger_dir, "jurnalist", 1e6)
    r = rewriter.ArticleRewriter.__new__(rewriter.ArticleRewriter)
    r.client, r.model, r.rate_limit_delay, r.last_api_call = _Client(), "claude-sonnet-5-5", 0, 0
    assert r._request_json("prompt", rewriter.ARTICLE_SCHEMA) is None
    assert r.client.calls == 0


def test_editorial_skips_api_over_budget(ledger_dir):
    from ai import editorial
    _spend(ledger_dir, "editorial", 1e6)
    a = editorial.EditorialAgent.__new__(editorial.EditorialAgent)
    a.client, a.model, a.rate_limit_delay, a.last_api_call = _Client(), "claude-sonnet-5-5", 0, 0
    assert a._call_claude("prompt") is None
    assert a.client.calls == 0
