"""Când expiră un anunț de licitație și trece în arhivă.

- termenul limită (`deadline`), dacă îl știm: din anunț sau din titlu („termen ... 05.12.2026”);
- altfel, pentru anunțurile primăriilor: data reală a anunțului + 30 de zile, sau ziua în care
  l-am găsit + 30 de zile când nu are dată;
- bunurile ANAF n-au termen sigur în flux: rămân active cât timp ANAF le ține în fluxuri.
"""
import re
from datetime import date, timedelta

from .sites import date_in_text

FALLBACK_DAYS = 30
DEADLINE_RE = re.compile(r"termen(ul)?(\s+limit[ăa])?(\s+de\s+depunere)?[^0-9]{0,40}", re.I)


def deadline_in_title(title):
    """Data de după „termen (limită)” din titlu, ca ISO; None dacă nu e scrisă."""
    m = DEADLINE_RE.search(title or "")
    return date_in_text(title[m.end():m.end() + 25]) if m else None


def expires_on(item):
    """Ziua (ISO) după care anunțul nu mai e activ; None = fără dată (ANAF: cât e în flux)."""
    if item.get("deadline"):
        return str(item["deadline"])[:10]
    if item.get("source") == "anaf" or item.get("kind") == "anaf_sale":
        return None
    when = str(item.get("published") or "")[:10]
    if not when or item.get("date_guessed"):
        when = str(item.get("first_seen") or "")[:10]
    if not when:
        return None
    try:
        return (date.fromisoformat(when) + timedelta(days=FALLBACK_DAYS)).isoformat()
    except ValueError:
        return None


def is_expired(item, today):
    exp = expires_on(item)
    return bool(exp) and exp < str(today)[:10]
