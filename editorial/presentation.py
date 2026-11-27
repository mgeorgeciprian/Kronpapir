"""
Cum se afișează un articol: titlul paginii, semnătura, imaginea, indexarea și JSON-LD.

Funcții pure, fără Flask, ca să poată fi testate direct.
"""

import os
import re
from urllib.parse import urlparse

from editorial import stock_photos

SITE_URL = "https://kronpapir.ro"
SITE_NAME = "KronPapir"
DEFAULT_OG_IMAGE = f"{SITE_URL}/static/images/og-image.png"
LOGO_URL = f"{SITE_URL}/static/images/og-image.png"

BYLINE_REVIEWED = "Scris de Redacția AI KronPapir, cu verificare umană"
BYLINE_AUTO_DATA = "Generat automat de Redacția AI KronPapir din date oficiale"
BYLINE_AUTO_PRESS = "Generat automat de Redacția AI KronPapir pe baza informațiilor publicate de"
ORG_AUTHOR_NAME = "Redacția KronPapir"

# Domeniile de pe care avem voie să afișăm imagini (ale noastre).
OWN_IMAGE_HOSTS = {"kronpapir.ro", "www.kronpapir.ro"}

# Semnătura personajului fictiv din editorialele vechi.
_PERSONA_RE = re.compile(
    r"<p[^>]*>(?:\s|<[^>]{1,80}>|[—–-])*Andrei Varga[^<]{0,240}(?:\s|</?[a-z]+[^>]{0,40}>)*?</p>",
    re.IGNORECASE,
)


def noindex_rewrites_enabled() -> bool:
    """Comutator din .env: NOINDEX_REWRITES=false oprește noindex-ul pe rescrieri."""
    return os.getenv("NOINDEX_REWRITES", "true").strip().lower() not in ("0", "false", "no", "off")


def article_url(article: dict) -> str:
    if article.get("slug"):
        return f"{SITE_URL}/stiri/{article['slug']}"
    return f"{SITE_URL}/articol/{article.get('id', '')}"


def is_reviewed(article: dict) -> bool:
    return bool(article.get("reviewed_by")) and bool(article.get("reviewed_at"))


def is_external_url(url: str) -> bool:
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and host not in OWN_IMAGE_HOSTS


def source_type(article: dict) -> str:
    """Tipul conținutului. Articolele vechi nu au câmpul și se deduc."""
    if article.get("source_type"):
        return article["source_type"]
    if article.get("contributor_id"):
        return "colaborator"
    if article.get("is_editorial") or article.get("category") == "editorial":
        return "editorial"
    if is_external_url(article.get("url", "")):
        return "rescriere_veche"
    return "redactie"


def should_noindex(article: dict) -> bool:
    """Ce nu trimitem spre indexare până nu îl verifică George:

    - rescrierile integrale ale articolelor altor publicații;
    - editorialele vechi, publicate automat înainte de regula „editorial = aprobat de George”.
    Editorialele noi trec prin ciorne și primesc reviewed_by/at la publicare, deci se indexează.
    """
    if article.get("duplicate_of"):  # dublură: pagina redirecționează spre articolul păstrat
        return True
    if not noindex_rewrites_enabled():
        return False
    return source_type(article) in ("rescriere_veche", "editorial") and not is_reviewed(article)


def byline(article: dict) -> dict:
    """Semnătura afișată: {'text': ..., 'source_name': ..., 'source_url': ..., 'person': bool}."""
    st = source_type(article)
    if st == "colaborator":
        return {"text": article.get("author") or article.get("contributor_name") or "Colaborator KronPapir",
                "source_name": "", "source_url": "", "person": True}
    if is_reviewed(article):
        return {"text": BYLINE_REVIEWED, "source_name": "", "source_url": "", "person": False}
    if st == "date_oficiale":
        return {"text": BYLINE_AUTO_DATA + ". Sursa:",
                "source_name": article.get("source") or "sursa oficială",
                "source_url": article.get("source_url") or article.get("url", ""), "person": False}
    if st == "rescriere_veche":
        return {"text": BYLINE_AUTO_PRESS,
                "source_name": article.get("source") or "o altă publicație",
                "source_url": article.get("url", ""), "person": False}
    # editoriale vechi și alte texte ale redacției, neverificate
    return {"text": "Redacția AI KronPapir", "source_name": "", "source_url": "", "person": False}


def page_title(article: dict) -> str:
    """Titlul paginii fără brand dublat: «Titlu | KronPapir»."""
    t = (article.get("seo_title") or article.get("title") or SITE_NAME).strip()
    t = t.split(" | ")[0].strip()  # elimină „| Categorie | KronPapir.ro” din seo_title-urile vechi
    t = re.sub(r"\s*[-|–]\s*KronPapir(\.ro)?\s*$", "", t, flags=re.IGNORECASE)
    return f"{t} | {SITE_NAME}"


def safe_image(article: dict):
    """URL-ul imaginii, doar dacă e a noastră. Hotlink-urile și linkurile Pixabay temporare -> None."""
    img = (article or {}).get("image") or ""
    if not img:
        return None
    if img.startswith("/static/") or img.startswith("/media/"):
        return img
    host = (urlparse(img).hostname or "").lower()
    if host in OWN_IMAGE_HOSTS:
        return img
    return None


RO_MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
             "septembrie", "octombrie", "noiembrie", "decembrie"]


def ro_datetime(value: str) -> str:
    """'2026-11-26T16:20:05' -> '26 noiembrie 2026, ora 16:20'."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", str(value or ""))
    if not m:
        return str(value or "")
    y, mo, d, h, mi = m.groups()
    text = f"{int(d)} {RO_MONTHS[int(mo) - 1]} {y}"
    return f"{text}, ora {h}:{mi}" if h else text


def absolute_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return SITE_URL + ("" if path_or_url.startswith("/") else "/") + path_or_url


def stock_photo(article: dict):
    """Poza ilustrativă (Wikimedia Commons) când articolul nu are o imagine proprie; altfel None."""
    if safe_image(article):
        return None
    return stock_photos.choose(article)


def display_image(article: dict):
    """Imaginea afișată: a noastră dacă există, altfel poza ilustrativă potrivită subiectului."""
    img = safe_image(article)
    if img:
        return img
    photo = stock_photos.choose(article)
    return photo["url"] if photo else None


PLACEHOLDERS = {"cultura", "default", "economie", "local", "mediu", "national",
                "politica", "sanatate", "social", "sport"}
PLACEHOLDER_ALIASES = {"culture": "cultura", "international": "national", "evenimente": "local",
                       "accidente": "local", "editorial": "default", "tehnologie": "default"}


def placeholder_image(article: dict, fallback: str = "default") -> str:
    """Calea statică a imaginii de rezervă; o categorie fără desen primește default.svg (nu 404)."""
    cat = str((article or {}).get("category") or fallback).strip().lower()
    cat = PLACEHOLDER_ALIASES.get(cat, cat)
    if cat not in PLACEHOLDERS:
        cat = "default"
    return f"images/placeholders/{cat}.svg"


def og_image(article: dict) -> str:
    img = safe_image(article)
    if img and img.lower().endswith(".svg"):  # Facebook și X nu afișează SVG în previzualizări
        img = None
    if not img:
        photo = stock_photos.choose(article)
        img = photo["url"] if photo else None
    return absolute_url(img) if img else DEFAULT_OG_IMAGE


def clean_content(html: str) -> str:
    """Scoate semnătura personajului fictiv „Andrei Varga” din editorialele vechi (doar la afișare)."""
    if not html:
        return ""
    return _PERSONA_RE.sub("", html)


def _plain(text: str, limit: int = 0) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() if limit else text


def build_jsonld(article: dict, category_label: str = "") -> list:
    """NewsArticle + BreadcrumbList (+ FAQPage dacă articolul are FAQ real). Gata pentru |tojson."""
    url = article_url(article)
    by = byline(article)
    if by["person"]:
        author = {"@type": "Person", "name": by["text"]}
    else:
        author = {"@type": "Organization", "name": ORG_AUTHOR_NAME, "url": SITE_URL}

    news = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": (article.get("title") or "")[:110],
        "description": article.get("meta_description") or _plain(article.get("excerpt") or article.get("content"), 160),
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "datePublished": article.get("date") or "",
        "dateModified": article.get("updated") or article.get("reviewed_at") or article.get("date") or "",
        "inLanguage": "ro-RO",
        "author": author,
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
            "logo": {"@type": "ImageObject", "url": LOGO_URL},
            "publishingPrinciples": SITE_URL + "/politica-editoriala",
        },
        "image": [og_image(article)],
        "wordCount": len(_plain(article.get("content")).split()),
    }
    if category_label:
        news["articleSection"] = category_label
    location = article.get("location")
    if location:
        news["contentLocation"] = {
            "@type": "Place",
            "name": location,
            "address": {"@type": "PostalAddress", "addressLocality": location, "addressCountry": "RO"},
        }
    keywords = article.get("keywords")
    if isinstance(keywords, list) and keywords:
        news["keywords"] = ", ".join(str(k) for k in keywords)
    if article.get("source_url"):
        news["isBasedOn"] = article["source_url"]

    is_national = article.get("type") == "national"
    crumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Acasă", "item": f"{SITE_URL}/"},
            {"@type": "ListItem", "position": 2,
             "name": "Știri Naționale" if is_national else "Știri Locale",
             "item": f"{SITE_URL}/national" if is_national else f"{SITE_URL}/local"},
            {"@type": "ListItem", "position": 3, "name": article.get("title") or "", "item": url},
        ],
    }
    blocks = [news, crumbs]

    faq = [q for q in (article.get("faq") or []) if q.get("q") and q.get("a")]
    if faq:
        blocks.append({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": q["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": q["a"]}}
                for q in faq
            ],
        })
    return blocks
