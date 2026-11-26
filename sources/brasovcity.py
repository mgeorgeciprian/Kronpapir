"""Documente oficiale ale Primăriei Brașov: proiecte de HCL în dezbatere publică, licitații, achiziții.

Surse (pagini publice, fără captcha; registrul HCL cu captcha NU îl folosim):
- https://www.brasovcity.ro/consiliul-local/proiecte-de-hotarare-dezbatere-publica
  (fiecare proiect: data, starea, titlul, PDF-urile, perioada în care se depun propuneri);
- https://www.brasovcity.ro/primaria/licitatii-publice-vanzare/  (vânzări / închirieri);
- https://www.brasovcity.ro/primaria/achizitii/                  (achiziții, proceduri proprii).

Pentru fiecare document nou și încă deschis (termenul nu a trecut) scriem un articol brut în
data/articles/brasovcity_docs/, cu sursa „Primăria Brașov” (sursă oficială). Pipeline-ul obișnuit
îl rescrie ca articol complet, îl trece prin fact-check și prin verificarea de duplicate.

Date personale: scoatem numele funcționarilor de contact („Punct(e) de contact”, „In atentia”).
Textul PDF-urilor îl extragem cu pdftotext (poppler-utils).

Rulare: python -m sources.brasovcity [--dry-run] [--data-dir data]
"""
import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from sources.http import FetchError, PoliteClient

log = logging.getLogger("sources.brasovcity")

BASE = "https://www.brasovcity.ro"
HCL_URL = f"{BASE}/consiliul-local/proiecte-de-hotarare-dezbatere-publica"
TENDER_PAGES = {
    "licitatie": f"{BASE}/primaria/licitatii-publice-vanzare/",
    "achizitie": f"{BASE}/primaria/achizitii/",
}
SOURCE_NAME = "Primăria Brașov"  # aceeași denumire ca în config/sources.yaml: sursă oficială
TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
MAX_NEW = {"hcl": 3, "licitatie": 2, "achizitie": 2}  # pe rulare (deciziile HCL: tot 3)
MAX_PDFS = 3
MAX_TEXT = 15000
RO_SHORT = {"ian": 1, "feb": 2, "mar": 3, "apr": 4, "mai": 5, "iun": 6, "iul": 7, "aug": 8,
            "sep": 9, "oct": 10, "noi": 11, "dec": 12}
_DATE_NUM = re.compile(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})")
_CONTACT_LINE = re.compile(r"(Punct\(e\) de contact|In atentia|În atenția)\s*:[^\n]*", re.I)


def _abs(href):
    """URL absolut, cu spațiile și diacriticele din cale codate (PDF-urile au spații în nume)."""
    parts = urlsplit(urljoin(BASE, href))
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%")))


def _text(el):
    return re.sub(r"[ \t]+", " ", el.get_text("\n", strip=True)) if el else ""


def parse_short_date(text):
    """„03 Noi 2026” -> date(2026, 11, 3)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-zĂÂÎȘȚăâîșț]{3})[a-zăâîșț]*\.?\s+(\d{4})", text or "")
    if m and m.group(2).lower()[:3] in RO_SHORT:
        return date(int(m.group(3)), RO_SHORT[m.group(2).lower()[:3]], int(m.group(1)))
    return None


def last_date(text):
    """Ultima dată numerică dintr-un text („în perioada 2.11.2026 – 11.11.2026” -> 11.11.2026)."""
    found = [date(int(y), int(mo), int(d)) for d, mo, y in _DATE_NUM.findall(text or "")
             if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31]
    return found[-1] if found else None


def scrub(text):
    return _CONTACT_LINE.sub("", text or "")


# ---------- parsare ----------

def parse_hcl_page(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("article.card"):
        link = card.select_one("h2 a[href]")
        if not link:
            continue
        badges = [b.get_text(" ", strip=True) for b in card.select("span.btn")]
        files = [(a.get_text(" ", strip=True), _abs(a["href"])) for a in card.select("li a[href]")
                 if a["href"].lower().endswith(".pdf")]
        notes = " ".join(p.get_text(" ", strip=True) for p in card.select("p"))
        url = _abs(link["href"])
        items.append({
            "kind": "hcl",
            "id": "hcl-" + url.rstrip("/").rsplit("/", 1)[-1],
            "title": re.sub(r"\s+", " ", link.get_text(" ", strip=True)),
            "url": url,
            "published": parse_short_date(" ".join(badges)),
            "status": next((b for b in badges if not parse_short_date(b)), ""),
            "files": files,
            "notes": notes,
            "deadline": last_date(notes),
        })
    return items


def parse_tender_page(html, kind):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for item in soup.select("div.accordion-item"):
        head = _text(item.select_one(".accordion-header"))
        body_el = item.select_one(".accordion-body")
        link = item.select_one("a[href*='/primaria/anunt-']")
        if not body_el or not link:
            continue
        body = _text(body_el)
        url = _abs(link["href"])
        title = ""
        m = re.search(r"Denumire contract:\s*([^\n]+)", body) or \
            re.search(r"^(Licita[țţ]ia publică privind[^\n]+)", body, re.M)
        if m:
            title = m.group(1)
        else:
            lines = [l for l in body.splitlines() if len(l) > 40 and not l.lower().startswith(("termen", "licita"))]
            title = lines[0] if lines else ""
        if not title:
            title = re.split(r"Vezi în pagină separată", body)[0][:150]
        pub = re.search(r"DATA PUBLICARE\s*:\s*(\d{1,2}\.\d{1,2}\.\d{4})", body)
        items.append({
            "kind": kind,
            "id": f"{kind}-" + url.rstrip("/").rsplit("/", 1)[-1],
            "title": re.sub(r"\s+", " ", title).strip()[:250],
            "url": url,
            "published": last_date(pub.group(1)) if pub else None,
            "status": "expirat" if "expirat" in head.lower() else "deschis",
            "files": [(a.get_text(" ", strip=True), _abs(a["href"])) for a in body_el.select("a[href]")
                      if a["href"].lower().endswith(".pdf")],
            "notes": body,
            "deadline": last_date(head) or last_date(body),
        })
    return items


FRESH_DAYS = 30  # fără termen: îl considerăm deschis doar dacă e publicat de curând


def is_open(item, today):
    if item["status"] == "expirat":
        return False
    if item["kind"] == "hcl" and "dezbatere" not in item["status"].lower():
        return False
    if item["deadline"] is not None:
        return item["deadline"] >= today
    return bool(item["published"]) and (today - item["published"]).days <= FRESH_DAYS


DECIDED = ("aprobat", "respins", "retras")


def decision_change(item, previous):
    """Proiect HCL trecut din „dezbatere publică” într-o decizie (aprobat / respins / retras)."""
    if item["kind"] != "hcl" or not previous:
        return False
    before, now_status = (previous.get("status") or "").lower(), item["status"].lower()
    return "dezbatere" in before and any(w in now_status for w in DECIDED)


# ---------- PDF ----------

def pdf_to_text(raw, timeout=60):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(raw)
        f.flush()
        try:
            out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", f.name, "-"],
                                 capture_output=True, timeout=timeout, check=True)
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            log.warning("pdftotext a eșuat: %s", e)
            return ""
    text = out.stdout.decode("utf-8", "replace")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def pick_pdfs(files):
    """Pentru HCL: anunțul, proiectul și referatul (în ordinea asta); pentru licitații: primele."""
    order = ("anunt", "proiect", "referat")
    ranked = sorted(files, key=lambda f: next((i for i, k in enumerate(order) if k in f[0].lower()), 9))
    return ranked[:MAX_PDFS]


# ---------- articol brut ----------

def build_raw(item, client, now, decided_from=None):
    parts = []
    if decided_from:
        parts.append(f"Actualizare de stare pe brasovcity.ro, constatată pe {now.strftime('%d.%m.%Y')}: "
                     f"proiectul de hotărâre a trecut din „{decided_from}” în „{item['status']}”. "
                     "Pagina nu precizează data ședinței sau numărul hotărârii.")
    if item["kind"] == "hcl":
        intro = (f"Proiect de hotărâre a Consiliului Local Brașov, publicat de Primăria Brașov pe "
                 f"{item['published'].strftime('%d.%m.%Y') if item['published'] else '(dată nespecificată)'}. "
                 f"Stare: {item['status']}.")
        parts.append(intro)
        if item["notes"]:
            parts.append("Consultare publică: " + item["notes"])
        for name, url in pick_pdfs(item["files"]):
            try:
                text = pdf_to_text(client.request_bytes(url, accept="application/pdf"))
            except FetchError as e:
                log.warning("Nu pot descărca %s: %s", url, e)
                continue
            if text:
                parts.append(f"=== {name} ===\n{text}")
    else:
        label = "Licitație publică a Primăriei Brașov" if item["kind"] == "licitatie" else "Achiziție a Primăriei Brașov"
        parts.append(f"{label}. Termen: {item['deadline'].strftime('%d.%m.%Y') if item['deadline'] else 'nespecificat'}.")
        parts.append(item["notes"])
    content = scrub("\n\n".join(parts))[:MAX_TEXT]
    published = item["published"] or now.date()
    key = item["url"] + (f"#{item['status']}" if decided_from else "")
    return {
        "id": hashlib.sha1(key.encode()).hexdigest(),
        "title": (f"{item['status']}: " if decided_from else "") + item["title"],
        "content": content,
        "text": content,
        "source": SOURCE_NAME,
        "url": item["url"],
        "date": (now if decided_from else datetime.combine(published, datetime.min.time())).isoformat(),
        "relevant_until": item["deadline"].isoformat() if item["deadline"] else None,
        "category": "local",
        "source_category": "local",
        "doc_type": "hcl_decizie" if decided_from else item["kind"],
        "files": [{"name": n, "url": u} for n, u in item["files"]][:20],
        "collected_at": now.isoformat(timespec="seconds"),
    }


# ---------- rulare ----------

def state_path(data_root):
    return Path(data_root) / "brasovcity" / "state.json"


def load_state(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"seen": {}}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def collect(client):
    items = parse_hcl_page(client.request_bytes(HCL_URL, accept="text/html").decode("utf-8", "replace"))
    for kind, url in TENDER_PAGES.items():
        html = client.request_bytes(url, accept="text/html").decode("utf-8", "replace")
        items += parse_tender_page(html, kind)
    return items


def run(data_dir=None, client=None, dry_run=False, now=None):
    now = now or datetime.now(TZ).replace(tzinfo=None)
    data_root = Path(data_dir or BASE_DIR / "data")
    client = client or PoliteClient(cache_dir=data_root / "cache" / "http", cache_ttl=1800)
    state = load_state(state_path(data_root))
    baseline = not state["seen"]  # prima rulare: reținem stările, nu anunțăm decizii vechi
    items = collect(client)
    stats = {"gasite": len(items), "deschise": 0, "noi": 0, "salvate": 0, "decizii": 0}
    counts = {}
    out_dir = data_root / "articles" / "brasovcity_docs"
    for item in items:
        prev = state["seen"].get(item["id"])
        if not baseline and decision_change(item, prev) and counts.get("decizie", 0) < MAX_NEW["hcl"]:
            counts["decizie"] = counts.get("decizie", 0) + 1
            if dry_run:
                log.info("[decizie] %s -> %s | %s", prev.get("status"), item["status"], item["title"][:80])
            else:
                raw = build_raw(item, client, now, decided_from=prev.get("status"))
                _write(out_dir / f"{raw['id']}.json", raw)
                prev["status"] = item["status"]
                stats["decizii"] += 1
            continue
        if prev is not None and item["kind"] == "hcl":
            prev["status"] = item["status"]
        if not is_open(item, now.date()):
            if prev is None and not dry_run:
                state["seen"][item["id"]] = {"title": item["title"][:120], "status": item["status"],
                                             "first_seen": now.isoformat(timespec="seconds")}
            continue
        stats["deschise"] += 1
        if item["id"] in state["seen"]:
            continue
        stats["noi"] += 1
        if counts.get(item["kind"], 0) >= MAX_NEW[item["kind"]]:
            continue  # restul la rularea următoare
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        if dry_run:
            log.info("[%s] %s | termen %s", item["kind"], item["title"][:90], item["deadline"])
            continue
        raw = build_raw(item, client, now)
        if len(raw["content"]) < 300:
            log.warning("Prea puțin text pentru %s; îl reîncerc data viitoare.", item["url"])
            continue
        _write(out_dir / f"{raw['id']}.json", raw)
        state["seen"][item["id"]] = {"title": item["title"][:120], "status": item["status"],
                                     "first_seen": now.isoformat(timespec="seconds")}
        stats["salvate"] += 1
    if not dry_run:
        _write(state_path(data_root), state)
    stats["cereri"] = client.requests_made
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Proiecte HCL, licitații și achiziții de pe brasovcity.ro")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        stats = run(data_dir=args.data_dir, dry_run=args.dry_run)
    except FetchError as e:
        log.error("Colectarea brasovcity.ro a eșuat: %s", e)
        return 1
    log.info("brasovcity.ro: %(gasite)d documente, %(deschise)d deschise, %(noi)d noi, "
             "%(salvate)d salvate, %(decizii)d decizii HCL, %(cereri)d cereri", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
