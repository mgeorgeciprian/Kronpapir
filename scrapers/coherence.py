"""Titlul și corpul trebuie să fie despre aceeași știre.

Un selector de conținut prea larg (de exemplu un bloc de articole recomandate) dă un corp care
vorbește despre altceva decât titlul. Măsurăm ce parte din cuvintele titlului (rădăcini, fără
diacritice și fără cuvinte de legătură) apar în corp.
"""
import re
import unicodedata

STOP = set("""si sa se la in din de cu pe un o ca ce mai nu care pentru este sunt fost dupa despre au a al ale
lui iar cum cand unde cat daca dar sau prin spre intre fara pana tot toti toate acest aceasta acum noi vor va
ii isi le il ei ea el ne lor cel cea cei cele unui unei""".split())

STEM = 5
MIN_TITLE_WORDS = 3
THRESHOLD = 0.2
# Sub ~600 de caractere corpul e de obicei doar un extras din RSS, scris cu alte cuvinte decât titlul:
# acolo testul dă alarme false (G4Media, Mediafax), așa că nu judecăm.
MIN_BODY = 600


def _norm(text):
    text = unicodedata.normalize("NFKD", re.sub(r"<[^>]+>", " ", text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def stems(text):
    return {w[:STEM] for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) > 2 and w not in STOP}


def title_overlap(title, body):
    """Fracția rădăcinilor din titlu care apar în corp; None dacă titlul are prea puține cuvinte."""
    ts = stems(title)
    if len(ts) < MIN_TITLE_WORDS:
        return None
    return len(ts & stems(body)) / len(ts)


def is_mismatch(title, body, threshold=THRESHOLD):
    """True când corpul e destul de lung ca să conteze și aproape nu pomenește titlul."""
    if len(re.sub(r"<[^>]+>", " ", body or "").strip()) < MIN_BODY:
        return False
    overlap = title_overlap(title, body)
    return overlap is not None and overlap < threshold
