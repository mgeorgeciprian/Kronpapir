"""Costurile agenților: modelul și plafonul din config/agents.yaml, consumul lunar în data/costs/.

La 80% din plafon (alert_threshold) se scrie o ALERTĂ în log pentru George; la 100% agentul se oprește.
"""
import json
import logging
import os
from pathlib import Path

import yaml

from editorial import store as editorial_store

log = logging.getLogger("ai.costs")

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_CONFIG = BASE_DIR / "config" / "agents.yaml"
COSTS_DIR = BASE_DIR / "data" / "costs"

# USD per milion de tokeni (input, output). Necunoscut -> prețul Opus, ca să nu subestimăm.
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0), "claude-haiku-5-5": (0.10, 0.50)}


class BudgetExceeded(RuntimeError):
    pass


def settings(agent, default_model, path=None):
    """Setările agentului din config/agents.yaml; modelul se poate suprascrie din .env."""
    try:
        cfg = yaml.safe_load(Path(path or AGENTS_CONFIG).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        cfg = {}
    entry = dict((cfg.get("agents") or {}).get(agent) or {})
    env_key = "KRONPAPIR_MODEL_" + agent.upper().replace("-", "_")
    entry["model"] = os.environ.get(env_key) or entry.get("model") or default_model
    entry["budget"] = float(entry.get("monthly_budget_usd") or 0)
    entry["alert"] = float(cfg.get("alert_threshold") or 0.8)
    entry["agent"] = agent
    return entry


def _ledger_path(agent, now):
    return COSTS_DIR / f"{agent}-{now:%Y-%m}.json"


def spent(agent, now):
    try:
        return float(json.loads(_ledger_path(agent, now).read_text(encoding="utf-8")).get("usd", 0))
    except (FileNotFoundError, ValueError):
        return 0.0


def record(agent, model, usage, now):
    """Adaugă costul unui apel. Întoarce (cost_apel, total_lună)."""
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    usd = (getattr(usage, "input_tokens", 0) * pin + getattr(usage, "output_tokens", 0) * pout) / 1e6
    path = _ledger_path(agent, now)
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        ledger = {"usd": 0.0, "calls": 0}
    ledger["usd"] = round(ledger["usd"] + usd, 6)
    ledger["calls"] += 1
    editorial_store._write_json_atomic(path, ledger)
    return usd, ledger["usd"]


def check(cfg, now):
    """Ridică BudgetExceeded dacă plafonul lipsește sau e atins; avertizează peste prag."""
    agent, budget = cfg["agent"], cfg["budget"]
    if budget <= 0:
        raise BudgetExceeded(f"Agentul {agent} nu are plafon în config/agents.yaml; nu rulez.")
    used = spent(agent, now)
    if used >= budget:
        raise BudgetExceeded(f"Plafonul lunar al agentului {agent} e atins: {used:.2f} din {budget:.2f} USD.")
    if used >= budget * cfg["alert"]:
        log.warning("ALERTĂ pentru George: %s a consumat %.2f din %.2f USD luna aceasta.", agent, used, budget)
