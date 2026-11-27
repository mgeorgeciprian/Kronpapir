"""Costurile agenților: modelul și plafonul din config/agents.yaml, consumul lunar în data/costs/.

La 80% din plafon (alert_threshold) George primește o ALERTĂ (în log și, dacă SMTP e configurat în .env,
pe email la redactia@kronpapir.ro, o singură dată pe lună pentru fiecare prag); la 100% agentul se oprește.
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


# Cache: o citire costă 5% din prețul de intrare (Sonnet 5.5, Opus 5.5), o scriere cu TTL de 5 minute 125%.
CACHE_READ = {"claude-sonnet-5-5": 0.05, "claude-opus-5-5": 0.05}
CACHE_WRITE = 1.25


def _tok(usage, name):
    return int(getattr(usage, name, 0) or 0)


def record(agent, model, usage, now):
    """Adaugă costul unui apel și tokenii lui. Întoarce (cost_apel, total_lună).

    input_tokens nu include tokenii citiți din cache sau scriși în cache; îi numărăm separat.
    """
    pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
    t_in, t_out = _tok(usage, "input_tokens"), _tok(usage, "output_tokens")
    t_read, t_write = _tok(usage, "cache_read_input_tokens"), _tok(usage, "cache_creation_input_tokens")
    usd = (t_in * pin + t_out * pout + t_read * pin * CACHE_READ.get(model, 0.1) + t_write * pin * CACHE_WRITE) / 1e6
    path = _ledger_path(agent, now)
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        ledger = {"usd": 0.0, "calls": 0}
    ledger["usd"] = round(ledger["usd"] + usd, 6)
    ledger["calls"] += 1
    for key, val in (("input_tokens", t_in), ("output_tokens", t_out),
                     ("cache_read_tokens", t_read), ("cache_write_tokens", t_write)):
        ledger[key] = ledger.get(key, 0) + val
    editorial_store._write_json_atomic(path, ledger)
    return usd, ledger["usd"]


def report(now, folder=None):
    """Consumul lunii pe agenți: [(agent, usd, apeluri, tokeni intrare, ieșire, din cache)]."""
    rows = []
    for p in sorted(Path(folder or COSTS_DIR).glob(f"*-{now:%Y-%m}.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows.append((p.name[:-len(f"-{now:%Y-%m}.json")], d.get("usd", 0), d.get("calls", 0), d.get("input_tokens"),
                     d.get("output_tokens"), d.get("cache_read_tokens")))
    return rows


ALERT_TO = "redactia@kronpapir.ro"


def _send_email(subject, body):
    """Trimite alerta prin SMTP-ul din .env (același cont ca formularul de contact). False dacă nu e configurat."""
    user, password = os.environ.get("SMTP_EMAIL"), os.environ.get("SMTP_PASSWORD")
    if not (user and password):
        return False
    import smtplib
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, ALERT_TO
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
        server.login(user, password)
        server.send_message(msg)
    return True


def alert(agent, level, used, budget, now, send=None):
    """Alerta pentru George la un prag ("80" sau "100"), o singură dată pe lună și prag.

    Pragul trimis se notează în registrul lunii (alerts_sent), ca să nu vină câte un email la fiecare apel.
    """
    path = _ledger_path(agent, now)
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        ledger = {"usd": 0.0, "calls": 0}
    if level in ledger.get("alerts_sent", []):
        return False
    what = "s-a oprit (plafon atins)" if level == "100" else f"a trecut de {level}% din plafon"
    text = (f"Agentul {agent} {what}: {used:.2f} din {budget:.2f} USD în {now:%m.%Y}.\n\n"
            f"Plafonul se schimbă în config/agents.yaml (monthly_budget_usd). Consumul: python -m ai.costs")
    log.warning("ALERTĂ pentru George: %s", text.splitlines()[0])
    try:
        (send or _send_email)(f"[KronPapir] Cost AI: {agent} {what}", text)
    except Exception as e:  # alerta nu are voie să oprească jobul; rămâne în log
        log.warning("Emailul de alertă nu s-a trimis: %s", e)
    ledger["alerts_sent"] = ledger.get("alerts_sent", []) + [level]
    editorial_store._write_json_atomic(path, ledger)
    return True


def check(cfg, now, send=None):
    """Ridică BudgetExceeded dacă plafonul lipsește sau e atins; alertează peste prag."""
    agent, budget = cfg["agent"], cfg["budget"]
    if budget <= 0:
        raise BudgetExceeded(f"Agentul {agent} nu are plafon în config/agents.yaml; nu rulez.")
    used = spent(agent, now)
    if used >= budget:
        alert(agent, "100", used, budget, now, send)
        raise BudgetExceeded(f"Plafonul lunar al agentului {agent} e atins: {used:.2f} din {budget:.2f} USD.")
    if used >= budget * cfg["alert"]:
        alert(agent, f"{cfg['alert'] * 100:.0f}", used, budget, now, send)


def allowed(agent, default_model, now=None):
    """True dacă agentul mai are buget luna asta; altfel scrie motivul în log și întoarce False."""
    from datetime import datetime as _dt
    try:
        check(settings(agent, default_model), now or _dt.now())
        return True
    except BudgetExceeded as e:
        log.error("%s Apelul nu se face.", e)
        return False


if __name__ == "__main__":  # python -m ai.costs : consumul lunii curente
    from datetime import datetime as _dt
    fmt = lambda v: "–" if v is None else f"{v:,}".replace(",", ".")
    print(f"{'agent':22} {'USD':>8} {'apeluri':>8} {'intrare':>12} {'ieșire':>10} {'din cache':>11}")
    for a, usd, calls, i, o, c in report(_dt.now()):
        print(f"{a:22} {usd:8.2f} {calls:8} {fmt(i):>12} {fmt(o):>10} {fmt(c):>11}")
    print("Tokenii se numără de la 27.11.2026; înainte se salvau doar dolarii.")
