"""Statisticile lunare ONRC pe județe: înmatriculări, radieri, dizolvări, suspendări, insolvențe, firme active.

Sursa: https://www.onrc.ro/index.php/ro/statistici (date publice, fișiere .xls/.xlsx lunare).
Pentru fiecare indicator luăm cel mai nou fișier, citim foaia pe județe și păstrăm toate județele
(pentru comparații și clasament). Rezultatul: data/business/onrc/AAAA-LL.json, plus latest.json.
Cifrele se copiază exact din fișier; nu calculăm nimic aici în afară de normalizarea numelor.

Rulare: python -m sources.onrc [--dry-run] [--data-dir data]
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sources.http import FetchError, PoliteClient
from sources.xlsx import read_sheets

log = logging.getLogger("sources.onrc")

TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
SITE = "https://www.onrc.ro"
PAGE = SITE + "/index.php/ro/statistici"
STATS = {  # cheie: (id pagină sau None pentru pagina principală, eticheta afișată)
    "inmatriculari": (None, "Înmatriculări"),
    "radieri": (251, "Radieri"),
    "dizolvari": (250, "Dizolvări"),
    "suspendari": (249, "Suspendări"),
    "insolvente": (252, "Intrări în insolvență"),
    "activi": (242, "Profesioniști activi"),
}
STAT_FILES = {  # numele fișierului începe cu (fără diacritice, pentru potrivire)
    "inmatriculari": "inmatriculari de persoane",
    "radieri": "radieri",
    "dizolvari": "dizolvari",
    "suspendari": "suspendari",
    "insolvente": "profesionisti intrati in insolventa",
    "activi": "profesionisti activi",
}
MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
          "septembrie", "octombrie", "noiembrie", "decembrie"]
COUNTY = "Brașov"
_LINK = re.compile(r'href="(/statistici/(\d{4})/([a-z]+)/([^"]+\.xlsx?))"', re.I)
_PERIOD = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})")
_AT = re.compile(r"la\s+(?:data\s+de\s+)?(\d{2})\.(\d{2})\.(\d{4})")
_ASCII = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaissttAAISSTT")
_COMMA = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"})


def ascii_fold(text):
    return text.translate(_ASCII).lower()


def county_name(raw):
    return " ".join(raw.translate(_COMMA).split())


def _int(text):
    text = (text or "").replace(" ", "").replace(".", "") if text and "," not in text else (text or "")
    try:
        return int(float(text))
    except ValueError:
        return None


def find_latest_file(html, stat):
    """Cel mai nou fișier al indicatorului de pe pagină: (an, lună, cale)."""
    want = STAT_FILES[stat]
    best = None
    for path, year, month, name in _LINK.findall(html):
        month = month.lower()
        if month not in MONTHS or not ascii_fold(name).startswith(want):
            continue
        key = (int(year), MONTHS.index(month) + 1)
        if best is None or key > best[:2]:
            best = (*key, path)
    return best


def _groups(header, sub):
    """Grupuri de coloane din rândul de antet: (coloana de start, coloana de final, text)."""
    starts = sorted(header)
    out = []
    for i, col in enumerate(starts):
        end = (starts[i + 1] - 1) if i + 1 < len(starts) else max([col, *sub]) if sub else col
        out.append((col, end, header[col]))
    return out


def _find_header(rows):
    for n in sorted(rows):
        first = ascii_fold(rows[n].get(0, ""))
        if first.startswith("judet"):
            return n
    raise ValueError("Nu găsesc rândul de antet cu „Județ”")


def parse_county_sheet(rows, stat):
    """Foaia pe județe -> (data_sfârșit_perioadă, {județ: {...}})."""
    hdr = _find_header(rows)
    header = {c: t for c, t in rows[hdr].items() if c > 0}
    sub = rows.get(hdr + 1, {})
    if ascii_fold(sub.get(0, "")) not in ("",):
        sub = {}
    columns = {}  # cheie -> index coloană
    forms = {}    # cheie -> {formă: coloană}
    period_end = None
    for start, end, text in _groups(header, sub):
        subs = {c: sub[c] for c in sub if start <= c <= end}
        if stat == "activi":
            m = _AT.search(text)
            if not m:
                continue
            day = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if not subs:
                columns.setdefault(f"total@{day}", start)
            else:
                for c, label in subs.items():
                    kind = "pf" if ascii_fold(label).startswith("persoane fizice") else \
                        "pj" if ascii_fold(label).startswith("persoane juridice") else None
                    if kind:
                        columns.setdefault(f"{kind}@{day}", c)
            continue
        m = _PERIOD.search(text)
        if not m:
            continue
        d1 = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        d2 = date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
        total_col = next((c for c, label in subs.items() if ascii_fold(label).startswith("total")), None)
        if subs and total_col is None:
            continue  # grup doar pe forme, fără total; totalul vine în altă coloană
        col = total_col if total_col is not None else start
        kinds = []
        if d1.month == 1 and d1.day == 1:
            kinds.append(("ytd", d2))
        if d1.month == d2.month and d1.year == d2.year:
            kinds.append(("month", d2))
        for kind, d in kinds:
            columns.setdefault(f"{kind}@{d}", col)
            if subs and kind == "ytd":
                forms.setdefault(f"{kind}@{d}", {label: c for c, label in subs.items()
                                                 if not ascii_fold(label).startswith("total")})
    dates = sorted({k.split("@")[1] for k in columns})
    if not dates:
        raise ValueError(f"Nu recunosc coloanele pentru {stat}")
    period_end = dates[-1]
    prev_year = str(int(period_end[:4]) - 1) + period_end[4:]
    counties = {}
    for n in sorted(rows):
        if n <= hdr + (1 if sub else 0):
            continue
        name = rows[n].get(0, "")
        if not name or ascii_fold(name).startswith("total"):
            continue
        cells = rows[n]
        entry = {}
        for key, col in columns.items():
            kind, d = key.split("@")
            if d == period_end:
                entry[kind] = _int(cells.get(col))
            elif d == prev_year:
                entry[f"{kind}_prev"] = _int(cells.get(col))
        for key, mapping in forms.items():
            kind, d = key.split("@")
            label = "forms" if d == period_end else "forms_prev" if d == prev_year else None
            if label:
                entry[label] = {f: _int(cells.get(c)) for f, c in mapping.items() if _int(cells.get(c)) is not None}
        if any(v is not None for k, v in entry.items() if not k.startswith("forms")):
            counties[county_name(name)] = entry
    total_row = next((rows[n] for n in sorted(rows) if ascii_fold(rows[n].get(0, "")).startswith("total")), None)
    national = {}
    if total_row:
        for key, col in columns.items():
            kind, d = key.split("@")
            if d == period_end:
                national[kind] = _int(total_row.get(col))
            elif d == prev_year:
                national[f"{kind}_prev"] = _int(total_row.get(col))
    return period_end, counties, national


def fetch_stat(client, stat):
    page_id = STATS[stat][0]
    page = PAGE if page_id is None else f"{PAGE}?id={page_id}"
    html = client.request_bytes(page, accept="text/html").decode("utf-8", "replace")
    latest = find_latest_file(html, stat)
    if not latest:
        raise FetchError(f"Nu găsesc fișierul pentru {stat} pe {page}")
    year, month, path = latest
    url = SITE + quote(path)
    raw = client.request_bytes(url, accept="*/*", max_bytes=3_000_000)
    sheets = read_sheets(raw)
    if not sheets:
        raise ValueError(f"Fișier fără foi: {url}")
    county_sheet = next((rows for name, rows in sheets if "judet" in ascii_fold(name)), sheets[0][1])
    period_end, counties, national = parse_county_sheet(county_sheet, stat)
    return {"period_end": period_end, "file_month": f"{year}-{month:02d}", "source_url": url,
            "page_url": page, "counties": counties, "national": national}


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def out_dir(data_dir=None):
    return Path(data_dir or BASE_DIR / "data") / "business" / "onrc"


def run(data_dir=None, client=None, dry_run=False, now=None):
    now = now or datetime.now(TZ)
    data_root = Path(data_dir or BASE_DIR / "data")
    client = client or PoliteClient(cache_dir=data_root / "cache" / "http", cache_ttl=6 * 3600)
    stats, errors = {}, {}
    for stat in STATS:
        try:
            stats[stat] = fetch_stat(client, stat)
        except (FetchError, ValueError, KeyError) as e:
            log.warning("ONRC %s: %s", stat, e)
            errors[stat] = str(e)
    if not stats:
        raise FetchError("Niciun indicator ONRC nu s-a putut citi")
    # Luna de referință = cea mai frecventă dată de final (indicatorii pot apărea în zile diferite)
    ends = sorted((s["period_end"] for s in stats.values()), reverse=True)
    period_end = max(set(ends), key=lambda d: (ends.count(d), d))
    payload = {"period_end": period_end, "fetched_at": now.isoformat(timespec="seconds"),
               "stats": stats, "errors": errors}
    bv = {k: v["counties"].get(COUNTY) for k, v in stats.items()}
    if dry_run:
        log.info("ONRC %s, Brașov: %s", period_end, json.dumps(bv, ensure_ascii=False)[:600])
        return payload
    folder = out_dir(data_root)
    _write(folder / f"{period_end[:7]}.json", payload)
    _write(folder / "latest.json", payload)
    log.info("ONRC: %d indicatori, perioada până la %s, %d erori, %d cereri",
             len(stats), period_end, len(errors), client.requests_made)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="Statistici ONRC pe județe")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        run(data_dir=args.data_dir, dry_run=args.dry_run)
    except FetchError as e:
        log.error("ONRC a eșuat: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
