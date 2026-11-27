"""Vânzările ANAF de bunuri (sechestrate / intrate în proprietatea statului), de pe elicitatii.anaf.ro.

Platforma interzice în termeni colectarea automată a conținutului paginilor. De aceea sursa
folosește exclusiv ce publică ea pentru consum automat: sitemap.xml (lista categoriilor) și
fluxurile RSS per categorie (/rss/<etapă>/categorii/<cale>), oferite pe fiecare pagină de
categorie ca opțiune de distribuire. Nu se descarcă pagini de bunuri și nu se preiau imagini.

Un flux are cel mult ~20 de elemente; de aceea se citesc toate categoriile din sitemap,
inclusiv subcategoriile, și se deduplică după guid.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Callable, Iterator

import requests

from .normalize import guess_county

log = logging.getLogger(__name__)

STAGES = ("publicitate", "licitatii")
STAGE_LABELS = {"publicitate": "În publicitate", "licitatii": "Licitație în derulare"}
CATEGORY_RE = re.compile(r"^/(publicitate|licitatii)/categorii/(.+)$")


def category_feeds(sitemap_xml: str) -> list[tuple[str, str]]:
    """[(etapă, cale_categorie)] din sitemap, în ordinea din fișier, fără duplicate."""
    out: list[tuple[str, str]] = []
    seen = set()
    root = ET.fromstring(sitemap_xml)
    for loc in root.iter():
        if not loc.tag.endswith("loc") or not loc.text:
            continue
        path = re.sub(r"^https?://[^/]+", "", loc.text.strip())
        m = CATEGORY_RE.match(path)
        if not m:
            continue
        key = (m.group(1), _real_category_path(m.group(2)))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _real_category_path(path: str) -> str:
    """Sitemap-ul repetă prefixul la fiecare nivel: 'a/a/b/a/b/c' înseamnă categoria 'a/b/c'."""
    segs = path.strip("/").split("/")
    n = len(segs)
    k = int((2 * n) ** 0.5)
    if k * (k + 1) // 2 != n:
        return path
    expected = [segs[:1]]
    pos = 1
    for level in range(2, k + 1):
        group = segs[pos:pos + level]
        if group[:-1] != expected[-1]:
            return path
        expected.append(group)
        pos += level
    return "/".join(expected[-1])


def humanize(slug: str) -> str:
    return slug.replace("-", " ").strip().capitalize()


def parse_feed(xml_text: str, stage: str, category_path: str, base_url: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    parts = category_path.split("/")
    items = []
    for it in root.iter("item"):
        guid = (it.findtext("guid") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not guid:
            guid = link.rsplit("/", 1)[-1].split("-", 1)[0]
        if not guid:
            continue
        title = (it.findtext("title") or "").strip() or "(fără titlu)"
        desc = re.sub(r"\s+", " ", it.findtext("description") or "").strip()
        pub = it.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).strftime("%Y-%m-%dT%H:%M") if pub else None
        except (TypeError, ValueError):
            published = None
        url = link if link.startswith("http") else base_url.rstrip("/") + link
        items.append({
            "id": f"anaf_sale:{guid}",
            "kind": "anaf_sale",
            "number": guid,
            "title": title,
            "description": desc[:700],
            "authority": "ANAF – valorificare bunuri",
            "county": guess_county(title, desc),
            "county_guessed": True,
            "cpv_code": None,
            "cpv_name": None,
            "value_ron": None,
            "currency": "RON",
            "published": published,
            "deadline": None,
            "procedure": STAGE_LABELS.get(stage, stage),
            "stage": stage,
            "category": humanize(parts[0]) if parts else None,
            "subcategory": humanize(parts[1]) if len(parts) > 1 else None,
            "category_path": category_path,
            "state": None,
            "url": url,
        })
    return items


class AnafSalesClient:
    def __init__(self, base_url: str, delay: float = 2.0, timeout: float = 60,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self.timeout = timeout
        self.sleep = sleep
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
            "User-Agent": "KronPapirBot/1.0 (+https://kronpapir.ro/surse; cititor RSS, o rulare pe zi)",
        })

    def _get(self, path: str) -> str:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.session.get(self.base_url + path, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                r.raise_for_status()
                return r.text
            except requests.RequestException as exc:
                last = exc
                self.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"elicitatii.anaf.ro {path} indisponibil: {last}")

    def feeds(self) -> list[tuple[str, str]]:
        return category_feeds(self._get("/sitemap.xml"))

    def items(self) -> Iterator[dict]:
        seen: set[str] = set()
        feeds = self.feeds()
        log.info("elicitatii.anaf.ro: %s fluxuri RSS de categorie", len(feeds))
        # Licitațiile în derulare se citesc după publicitate, ca etapa mai avansată să câștige.
        for stage, path in sorted(feeds, key=lambda f: STAGES.index(f[0])):
            try:
                xml_text = self._get(f"/rss/{stage}/categorii/{path}")
            except RuntimeError as exc:
                log.warning("%s", exc)
                continue
            for item in parse_feed(xml_text, stage, path, self.base_url):
                if item["id"] in seen and item["stage"] == "publicitate":
                    continue
                seen.add(item["id"])
                yield item
            self.sleep(self.delay)
