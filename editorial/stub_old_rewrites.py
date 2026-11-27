"""Rescrierile integrale vechi ale articolelor altor publicații devin cioturi scurte cu link la sursă.

Regula 5 din CLAUDE.md: din alte publicații se ia doar un rezumat scurt, cu link. Înainte de 26.11.2026
pipeline-ul rescria integral articolele (mediana ~380 de cuvinte). Textul original nu l-am păstrat, deci
nu putem scrie un rezumat nou verificat; păstrăm doar fraza de descriere pe care o aveam deja
(meta_description sau extrasul), tăiată la cel mult 45 de cuvinte, și linkul spre articolul complet.

- Fără AI, fără cost. URL-urile rămân, noindex rămâne (source_type tot rescriere_veche).
- Înainte de orice modificare, fișierul întreg se copiază în data/backups/rescrieri-lungi-<data>/.
- Se sar: dublurile (duplicate_of), articolele verificate de George, cele deja transformate.

    python -m editorial.stub_old_rewrites            # doar raport
    python -m editorial.stub_old_rewrites --apply    # scrie
"""
import argparse
import gzip
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from editorial import presentation as pres
from editorial import store as editorial_store

BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED = BASE_DIR / "data" / "processed"
BACKUPS = BASE_DIR / "data" / "backups"
MAX_WORDS = 45
MIN_CHARS = 60


def _clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    text = re.sub(r"^Pe scurt\s*", "", text)
    return text.rstrip(".… ").strip() if text.endswith(("...", "…")) else text


# Frazele de SEO din meta_description care trimit la textul lung („Descoperă…”, „Cum ajungem aici…”).
CTA = re.compile(r"^(Descoperă|Află|Citește|Vezi|Iată|Detalii |Analiz[aă] detaliat|Toate detaliile|Cum |Ce |De ce |Care |Unde |Când |Tot ce )", re.I)


def _close_quotes(text):
    """Un bug vechi tăia textul după ghilimelele de deschidere („Carmen); le închidem."""
    if text.count("„") > text.count("”") + text.count('"'):
        text = text.rstrip(".!?… ") + "”"
    return text


def _cut(text, max_words=MAX_WORDS):
    """Fraze întregi până la max_words, fără întrebări și îndemnuri; prima frază lungă se taie la cuvânt."""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZĂÂÎȘȚ„\"])", text)
    kept = [x for x in sentences if not x.rstrip().endswith("?") and not CTA.match(x)]
    sentences = kept or sentences[:1]
    out, words = [], 0
    for s in sentences:
        n = len(s.split())
        if words + n > max_words:
            break
        out.append(s)
        words += n
    if out:
        return " ".join(out)
    return " ".join(text.split()[:max_words]).rstrip(",;:") + "…"


def lead(article):
    """Fraza de descriere: meta_description, apoi extrasul, apoi începutul textului."""
    for field in ("meta_description", "excerpt", "content"):
        text = _clean(article.get(field))
        if len(text) >= MIN_CHARS or (field == "content" and text):
            cut = _close_quotes(_cut(text))
            if not cut.endswith((".", "!", "?", "…")):
                cut += "."
            return cut
    return ""


def needs_stub(article):
    return (isinstance(article, dict)
            and pres.source_type(article) == "rescriere_veche"
            and not article.get("duplicate_of")
            and not pres.is_reviewed(article)
            and not article.get("stubbed_at"))


def stub(article, now):
    """Articolul cu textul lung înlocuit de ciot. Nu modifică dicționarul primit."""
    src = article.get("source") or "sursa originală"
    url = re.sub(r"[?&]utm_[^#]*$", "", article.get("source_url") or article.get("url") or "")
    link = (f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f'{html.escape(src)}</a>') if url else html.escape(src)
    text = lead(article)
    out = dict(article)
    out["content"] = (f"<p>{html.escape(text)}</p>\n"
                      f"<p>Articolul complet a fost publicat de {link}.</p>")
    out["excerpt"] = text
    out["format"] = "rezumat"
    out["stubbed_at"] = now.isoformat(timespec="seconds")
    return out


def _load(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    if path.suffix == ".gz":
        tmp = path.with_name(".tmp-" + path.name)
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    else:
        editorial_store._write_json_atomic(path, data)


def run(apply=False, folder=None, backups=None, now=None):
    now = now or datetime.now()
    folder, backups = Path(folder or PROCESSED), Path(backups or BACKUPS)
    backup_dir = backups / f"rescrieri-lungi-{now:%Y%m%d-%H%M}"
    stats = {"total": 0, "stub": 0, "skipped_reviewed": 0, "words_before": 0, "words_after": 0, "errors": 0}
    for path in sorted(folder.glob("*.json*")):
        try:
            art = _load(path)
        except (ValueError, OSError):
            stats["errors"] += 1
            continue
        if not isinstance(art, dict):
            continue
        stats["total"] += 1
        if pres.source_type(art) == "rescriere_veche" and pres.is_reviewed(art):
            stats["skipped_reviewed"] += 1
        if not needs_stub(art):
            continue
        new = stub(art, now)
        stats["stub"] += 1
        stats["words_before"] += len(_clean(art.get("content")).split())
        stats["words_after"] += len(_clean(new["content"]).split())
        if apply:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_dir / path.name)
            _save(path, new)
    stats["backup_dir"] = str(backup_dir) if apply and stats["stub"] else None
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="scrie modificările (altfel doar raport)")
    args = parser.parse_args(argv)
    print(json.dumps(run(apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
