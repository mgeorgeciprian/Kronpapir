"""Aceeași știre din două surse: o depistăm înainte de rescriere, ca să nu o publicăm de două ori.

Pas 1 (gratuit): scor de asemănare între candidat și articolele publicate în ultimele zile,
pe titlu și pe începutul textului (cuvinte fără diacritice, fără cuvinte de legătură),
plus cifrele și numele proprii comune.
Pas 2 (doar pentru cazurile la limită): redactorul-șef (Claude) decide dacă e același eveniment.

Când e duplicat, nu rescriem a doua oară: adăugăm sursa nouă la articolul existent
(`also_reported_by`), ca cititorul să vadă cine a mai relatat.
"""
import re
import unicodedata
from datetime import datetime, timedelta

WINDOW_DAYS = 4
SURE = 0.55       # peste: duplicat sigur, fără apel AI
MAYBE = 0.30      # între MAYBE și SURE: întrebăm redactorul-șef

STOPWORDS = set("""
a al ale alt alta altă am ar are as asa astfel au ca cand când care cat cât ce cea cei cel cele cu cum
da dar de deci din dintre doar dupa după e ea ei el este eu fara fără fi fie fost iar ii îi il îl in în
inca încă insa însă intr într intre între isi își la le li lor lui mai ma mă mi mult ne nici nu o ori
pe pentru peste pana până prin sa să se si și sau sub sunt suntem tot toti toți toate un una unei unui
unor va vor voi vom brasov brașov brasovului brașovului judetul județul judetului județului
""".split())
_WORD = re.compile(r"[a-z0-9]+")
_NUM = re.compile(r"\b\d[\d.,]*\b")
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-ZĂÂÎȘȚ][a-zăâîșț]{2,})")


def fold(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _stem(word):
    # tăiem terminațiile frecvente, ca „primăriei/primăria/primărie” să fie același cuvânt
    return word[:7] if len(word) > 7 else word


def tokens(text):
    return {_stem(w) for w in _WORD.findall(fold(text)) if len(w) > 2 and w not in STOPWORDS}


def fingerprint(article):
    title = article.get("source_title") or article.get("title") or ""
    body = _plain(article.get("content") or article.get("text") or article.get("excerpt") or "")[:600]
    alt_title = article.get("title") if article.get("source_title") else ""
    return {
        "title": tokens(title) | tokens(alt_title),
        "lead": tokens(body),
        "numbers": {n.strip(".,") for n in _NUM.findall(title + " " + body) if len(n.strip(".,")) >= 2},
        "names": {fold(m) for m in _PROPER.findall(title + " " + body)} - STOPWORDS,
    }


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def _overlap(a, b):
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def similarity(fa, fb):
    """0..1. Titlu și început de text, cu un bonus pentru cifre și nume proprii comune."""
    title = _jaccard(fa["title"], fb["title"])
    lead = _overlap(fa["lead"], fb["lead"]) if min(len(fa["lead"]), len(fb["lead"])) >= 8 else 0.0
    score = max(title, 0.6 * title + 0.4 * lead, 0.75 * lead)
    shared_nums = fa["numbers"] & fb["numbers"]
    shared_names = fa["names"] & fb["names"]
    if shared_nums:
        score += 0.08 * min(len(shared_nums), 2)
    if len(shared_names) >= 2:
        score += 0.05
    return min(score, 1.0)


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def recent(articles, now=None, days=WINDOW_DAYS):
    """Articolele publicate în ultimele `days` zile, fără editoriale (ele adună mai multe știri)."""
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    out = []
    for a in articles:
        if a.get("is_editorial") or a.get("category") == "editorial":
            continue
        d = _parse_date(a.get("date") or "")
        if d is None or d.replace(tzinfo=None) >= cutoff:
            out.append(a)
    return out


class Index:
    """Articolele cu care comparăm: cele publicate recent plus cele acceptate în rularea curentă."""

    def __init__(self, articles=()):
        self.items = [(a, fingerprint(a)) for a in articles]

    def add(self, article):
        self.items.append((article, fingerprint(article)))

    def best(self, candidate):
        fc = fingerprint(candidate)
        best, best_score = None, 0.0
        for art, fa in self.items:
            if candidate.get("url") and candidate.get("url") == art.get("url"):
                return art, 1.0
            s = similarity(fc, fa)
            if s > best_score:
                best, best_score = art, s
        return best, best_score


def check(candidate, index, judge=None):
    """('nou' | 'duplicat', articolul existent sau None, scor, motiv).

    `judge(candidate, existing) -> (bool, motiv)` e apelat doar în zona de incertitudine.
    Fără judge, zona de incertitudine e tratată ca știre nouă (preferăm să nu pierdem știri).
    """
    existing, score = index.best(candidate)
    if existing is None or score < MAYBE:
        return "nou", None, score, "fără asemănări"
    if score >= SURE:
        return "duplicat", existing, score, "titlu și text foarte asemănătoare"
    if judge is None:
        return "nou", None, score, "asemănare la limită, fără verificare AI"
    same, reason = judge(candidate, existing)
    return ("duplicat" if same else "nou"), (existing if same else None), score, reason


def merge_source(existing, candidate):
    """Adaugă sursa candidatului la articolul existent. Întoarce True dacă s-a schimbat ceva."""
    url = candidate.get("url") or ""
    if not url or url == existing.get("url"):
        return False
    others = existing.setdefault("also_reported_by", [])
    if any(o.get("url") == url for o in others):
        return False
    others.append({"source": candidate.get("source") or "", "url": url,
                   "title": (candidate.get("title") or "")[:200],
                   "added_at": datetime.now().isoformat(timespec="seconds")})
    return True
