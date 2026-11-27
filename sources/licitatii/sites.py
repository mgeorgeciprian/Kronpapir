"""Urmărirea paginilor de anunțuri de pe site-urile primăriilor (listă în sites_<județ>.yaml).

Fiecare site are altă structură, așa că nu se parsează conținutul: se citește o singură pagină
pe zi per primărie, se extrag linkurile al căror text sau adresă conține cuvinte legate de
achiziții și se raportează cele nevăzute până acum. Titlul anunțului este textul linkului;
data este ziua în care l-am văzut prima dată. Detaliile se citesc pe site, la link.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Callable, Iterator
from urllib.parse import urljoin, urlsplit

import urllib.robotparser

import requests

from email.utils import parsedate_to_datetime

DOC_EXT = (".pdf", ".doc", ".docx")


def extract_doc_info(*_args, **_kwargs):
    """În KronPapir nu extragem date din documente (ar aduce și telefoane sau e-mailuri personale)."""
    return None
from .normalize import norm_text

log = logging.getLogger(__name__)

USER_AGENT = "KronPapirBot/1.0 (+https://kronpapir.ro/surse)"

# Linkuri reținute: textul sau adresa (normalizate) conține unul dintre acestea...
KEEP = [
    "ACHIZITI", "CERERE DE OFERT", "CERERI DE OFERT", "SOLICITARE DE OFERT", "SOLICITARE OFERT",
    "INVITATIE DE PARTICIPARE", "INVITATIE PARTICIPARE", "ANUNT DE PARTICIPARE", "ANUNT PUBLICITATE",
    "ANUNT DE PUBLICITATE", "ANUNT ACHIZITIE", "OFERTA DE PRET", "OFERTE DE PRET", "CAIET DE SARCINI",
    "DOCUMENTATIE DE ATRIBUIRE", "LICITATIE",
]
# ...și nu este pagina generică de secțiune, un document de raportare, un concurs de angajare,
# o vânzare/concesionare (nu cumpără nimic) sau un rezultat de atribuire.
SKIP = ["ARHIVA", "REGULAMENT", "STRATEGI", "PROGRAM ANUAL", "PROGRAMUL ANUAL", "PLANUL ANUAL",
        "PLAN ANUAL", "PAAP", "RAPORT", "CENTRALIZATOR", "PESTE 5000", "PESTE 5.000", "EXECUTIA CONTRACT",
        "EXECUTIEI CONTRACT", "BILANT", "EXECUTIE BUGETARA", "CONCURS", "RECRUTARE", "VANZARE", "VANZARI",
        "CONCESION", "INCHIRIERE", "ANUNT DE ATRIBUIRE", "ANUNTUL DE ATRIBUIRE", "ATRIBUIREA CONTRACTULUI",
        "REZULTAT", "COMPARTIMENT", "ACHIZITII PUBLICE29", "TRIMESTRUL", "SEMESTRUL", "PROCES VERBAL",
        "PROCES-VERBAL", "PV DESCHIDERE", "DE INTERES PUBLIC", "ANUNTURI DE TRANSPARENTA", "ACASA",
        "COMUNICAT", "DEZBATERE", "BUGET", "PENTRU MEDIU", "AVIZARE", "CAMPANI", "RECAPITULATIE",
        "CONTRACTE DE ACHIZITII", "MAI MULT", "CONSILIUL LOCAL", "CONTACTE", "LANSAREA PROIECTULUI",
        "INCEPEREA PROIECTULUI", "FINALIZAREA PROIECTULUI", "FINALIZARE PROIECT", "PUG",
        "INSTRUCTIUNI PENTRU OFERTANTI", "PROCEDURA PROPRIE ACHIZITII ANEXA", "INCHIRIER", "REGULARIZARE",
        "GEOTEHNIC", "FOND FUNCIAR", "NORMELE PROCEDURALE", "PROCEDURA PROPRIE PENTRU ORGANIZAREA",
        "SELECTIE PARTENERI", "AUTORIZATIEI", "OFERTA CASTIGATOARE", "ANUNT DE INTENTIE"]
# liste periodice de achiziții (rapoarte), nu anunțuri: „Achiziții directe – Trimestrul II – 2025;”
PERIODIC_RE = re.compile(r"^(ACHIZITII DIRECTE|CONTRACTE( DE)? ACHIZITII( PUBLICE)?)\b.*\b20\d{2};?$")
# titluri fără conținut: goale, doar o dată, doar cifre/punctuație, sau prea scurte
EMPTY_TITLE_RE = re.compile(r"^[\W\d]*$|^\d{1,2} \w+ \d{4}$|^(ACHIZITII PUBLICE )?\d{4}$")
SECTION_RE = re.compile(r"^(ANUNTURI )?(ACHIZITII?( PUBLICE)?|ANUNTURI PUBLICE|INFORMATII PUBLICE SI ANUNTURI|"
                        r"ACHIZITII - PROCEDURI PROPRII|ANUNT ACHIZITII PUBLICE|ANUNT ACHIZITIE DIRECTA|"
                        r"ANUNT DE PARTICIPARE|ANUNT DE LICITATIE|CERERE DE OFERTA|CAIET DE SARCINI|ANUNT PARTICIPARE)$")
SKIP_RE = re.compile(r"^(▮\s*)?(ANUNTURI )?(ACHIZITI[EI]( PUBLIC[AE])?|ANUNTURI|LICITATII|CERERI DE OFERT[AE]|E-LICITATIE|VEZI IN PAGINA SEPARATA)$")
MAX_TITLE = 200
# Terenuri: ofertele de vânzare afișate de primării (Legea 17/2014, terenuri agricole extravilane,
# cu drept de preempțiune), licitațiile de vânzare / concesionare / închiriere de terenuri.
LAND_KEEP = ["VANZARE TEREN", "VANZARI TEREN", "VANZAREA TEREN", "VANZARE A TEREN", "OFERTA DE VANZARE",
             "OFERTE DE VANZARE", "OFERTEI DE VANZARE", "LEGEA 17", "LEGII 17", "LEGEA NR. 17", "LEGII NR. 17",
             "EXTRAVILAN", "TEREN AGRICOL", "TERENURI AGRICOLE", "PREEMPT", "CONCESION", "INCHIRIERE TEREN",
             "INCHIRIEREA TEREN", "LICITATIE TEREN", "LICITATIE PUBLICA TEREN", "VANZARE IMOBIL", "VANZAREA IMOBIL"]
LAND_SKIP = ["REGULAMENT", "RAPORT", "CONCURS", "RECRUTARE", "CENTRALIZATOR", "REZULTAT", "PROCES VERBAL",
             "PROCES-VERBAL", "COMUNICAT", "BUGET", "HOTARARE", "HCL "]
# pe o pagină care e deja secțiunea de achiziții, și aceste cuvinte sunt suficiente
KEEP_ON_PROCUREMENT_PAGE = ["ANUNT", "INVITATIE", "OFERT"]
DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})|(20\d{2})-(\d{2})-(\d{2})")


def date_in_text(text: str) -> str | None:
    """Prima dată dd.mm.yyyy sau yyyy-mm-dd din text, ca ISO; None dacă nu există."""
    m = DATE_RE.search(text)
    if not m:
        return None
    if m.group(1):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        y, mo, d = m.group(4), int(m.group(5)), int(m.group(6))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y}-{mo:02d}-{d:02d}"


GENERIC_RE = re.compile(r"^(\[.*\]|DESCARCA\b.*|DOWNLOAD\b.*|CLICK AICI.*|VEZI\b.*|DETALII|CAIET(UL)? DE SARCINI.*|"
                        r"FORMULAR(E|UL)?\b.*|SECTIUNEA .*|FISA DE DATE.*|PV\b.*|PROCES.VERBAL.*|DOCUMENTATI[AE]( DE ATRIBUIRE)?.*|MODEL .*|"
                        r"ANEXA.*|ERATA.*|CLARIFICARI.*|RASPUNS.*|INVITATIE( DE)? PARTICIPARE|ANUNT( DE)? PARTICIPARE|"
                        r"\d+\.? ?(ANUNT|INVITATIE|FISA|FORMULARE|CAIET).*)$")
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
NAV_TAGS = ("nav", "footer")   # <header> e meniu doar în afara unui <article> (în articol e titlul)
VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "track", "base", "param"}
NAV_MARK = re.compile(r"\b(menu|nav|navbar|navigation|sidebar|breadcrumb|footer|header|widget-area)\b")


class _Links(HTMLParser):
    """Linkurile paginii, grupate: fiecare link știe ultimul titlu (h1–h6) și rândul de tabel."""

    def __init__(self):
        super().__init__()
        self.links: list[dict] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._heading_tag: str | None = None
        self._heading: list[str] = []
        self.last_heading = ""
        self._row: int | None = None
        self._rows = 0
        self.row_text: dict[int, list[str]] = {}
        self._open: list[tuple[str, bool]] = []   # (etichetă, e meniu/antet/subsol?) pentru toate etichetele deschise
        self._nav_depth = 0
        self._articles = 0
        self._article: int | None = None      # <article> curent: grupează titlul, imaginea și „Read more”
        self._article_time: str | None = None  # <time datetime> din articolul curent

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        a = dict(attrs)
        marker = f"{a.get('class', '')} {a.get('id', '')} {a.get('role', '')}".lower()
        in_article = any(t == "article" for t, _ in self._open)
        is_nav = (tag in NAV_TAGS or (tag == "header" and not in_article)
                  or (tag not in ("html", "body") and not in_article and bool(NAV_MARK.search(marker))))
        self._open.append((tag, is_nav))
        if is_nav:
            self._nav_depth += 1
        if tag == "article":
            self._articles += 1
            self._article, self._article_time = self._articles, None
        if tag == "time" and a.get("datetime") and (self._article is not None or self._row is not None):
            self._article_time = a["datetime"][:10]
        if tag == "a":
            self._href = a.get("href")
            self._text = []
        elif tag in HEADINGS:
            self._heading_tag, self._heading = tag, []
        elif tag == "tr":
            self._rows += 1
            self._row = self._rows
            self.row_text[self._row] = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
        if self._heading_tag:
            self._heading.append(data)
        if self._row is not None:
            self.row_text[self._row].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip()
            self.links.append({"href": self._href, "text": text, "heading": self.last_heading,
                               "row": self._row, "article": self._article, "nav": self._nav_depth > 0})
            self._href = None
        elif tag in HEADINGS and self._heading_tag:
            self.last_heading = re.sub(r"\s+", " ", "".join(self._heading)).strip()[:MAX_TITLE]
            self._heading_tag = None
        elif tag == "tr":
            self._row = None
        if tag == "article":
            if self._article_time:
                for l in self.links:
                    if l.get("article") == self._article:
                        l["time"] = self._article_time
            self._article = None
        # închidem până la ultima etichetă deschisă cu același nume (HTML-ul real e rar echilibrat)
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                for _, is_nav in self._open[i:]:
                    if is_nav:
                        self._nav_depth -= 1
                del self._open[i:]
                break


def _slug(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].replace("_", " ").replace("-", " ")


def extract_notices(html: str, page_url: str) -> list[tuple[str, str, str | None]]:
    """Doar anunțurile de achiziție (vezi extract_all pentru ambele teme)."""
    return [(u, t, w) for u, t, w, topic in extract_all(html, page_url) if topic == "achizitii"]


def extract_all(html: str, page_url: str) -> list[tuple[str, str, str | None, str]]:
    """[(url absolut, titlu, dată ISO sau None)] pentru linkurile care par anunțuri de achiziție.

    Linkurile se grupează pe rândul de tabel sau, în afara tabelelor, pe titlul (h1–h6) de
    deasupra, când textul lor e generic („Descarcă caiet de sarcini”, „[ Formulare ]”). Un grup
    dă un singur element: titlul e primul link cu text propriu din rând, altfel textul rândului
    sau titlul de deasupra; adresa e a primului link; data, prima găsită în rând/titlu.
    Pe o pagină dedicată achizițiilor („achizitii” în adresă) cuvintele cheie sunt mai permisive.
    """
    parser = _Links()
    try:
        parser.feed(html)
    except Exception:  # HTML stricat: ce s-a parsat până acolo e suficient
        pass
    keep = list(KEEP)
    if "ACHIZITI" in norm_text(urlsplit(page_url).path):
        keep += KEEP_ON_PROCUREMENT_PAGE

    # Același URL apare adesea de două ori (imagine + titlu): păstrăm textul real, nu pe cel gol.
    resolved = []
    for link in parser.links:
        href = link["href"]
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")) or link["nav"]:
            continue
        url = urljoin(page_url, href.strip())
        if urlsplit(url).scheme not in ("http", "https"):
            continue
        resolved.append((url, link))
    best_text: dict[str, str] = {}
    for url, link in resolved:
        if link["text"] and (url not in best_text or GENERIC_RE.match(norm_text(best_text[url]))):
            best_text[url] = link["text"]
    groups: dict = {}
    order: list = []
    skipped_dupes: set[str] = set()
    for url, link in resolved:
        text = link["text"]
        if best_text.get(url) and text != best_text[url]:
            continue  # duplicat fără text (sau cu text generic) al unui link cu titlu real
        if url in skipped_dupes:
            continue
        skipped_dupes.add(url)
        generic = bool(GENERIC_RE.match(norm_text(text))) or len(text) < 8
        if link["row"] is not None:
            key = ("row", link["row"])
        elif link["article"] is not None:
            key = ("article", link["article"])
        elif generic and link["heading"]:
            key = ("heading", link["heading"])
        else:
            key = ("url", url)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"links": [], "heading": link["heading"], "row": link["row"], "time": None}
            order.append(key)
        g["links"].append((url, text, generic))
        if link.get("time"):
            g["time"] = g["time"] or link["time"]

    out, seen_urls, seen_titles = [], set(), set()
    for key in order:
        g = groups[key]
        row_text = re.sub(r"\s+", " ", " ".join(parser.row_text.get(g["row"], []))).strip() if g["row"] else ""
        own = [(u, t) for u, t, generic in g["links"] if not generic]
        if own:
            title_url, title = own[0]
        else:
            title_url = g["links"][0][0]
            context = row_text[:MAX_TITLE] if row_text else g["heading"]
            if not context:
                continue  # atașament fără niciun titlu în jur: nu știm ce e
            title = f"{context} – {g['links'][0][1]}" if g["heading"] and not row_text else context
        if key[0] == "row" and not own:
            # rândul descrie anunțul: scoatem din text atașamentele generice și data
            title = re.sub(r"\s+", " ", row_text).strip()[:MAX_TITLE]
        title = re.sub(r"\s*[–-]\s*$", "", title).strip()   # „Titlu – ” cu atașament fără text
        blob = norm_text(" ".join([title, row_text, g["heading"] if key[0] == "heading" else ""] +
                                  [f"{t} {_slug(u)}" for u, t, _ in g["links"]]))
        title_n = norm_text(title)
        if len(title_n) < 12 or EMPTY_TITLE_RE.match(title_n) or sum(c.isalpha() for c in title_n) < 8:
            continue
        land_blob = norm_text(f"{title} {_slug(title_url)}")
        if any(k in land_blob for k in LAND_KEEP) and not any(k in title_n for k in LAND_SKIP) \
                and not SECTION_RE.match(re.sub(r"^[•☛▮\s]+", "", title_n)) and not LAND_SECTION_RE.match(title_n):
            topic = "terenuri"
        else:
            topic = "achizitii"
            if not any(k in blob for k in keep):
                continue
            if SKIP_RE.match(title_n) or any(k in title_n for k in SKIP):
                continue
            if PERIODIC_RE.match(title_n) or SECTION_RE.match(re.sub(r"^[•☛▮\s]+", "", title_n)):
                continue
        if title_url in seen_urls or title_n in seen_titles:
            continue
        seen_urls.add(title_url)
        seen_titles.add(title_n)
        when = (date_in_text(title) or date_in_text(row_text) or date_in_text(g["heading"] or "")
                or g.get("time"))
        out.append((title_url, title, when, topic))
    return out


LAND_SECTION_RE = re.compile(r"^(OFERTE DE VANZARE TEREN(URI)?( EXTRAVILAN)?|VANZARI TERENURI|TERENURI|CONCESIUNI|CONCESIONARI|"
                             r"INTERES PUBLIC|ANUNTURI|ACASA|CITESTE MAI MULT|READ MORE)$")


def file_date(session: requests.Session, url: str, timeout: float = 15) -> str | None:
    """Data fișierului de la server (antetul Last-Modified), ca ISO; None pentru pagini HTML sau
    servere care nu o trimit. O cerere HEAD, fără descărcarea documentului."""
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        if "html" in (r.headers.get("Content-Type") or "").lower():
            return None
        lm = r.headers.get("Last-Modified")
        return parsedate_to_datetime(lm).strftime("%Y-%m-%d") if lm else None
    except (requests.RequestException, TypeError, ValueError):
        return None


def site_items(site: dict, html: str, today: date, county: str) -> list[dict]:
    page = site["page"]
    name = norm_text(site["name"])
    items = []
    for url, title, when, topic in extract_all(html, page):
        items.append({
            "topic": topic,
            "published": when or today.isoformat(),
            "date_guessed": when is None,
            "id": f"site:{url}",
            "kind": "site_notice",
            "number": None,
            "title": title,
            "authority": name,
            "authority_cif": None,
            "county": norm_text(site.get("county") or county),
            "cpv_code": None,
            "cpv_name": None,
            "value_ron": None,
            "currency": "RON",
            "deadline": None,
            "procedure": "Ofertă / licitație teren (site primărie)" if topic == "terenuri" else "Anunț pe site-ul primăriei",
            "contract_type": None,
            "state": None,
            "source_page": page,
            "url": url,
        })
    return items


class SitesClient:
    def __init__(self, delay: float = 2.0, timeout: float = 30,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep, extract_docs: bool = False):
        self.delay, self.timeout, self.sleep = delay, timeout, sleep
        self.extract_docs = extract_docs
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "ro,en;q=0.5",
        })
        self.failed: list[str] = []
        self.blocked: list[str] = []
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        """robots.txt pentru KronPapirBot; lipsă sau eroare = permis."""
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            lines: list[str] = []
            try:
                r = self.session.get(host + "/robots.txt", timeout=15)
                if r.status_code == 200 and "<html" not in r.text[:500].lower():
                    lines = r.text.splitlines()
            except requests.RequestException:
                pass
            rp.parse(lines)
            self._robots[host] = rp
        return self._robots[host].can_fetch(USER_AGENT, url)

    def fetch(self, url: str) -> str | None:
        if not self.allowed(url):
            log.info("robots.txt nu permite %s", url)
            self.blocked.append(url)
            return None
        try:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            if "html" not in (r.headers.get("Content-Type") or "html"):
                return None
            r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
            return r.text
        except requests.RequestException as exc:
            log.warning("site %s: %s", url, exc)
            return None

    def items(self, sites: list[dict], today: date, county: str,
              known_urls: set[str] | None = None) -> Iterator[dict]:
        """Anunțurile de pe toate site-urile. Pentru linkurile noi fără dată în text se cere data
        fișierului de la server (HEAD); linkurile deja cunoscute (known_urls) nu se mai interoghează."""
        known_urls = known_urls or set()
        for i, site in enumerate(sites):
            pages = [site.get("page")] + list(site.get("more_pages") or [])
            pages = [p for p in pages if p]
            if not pages:
                continue
            if i:
                self.sleep(self.delay)
            collected = []
            for j, page in enumerate(pages):
                if j:
                    self.sleep(self.delay)
                html = self.fetch(page)
                if html is None:
                    if j == 0:
                        self.failed.append(site["name"])
                    continue
                collected += site_items({**site, "page": page}, html, today, county)
            for item in collected:
                if item["date_guessed"] and item["url"] not in known_urls and self.allowed(item["url"]):
                    when = file_date(self.session, item["url"], self.timeout)
                    if when:
                        item["published"], item["date_guessed"], item["date_source"] = when, False, "fișier"
                    self.sleep(min(self.delay, 0.5))
                if (self.extract_docs and item["url"] not in known_urls and item["topic"] == "achizitii"
                        and item["url"].lower().split("?")[0].endswith(DOC_EXT)):
                    info = extract_doc_info(self.session, item["url"], max(self.timeout, 40))
                    if info:
                        item["doc"] = info
                        if info.get("deadline") and not item.get("deadline"):
                            item["deadline"] = info["deadline"]
                        if info.get("value_ron") and not item.get("value_ron"):
                            item["value_ron"] = info["value_ron"]
                        if info.get("cpv") and not item.get("cpv_code"):
                            item["cpv_code"] = info["cpv"][0]
                    self.sleep(min(self.delay, 1.0))
                yield item
