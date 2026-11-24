"""Localitățile din zona Brașov pentru care KronPapir are pagini dedicate,
plus detectarea articolelor „utile” (informații practice pentru cititori)."""

import re
from datetime import datetime, timedelta
from typing import Dict, List

# slug -> (nume afișat, regex). Regexurile sunt case-sensitive (nume proprii)
# și acceptă forme fără diacritice și cu ş/ţ cu sedilă.
LOCALITIES: Dict[str, tuple] = {
    "sacele": ("Săcele", r"S[ăa]cele"),
    "tarlungeni": ("Tărlungeni", r"T[ăa]rlungeni"),
    "harman": ("Hărman", r"H[ăa]rman"),
    "sanpetru": ("Sânpetru", r"S[âîa]npetru"),
    "ghimbav": ("Ghimbav", r"Ghimbav"),
    "codlea": ("Codlea", r"Codlea"),
    "rasnov": ("Râșnov", r"R[âa][șşs]nov"),
    "zarnesti": ("Zărnești", r"Z[ăa]rne[șşs]ti"),
    "prejmer": ("Prejmer", r"Prejmer"),
    "predeal": ("Predeal", r"Predeal"),
    "bran": ("Bran", r"Bran(?![a-zăâîșşțţ])"),
    "fagaras": ("Făgăraș", r"F[ăa]g[ăa]ra[șşs]"),
    "rupea": ("Rupea", r"Rupea"),
    "poiana-brasov": ("Poiana Brașov", r"Poiana Bra[șşs]ov"),
}

_COMPILED = {slug: re.compile(rf"(?<![A-Za-zĂÂÎȘŞȚŢăâîșşțţ]){rx}") for slug, (_, rx) in LOCALITIES.items()}

SERVICE_RX = re.compile(
    r"\b(întrerupe|intrerupe|oprire(a)? (apei|curentului|gazelor)|fără apă|fara apa|fără curent|"
    r"program(ul)? (de|cu publicul|special)|termen(ul)? (limită|de depunere)|înscrier|inscrier|"
    r"bilete de tratament|burs[ăe]|impozit|taxe locale|deszăpezire|deszapezire|restricți|restrictii|"
    r"închiderea circulației|inchiderea circulatiei|devier|vaccinare|cod (galben|portocaliu|roșu))",
    re.IGNORECASE,
)


def _text(article: dict, limit: int = 2000) -> str:
    return " ".join([
        article.get("title", ""), article.get("excerpt", "") or "",
        re.sub(r"<[^>]+>", " ", article.get("content", "") or "")[:limit],
    ])


def detect_localities(article: dict) -> List[str]:
    if article.get("localities"):
        return article["localities"]
    text = _text(article)
    return [slug for slug, rx in _COMPILED.items() if rx.search(text)]


def is_service_article(article: dict) -> bool:
    if "is_service" in article:
        return bool(article["is_service"])
    return bool(SERVICE_RX.search(article.get("title", "") + " " + (article.get("excerpt") or "")))


def is_recent(article: dict, days: int) -> bool:
    try:
        date = datetime.fromisoformat(str(article.get("date", ""))[:19])
    except ValueError:
        return False
    return date >= datetime.now() - timedelta(days=days)
