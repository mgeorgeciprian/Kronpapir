"""Poze ilustrative cu licență liberă (Wikimedia Commons), pentru articolele fără imagine proprie.

Pozele stau în static/images/foto/, iar foto.json are pentru fiecare: legenda, etichetele,
autorul, licența și pagina sursă. Licențele CC BY / CC BY-SA cer menționarea autorului și a
licenței, cu link: vezi credit() și legenda din templates/article.html.

Alegerea, în ordine:
1. subiectul din titlu (poliție, pompieri, ambulanță, justiție, spital, tren, iarnă);
2. localitatea din titlu (Săcele, Tărlungeni, Poiana Brașov, Râșnov, Bran...);
3. categoria articolului; altfel o poză generală din Brașov.
Dintre pozele potrivite se alege mereu aceeași pentru același articol (după id).
"""
import hashlib
import json
import re
import threading
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FOTO_DIR = BASE_DIR / "static" / "images" / "foto"
MANIFEST = FOTO_DIR / "foto.json"
PUBLIC_PREFIX = "/static/images/foto/"

# Subiecte, în ordinea priorității. Textul e fără diacritice și cu litere mici.
TOPICS = [
    ("pompieri", re.compile(r"\b(incendi\w*|pompier\w*|isu|flacar\w*|explozi\w*|a luat foc|arde|degajar\w*)\b")),
    ("politie", re.compile(r"\b(politia|politiei|politist\w*|ipj|arestat\w*|retinut\w*|furt\w*|talhar\w*|"
                           r"perchezit\w*|dosar penal|drogur\w*|inselaci\w*|crima|crime|ucis\w*|omor\w*|"
                           r"agresa\w*|agresiun\w*|jaf\w*|loverboy|trafic de|violent\w*)\b")),
    ("ambulanta", re.compile(r"\b(accident\w*|ambulant\w*|smurd|ranit\w*|resuscit\w*)\b")),
    ("justitie", re.compile(r"\b(tribunal\w*|instant\w*|judecat\w*|condamn\w*|procuror\w*|diicot|dna|"
                            r"parchet\w*|sentint\w*)\b")),
    ("spital", re.compile(r"\b(spital\w*|pacient\w*|medic|medici|medicii)\b")),
    ("tren", re.compile(r"\b(tren\w*|cfr|gara|garii|feroviar\w*)\b")),
    ("iarna", re.compile(r"\b(zapad\w*|ninsoar\w*|ninge|viscol\w*|deszapez\w*|ger|polei)\b")),
]
PLACES = [
    ("sacele", re.compile(r"\bsacele\w*\b")),
    ("tarlungeni", re.compile(r"\b(tarlungeni|zizin|purcareni|carpinis)\b")),
    ("poiana-brasov", re.compile(r"\bpoiana brasov\b")),
    ("rasnov", re.compile(r"\brasnov\w*\b")),
    ("bran", re.compile(r"\bbran\b")),
    ("codlea", re.compile(r"\bcodlea\b")),
    ("fagaras", re.compile(r"\bfagaras\w*\b")),
    ("prejmer", re.compile(r"\bprejmer\b")),
]
CATEGORY_TAGS = {"sport": "sport", "cultura": "cultura", "economie": "economie", "mediu": "mediu",
                 "social": "social", "sanatate": "spital", "accidente": "ambulanta"}
# Subiectele pentru care poza ilustrativă e potrivită și nu mai e nevoie de un desen AI.
EMERGENCY_TOPICS = {"pompieri", "ambulanta", "politie", "justitie"}
# Pentru știrile naționale și internaționale nu punem poze din Brașov: doar mașini de intervenție generice.
NON_LOCAL_TAGS = {"pompieri", "ambulanta", "politie"}

_cache = {"key": None, "data": {}}
_lock = threading.Lock()


def load_manifest():
    try:
        st = MANIFEST.stat()
    except FileNotFoundError:
        return {}
    key = (st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] != key:
            try:
                _cache.update(key=key, data=json.loads(MANIFEST.read_text(encoding="utf-8")))
            except ValueError:
                _cache.update(key=key, data={})
        return _cache["data"]


def _fold(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def topic(article):
    """(tip, eticheta): ('topic', 'politie'), ('place', 'sacele'), ('category', 'sport') sau ('generic', 'brasov')."""
    article = article or {}
    keywords = article.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    title = _fold(article.get("title") or "")
    text = _fold(" ".join([title] + [str(k) for k in keywords]))
    for tag, rx in TOPICS:
        if rx.search(text):
            return "topic", tag
    for tag, rx in PLACES:  # localitatea doar din titlu: cuvintele cheie pomenesc uneori localități vecine
        if rx.search(title):
            return "place", tag
    cat = CATEGORY_TAGS.get((article.get("category") or "").lower())
    if cat:
        return "category", cat
    return "generic", "brasov"


def choose(article):
    """Intrarea din foto.json potrivită articolului, sau None dacă nu avem poze."""
    manifest = load_manifest()
    if not manifest:
        return None
    kind, tag = topic(article)
    local = (article or {}).get("type", "local") == "local" and not (article or {}).get("is_editorial")
    if not local and not (kind == "topic" and tag in NON_LOCAL_TAGS):
        return None
    pool = sorted(k for k, v in manifest.items() if tag in v.get("tags", []))
    if not pool:
        pool = sorted(k for k, v in manifest.items() if "brasov" in v.get("tags", []))
    if not pool:
        return None
    seed = str((article or {}).get("id") or (article or {}).get("title") or "")
    key = pool[int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % len(pool)]
    return dict(manifest[key], key=key, url=PUBLIC_PREFIX + manifest[key]["file"])


def needs_illustration(article):
    """Desenul AI nu mai e necesar când avem o poză ilustrativă pe subiect (poliție, pompieri...)."""
    kind, tag = topic(article)
    return not (kind == "topic" and tag in EMERGENCY_TOPICS)
