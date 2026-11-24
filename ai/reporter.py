"""
KronPapir - Agentul Reporter

Scrie știri ORIGINALE din surse primare: comunicatele oficiale ale instituțiilor
din Brașov (Primărie, CJ, IPJ, ISU, Prefectură, ISJ) și date publice (meteo).
Nu rescrie articolele altor publicații.

Flux pentru fiecare document:
  1. descoperă comunicate noi (RSS / autodiscovery / listare)
  2. extrage textul documentului oficial
  3. Claude scrie o știre doar din faptele documentului (sau decide că nu e știre)
  4. verificare de fapte: (a) toate cifrele din articol există în sursă,
     (b) un al doilea apel Claude compară articolul cu sursa
  5. doar articolele care trec verificarea sunt salvate în data/processed/
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

try:
    import feedparser
except ImportError:  # feedparser e folosit și de rss_scraper
    feedparser = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

logger = logging.getLogger("KronPapir.Reporter")

USER_AGENT = "Mozilla/5.0 (compatible; KronPapirBot/1.0; +https://kronpapir.ro)"
CONTENT_SELECTORS = [
    "div.entry-content", "div.post-content", "div.article-content", "div.content-article",
    "div.field--name-body", "div.item-page", "article", "main",
]
MAX_SOURCE_CHARS = 12000
MIN_SOURCE_CHARS = 300

ROMANIAN_RULES = """LIMBA ROMÂNĂ CORECTĂ:
- Diacritice obligatorii (ă, â, î, ș, ț), acord subiect-predicat mereu corect
- Virgulă înainte de "dar", "iar", "însă", "deși"; topică naturală, fără calcuri din engleză"""

WRITER_PROMPT = """Ești reporter la KronPapir.ro, publicație locală din Brașov.
Primești un DOCUMENT OFICIAL publicat de {institution}. Scrie o știre ORIGINALĂ pe baza lui.

REGULI STRICTE:
1. Folosește DOAR faptele din document. Nu adăuga nume, cifre, date, locuri, citate sau context
   care nu apar în document. Dacă un detaliu lipsește, nu-l inventa.
2. Atribuie clar sursa în text ("potrivit {institution}", "a anunțat {institution}").
3. Citate directe: maximum unul, scurt, copiat exact din document.
4. Structură de știre: lead cu ce/cine/unde/când, apoi detalii, apoi ce urmează pentru cititori
   (termene, program, ce trebuie să facă oamenii), doar dacă documentul le spune.
5. Persoane: în cazuri penale nu folosi numele persoanelor private chiar dacă apar; folosește
   vârsta/localitatea. Prezumția de nevinovăție: "suspectat", "cercetat", nu "vinovat".
6. Dacă documentul NU e de interes pentru publicul din Brașov (proceduri interne, anunțuri de
   angajare, documente tehnice fără conținut de știre), răspunde cu {{"skip": true, "reason": "..."}}.
7. Lungime: 200-450 de cuvinte. Ton factual, fără senzaționalism, fără clișee.

{romanian_rules}

DOCUMENT ({source_url}):
Titlu: {doc_title}
Data: {doc_date}
---
{doc_text}
---

Răspunde DOAR cu JSON valid:
{{
  "skip": false,
  "title": "Titlu informativ, max 90 caractere",
  "seo_title": "Titlu SEO max 60 caractere",
  "excerpt": "Rezumat de 1-2 propoziții",
  "content": "Corpul articolului în HTML: <p> pentru paragrafe, <h2> doar dacă e necesar",
  "meta_description": "150-160 caractere",
  "slug": "slug-fara-diacritice",
  "keywords": ["cuvant1", "cuvant2", "cuvant3", "cuvant4"],
  "category": "politica|economie|cultura|sport|sanatate|social|mediu|local"
}}"""

CHECKER_PROMPT = """Ești editor de verificare a faptelor la KronPapir.ro.
Compară ARTICOLUL cu DOCUMENTUL SURSĂ. Găsește orice afirmație din articol care NU e susținută
de document: nume, cifre, date, locuri, cauze, citate, calificative sau concluzii adăugate.
Reformulările fidele sunt în regulă. Atribuirea către instituție e în regulă.

DOCUMENT SURSĂ:
---
{doc_text}
---

ARTICOL:
Titlu: {title}
---
{content}
---

Răspunde DOAR cu JSON valid:
{{"ok": true|false, "problems": ["afirmația nesusținută și de ce"]}}"""

WEATHER_PROMPT = """Ești reporter la KronPapir.ro. Scrie o știre scurtă despre vremea din Brașov
pentru {date_label}, folosind EXCLUSIV datele de mai jos (sursa: Open-Meteo). Nu adăuga cifre
sau fenomene care nu reies din date. Poți da sfaturi practice generale (umbrelă, haine groase)
doar dacă reies direct din date. 120-250 de cuvinte.

{romanian_rules}

DATE:
{data}

Răspunde DOAR cu JSON valid:
{{"title": "...", "seo_title": "...", "excerpt": "...", "content": "<p>...</p>",
  "meta_description": "150-160 caractere", "slug": "vremea-brasov-...", "keywords": ["..."]}}"""

WEATHER_CODES = {
    0: "senin", 1: "predominant senin", 2: "parțial noros", 3: "înnorat", 45: "ceață",
    48: "ceață cu chiciură", 51: "burniță slabă", 53: "burniță", 55: "burniță densă",
    61: "ploaie slabă", 63: "ploaie", 65: "ploaie puternică", 66: "ploaie înghețată slabă",
    67: "ploaie înghețată", 71: "ninsoare slabă", 73: "ninsoare", 75: "ninsoare abundentă",
    77: "grăunțe de zăpadă", 80: "averse slabe", 81: "averse", 82: "averse puternice",
    85: "averse de ninsoare", 86: "averse puternice de ninsoare", 95: "furtună",
    96: "furtună cu grindină", 99: "furtună cu grindină puternică",
}


def _plain(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def _numbers(text: str) -> List[str]:
    """Extrage numerele dintr-un text, normalizate la cifre (fără separatori)."""
    out = []
    for m in re.findall(r"\d[\d.,]*\d|\d", text):
        digits = re.sub(r"\D", "", m)
        if digits:
            out.append(digits)
    return out


def unsupported_numbers(article_text: str, source_text: str, allowed: Optional[set] = None) -> List[str]:
    """Numerele din articol care nu apar în sursă (verificare deterministă)."""
    allowed = allowed or set()
    source_digits = set(_numbers(source_text))
    source_blob = " ".join(source_digits)
    bad = []
    for n in set(_numbers(article_text)):
        if n in allowed or n in source_digits or n in source_blob:
            continue
        bad.append(n)
    return sorted(bad)


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    start, end = text.find("{"), text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


class PrimarySourceFetcher:
    """Descoperă și descarcă documente oficiale noi."""

    def __init__(self, config_path: Path, state_path: Path, timeout: int = 20):
        self.config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        self.state_path = Path(state_path)
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.seen = self._load_seen()

    # --- stare ---
    def _load_seen(self) -> Dict[str, str]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def mark_seen(self, url: str, status: str):
        self.seen[url] = f"{status}:{datetime.now().isoformat(timespec='seconds')}"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.seen, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- HTTP ---
    def _get(self, url: str) -> Optional[str]:
        try:
            r = self.session.get(url, timeout=self.timeout)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
        except Exception as e:
            logger.warning(f"   ⚠️ {url}: {e}")
            return None

    # --- descoperire ---
    def sources(self) -> List[Dict[str, Any]]:
        return [s for s in self.config.get("sources", []) if s.get("enabled", True)]

    def discover(self, source: Dict[str, Any], limit: int = 10) -> List[Dict[str, str]]:
        """Returnează [{url, title, date}] pentru cele mai recente documente ale sursei."""
        feed_url = source.get("feed_url")
        items = self._from_feed(feed_url, limit) if feed_url else []
        if items:
            return items

        page = self._get(source["list_url"])
        if not page:
            return []
        soup = BeautifulSoup(page, "html.parser")

        alt = soup.find("link", attrs={"type": re.compile(r"application/(rss|atom)\+xml")})
        if alt and alt.get("href"):
            items = self._from_feed(urljoin(source["list_url"], alt["href"]), limit)
            if items:
                return items

        pattern = source.get("link_pattern")
        if not pattern:
            return []
        rx = re.compile(pattern)
        host = urlparse(source["list_url"]).netloc
        found, seen_urls = [], set()
        for a in soup.find_all("a", href=True):
            url = urljoin(source["list_url"], a["href"]).split("#")[0]
            title = a.get_text(" ", strip=True)
            if (urlparse(url).netloc != host or url in seen_urls or not rx.search(urlparse(url).path)
                    or len(title) < 20):
                continue
            seen_urls.add(url)
            found.append({"url": url, "title": title, "date": ""})
            if len(found) >= limit:
                break
        return found

    def _from_feed(self, feed_url: str, limit: int) -> List[Dict[str, str]]:
        if not feedparser:
            return []
        raw = self._get(feed_url)
        if not raw:
            return []
        feed = feedparser.parse(raw)
        return [
            {"url": e.get("link", ""), "title": e.get("title", ""),
             "date": e.get("published", e.get("updated", ""))}
            for e in feed.entries[:limit] if e.get("link")
        ]

    # --- extragere ---
    def fetch_document(self, item: Dict[str, str]) -> Optional[Dict[str, str]]:
        html = self._get(item["url"])
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()

        text = ""
        for sel in CONTENT_SELECTORS:
            node = soup.select_one(sel)
            if node:
                text = node.get_text("\n", strip=True)
                if len(text) >= MIN_SOURCE_CHARS:
                    break
        if len(text) < MIN_SOURCE_CHARS:
            text = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < MIN_SOURCE_CHARS:
            return None

        title = item.get("title") or (soup.title.get_text(strip=True) if soup.title else "")
        og = soup.find("meta", property="og:image")
        return {
            "url": item["url"],
            "title": title,
            "date": item.get("date", ""),
            "text": text[:MAX_SOURCE_CHARS],
            "image": og.get("content", "") if og else "",
        }


class ReporterAgent:
    """Scrie și verifică știri originale din documente oficiale."""

    def __init__(self, api_key: Optional[str], model: str, checker_model: Optional[str] = None,
                 rate_limit_delay: float = 1.0):
        self.model = model
        self.checker_model = checker_model or model
        self.rate_limit_delay = rate_limit_delay
        self._last = 0.0
        self.client = Anthropic(api_key=api_key) if (Anthropic and api_key) else None

    def _call(self, prompt: str, model: str, max_tokens: int = 4096) -> Optional[Dict[str, Any]]:
        if not self.client:
            logger.error("❌ Clientul Anthropic nu e disponibil (cheie sau modul lipsă).")
            return None
        wait = self.rate_limit_delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        try:
            msg = self.client.messages.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_json(msg.content[0].text)
        except Exception as e:
            logger.error(f"❌ Eroare API: {e}")
            return None

    # --- verificare ---
    def verify(self, draft: Dict[str, Any], source_text: str, allowed_numbers: set) -> List[str]:
        """Returnează lista de probleme; listă goală = articolul trece."""
        article_text = f"{draft.get('title', '')} {_plain(draft.get('content', ''))} {draft.get('excerpt', '')}"
        problems = [f"cifră absentă din sursă: {n}"
                    for n in unsupported_numbers(article_text, source_text, allowed_numbers)]
        if problems:
            return problems

        check = self._call(CHECKER_PROMPT.format(
            doc_text=source_text, title=draft.get("title", ""), content=_plain(draft.get("content", ""))
        ), self.checker_model, max_tokens=1024)
        if check is None:
            return ["verificarea nu a putut rula"]
        if not check.get("ok"):
            return check.get("problems") or ["verificatorul a respins articolul"]
        return []

    def _finalize(self, draft: Dict[str, Any], source_name: str, source_url: str, image: str,
                  category: str) -> Dict[str, Any]:
        slug = re.sub(r"[^a-z0-9-]", "", (draft.get("slug") or "").lower().replace(" ", "-")).strip("-")
        if not slug:
            slug = f"stire-{uuid.uuid4().hex[:8]}"
        return {
            "id": str(uuid.uuid4()),
            "title": draft["title"],
            "seo_title": draft.get("seo_title") or draft["title"][:60],
            "content": draft["content"],
            "excerpt": _plain(draft.get("excerpt", ""))[:200],
            "meta_description": draft.get("meta_description", ""),
            "slug": slug,
            "keywords": draft.get("keywords", []),
            "category": (draft.get("category") or category or "local").lower(),
            "type": "local",
            "source": source_name,
            "url": source_url,
            "image": image or "",
            "date": datetime.now().isoformat(),
            "author": "Redacția KronPapir",
            "processed": True,
            "original": True,
            "ai_generated": True,
            "generated_by": "reporter",
        }

    # --- scriere ---
    def write_from_document(self, doc: Dict[str, str], source: Dict[str, Any]) -> Dict[str, Any]:
        """Returnează {'status': 'published'|'skipped'|'rejected'|'error', 'article'?, 'reason'?}."""
        draft = self._call(WRITER_PROMPT.format(
            institution=source["name"], source_url=doc["url"], doc_title=doc["title"],
            doc_date=doc["date"] or "nespecificată", doc_text=doc["text"],
            romanian_rules=ROMANIAN_RULES,
        ), self.model)
        if draft is None:
            return {"status": "error", "reason": "răspuns invalid de la model"}
        if draft.get("skip"):
            return {"status": "skipped", "reason": draft.get("reason", "")}
        if not draft.get("title") or not draft.get("content"):
            return {"status": "error", "reason": "câmpuri lipsă"}

        # anul curent și data documentului pot apărea legitim în text
        allowed = {str(datetime.now().year)} | set(_numbers(doc["title"] + " " + doc["date"]))
        problems = self.verify(draft, doc["title"] + "\n" + doc["text"], allowed)
        if problems:
            return {"status": "rejected", "reason": "; ".join(problems)[:500]}

        article = self._finalize(draft, source["name"], doc["url"], doc.get("image", ""),
                                 source.get("category", "local"))
        return {"status": "published", "article": article}

    def write_weather(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={cfg['latitude']}&longitude={cfg['longitude']}"
               "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
               "precipitation_probability_max,wind_speed_10m_max"
               "&timezone=Europe%2FBucharest&forecast_days=1")
        try:
            d = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT}).json()["daily"]
        except Exception as e:
            return {"status": "error", "reason": f"Open-Meteo: {e}"}

        day = datetime.strptime(d["time"][0], "%Y-%m-%d")
        luni = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie",
                "august", "septembrie", "octombrie", "noiembrie", "decembrie"]
        zile = ["luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică"]
        date_label = f"{zile[day.weekday()]}, {day.day} {luni[day.month - 1]} {day.year}"
        data_lines = (
            f"Data: {date_label}\n"
            f"Fenomen dominant: {WEATHER_CODES.get(d['weather_code'][0], 'variabil')}\n"
            f"Temperatura minimă: {round(d['temperature_2m_min'][0])} °C\n"
            f"Temperatura maximă: {round(d['temperature_2m_max'][0])} °C\n"
            f"Precipitații totale: {d['precipitation_sum'][0]} mm\n"
            f"Probabilitate maximă de precipitații: {d['precipitation_probability_max'][0]}%\n"
            f"Vânt maxim: {round(d['wind_speed_10m_max'][0])} km/h"
        )
        draft = self._call(WEATHER_PROMPT.format(date_label=date_label, data=data_lines,
                                                 romanian_rules=ROMANIAN_RULES), self.model, 2048)
        if not draft or not draft.get("content"):
            return {"status": "error", "reason": "răspuns invalid de la model"}

        article_text = f"{draft.get('title', '')} {_plain(draft['content'])} {draft.get('excerpt', '')}"
        bad = unsupported_numbers(article_text, data_lines)
        if bad:
            return {"status": "rejected", "reason": f"cifre absente din date: {bad}"}

        draft.setdefault("slug", f"vremea-brasov-{d['time'][0]}")
        draft["category"] = "mediu"
        article = self._finalize(draft, "Open-Meteo", "https://open-meteo.com/", "", "mediu")
        article["slug"] = f"vremea-brasov-{d['time'][0]}"
        return {"status": "published", "article": article}


def run_reporter(base_dir: Path, api_key: str, model: str, checker_model: Optional[str] = None,
                 max_articles: int = 5, per_source: int = 3, include_weather: bool = True,
                 dry_run: bool = False) -> Dict[str, Any]:
    """Rulează reporterul o dată. Salvează articolele publicate în data/processed/."""
    processed_dir = base_dir / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    fetcher = PrimarySourceFetcher(base_dir / "config" / "primary_sources.yaml",
                                   base_dir / "data" / "reporter_seen.json")
    agent = ReporterAgent(api_key, model, checker_model)
    stats = {"published": 0, "skipped": 0, "rejected": 0, "error": 0, "slugs": []}

    def save(article: Dict[str, Any]):
        if dry_run:
            logger.info(f"   [dry-run] {article['title']}")
            return
        (processed_dir / f"{article['id']}.json").write_text(
            json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["slugs"].append(article["slug"])

    weather_cfg = (fetcher.config.get("data_reports") or {}).get("weather") or {}
    weather_key = f"weather:{datetime.now():%Y-%m-%d}"
    if include_weather and weather_cfg.get("enabled") and weather_key not in fetcher.seen:
        res = agent.write_weather(weather_cfg)
        stats[res["status"]] += 1
        if res["status"] == "published":
            save(res["article"])
        else:
            logger.warning(f"   ⚠️ Meteo {res['status']}: {res.get('reason', '')}")
        if not dry_run and res["status"] == "published":
            fetcher.mark_seen(weather_key, "published")

    for source in fetcher.sources():
        if stats["published"] >= max_articles:
            break
        logger.info(f"🔎 {source['name']}")
        new_items = [i for i in fetcher.discover(source) if i["url"] not in fetcher.seen][:per_source]
        for item in new_items:
            if stats["published"] >= max_articles:
                break
            doc = fetcher.fetch_document(item)
            if not doc:
                if not dry_run:
                    fetcher.mark_seen(item["url"], "unreadable")
                continue
            res = agent.write_from_document(doc, source)
            stats[res["status"]] += 1
            if res["status"] == "published":
                save(res["article"])
                logger.info(f"   ✅ {res['article']['title'][:70]}")
            else:
                logger.info(f"   ↷ {res['status']}: {item['title'][:50]} — {res.get('reason', '')[:120]}")
            # erorile (API etc.) se reîncearcă la rularea următoare
            if not dry_run and res["status"] != "error":
                fetcher.mark_seen(item["url"], res["status"])

    return stats


def check_sources(base_dir: Path) -> List[Dict[str, Any]]:
    """Verifică fiecare sursă: câte documente găsește și dacă primul se poate citi."""
    fetcher = PrimarySourceFetcher(base_dir / "config" / "primary_sources.yaml",
                                   base_dir / "data" / "reporter_seen.json")
    report = []
    for source in fetcher.config.get("sources", []):
        items = fetcher.discover(source, limit=5)
        doc = fetcher.fetch_document(items[0]) if items else None
        report.append({
            "id": source["id"], "enabled": source.get("enabled", True), "found": len(items),
            "readable": bool(doc), "chars": len(doc["text"]) if doc else 0,
            "example": items[0]["url"] if items else "",
        })
    return report
