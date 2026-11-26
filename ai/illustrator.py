"""Ilustratorul: schițe în creion (SVG) pentru articolele fără imagine proprie.

Pentru fiecare articol publicat care nu are o imagine pe care avem voie s-o afișăm
(vezi editorial.presentation.safe_image), Claude desenează un SVG original pornind de la
titlu, începutul textului și, opțional, poza din articolul sursă, folosită doar ca să
înțeleagă subiectul. Promptul e în .claude/agents/ilustrator.md; modelul și plafonul
lunar sunt în config/agents.yaml (cheia `ilustrator`).

Desenul se salvează în static/ilustratii/<id>.svg, după o curățare strictă (doar
elementele de desen permise, fără script, linkuri sau imagini externe). Articolul primește
image, image_alt și image_credit = „Ilustrație generată de AI”.

Rulare: python -m ai.illustrator [--limit 10] [--dry-run] [--id <article_id>]
"""
import argparse
import gzip
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from ai import costs
from editorial import presentation as pres
from editorial import stock_photos
from editorial import store as editorial_store

log = logging.getLogger("ai.illustrator")

BASE_DIR = Path(__file__).resolve().parent.parent
AGENT_FILE = BASE_DIR / ".claude" / "agents" / "ilustrator.md"
OUT_DIR = BASE_DIR / "static" / "ilustratii"
PUBLIC_PREFIX = "/static/ilustratii/"
CREDIT = "Ilustrație generată de AI"
AGENT = "ilustrator"

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_SVG_BYTES = 120_000
TEXT_CHARS = 1500

SVG_NS = "http://www.w3.org/2000/svg"
ALLOWED_TAGS = {"svg", "g", "defs", "path", "line", "polyline", "polygon", "rect", "circle", "ellipse",
                "filter", "feTurbulence", "feDisplacementMap", "feGaussianBlur", "title", "desc"}
ALLOWED_ATTRS = {
    "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "d", "points", "fill", "fill-opacity", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
    "stroke-opacity", "stroke-dasharray", "opacity", "transform", "filter", "id",
    "baseFrequency", "numOctaves", "seed", "type", "in", "in2", "scale", "result",
    "xChannelSelector", "yChannelSelector", "stdDeviation", "preserveAspectRatio",
}
_LOCAL_URL = re.compile(r"^url\(#[A-Za-z][\w-]*\)$")

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"svg": {"type": "string"}, "alt": {"type": "string"}},
    "required": ["svg", "alt"],
    "additionalProperties": False,
}


BudgetExceeded = costs.BudgetExceeded


# ---------- configurare ----------

def load_prompt(path=AGENT_FILE):
    """Corpul fișierului de agent, fără antetul YAML (frontmatter)."""
    text = Path(path).read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def load_settings(path=None):
    cfg = costs.settings(AGENT, DEFAULT_MODEL, path)
    cfg["use_source_photo"] = bool(cfg.get("use_source_photo", True))
    cfg["effort"] = cfg.get("effort") or "high"
    return cfg


def check_budget(settings, now):
    costs.check(settings, now)


def record_cost(now, model, usage):
    return costs.record(AGENT, model, usage, now)


# ---------- SVG ----------

def sanitize_svg(svg_text):
    """Păstrează doar desenul. Întoarce SVG curat sau ridică ValueError."""
    if not svg_text or len(svg_text.encode("utf-8")) > MAX_SVG_BYTES:
        raise ValueError("SVG gol sau prea mare")
    if "<!DOCTYPE" in svg_text or "<!ENTITY" in svg_text:
        raise ValueError("SVG cu DOCTYPE/ENTITY")
    try:
        root = ET.fromstring(svg_text.strip())
    except ET.ParseError as e:
        raise ValueError(f"SVG invalid: {e}") from e

    def local(tag):
        return tag.split("}", 1)[1] if tag.startswith("{") else tag

    def clean(el):
        new = ET.Element(f"{{{SVG_NS}}}{local(el.tag)}")
        for k, v in el.attrib.items():
            name = local(k)
            if name not in ALLOWED_ATTRS or k.startswith("{"):
                continue
            if "url(" in v and not _LOCAL_URL.match(v.strip()):
                continue
            new.set(name, v)
        if local(el.tag) in ("title", "desc") and el.text:
            new.text = el.text[:300]
        for child in el:
            if local(child.tag) in ALLOWED_TAGS:
                new.append(clean(child))
        return new

    if local(root.tag) != "svg":
        raise ValueError("Rădăcina nu e <svg>")
    out = clean(root)
    out.set("viewBox", out.get("viewBox") or "0 0 1200 675")
    if sum(1 for _ in out.iter()) < 5:
        raise ValueError("SVG aproape gol")
    ET.register_namespace("", SVG_NS)
    return ET.tostring(out, encoding="unicode")


def add_metadata(svg, alt):
    """<title> și <desc> cu mențiunea AI, la începutul desenului."""
    root = ET.fromstring(svg)
    for el in list(root):
        if el.tag in (f"{{{SVG_NS}}}title", f"{{{SVG_NS}}}desc"):
            root.remove(el)
    title = ET.Element(f"{{{SVG_NS}}}title")
    title.text = alt[:300]
    desc = ET.Element(f"{{{SVG_NS}}}desc")
    desc.text = f"{CREDIT} pentru KronPapir (kronpapir.ro)."
    root.insert(0, desc)
    root.insert(0, title)
    ET.register_namespace("", SVG_NS)
    return ET.tostring(root, encoding="unicode")


# ---------- articole ----------

def _read(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def candidates(limit=None, only_id=None):
    """Articolele publicate de noi (verificate sau din date oficiale) fără imagine proprie, cele mai noi primele.

    Doar fișierele .json (cele arhivate .json.gz sunt vechi și rămân cu desenul generic).
    """
    folder = editorial_store.PROCESSED_DIR
    items = []
    for path in folder.glob("*.json"):
        try:
            art = _read(path)
        except (OSError, ValueError):
            continue
        if not isinstance(art, dict) or not art.get("id") or not art.get("title"):
            continue
        if only_id and art["id"] != only_id:
            continue
        if pres.safe_image(art) or art.get("illustration_failed"):
            continue
        # doar ce publicăm noi (verificat de George sau articol de date oficiale);
        # restul rămâne cu poza ilustrativă din static/images/foto/
        if not (pres.is_reviewed(art) or pres.source_type(art) == "date_oficiale"):
            continue
        if not stock_photos.needs_illustration(art):  # poliție, pompieri...: poza ilustrativă e suficientă
            continue
        items.append((art.get("date") or "", path, art))
    items.sort(key=lambda t: t[0], reverse=True)
    return [(p, a) for _, p, a in (items[:limit] if limit else items)]


def source_photo(article):
    """Poza articolului sursă (alt site), doar ca referință de subiect pentru model."""
    img = article.get("image_original") or article.get("image") or ""
    return img if img.startswith("https://") and pres.is_external_url(img) else None


def build_user_content(article, photo_url):
    text = re.sub(r"<[^>]+>", " ", article.get("content") or "")
    text = re.sub(r"\s+", " ", text).strip()[:TEXT_CHARS]
    brief = (f"Titlu: {article.get('title')}\n"
             f"Categorie: {article.get('category') or 'local'}\n"
             f"Începutul articolului: {text or article.get('excerpt') or '(lipsă)'}\n\n"
             "Desenează ilustrația după regulile tale și întoarce JSON-ul cerut.")
    content = []
    if photo_url:
        content.append({"type": "image", "source": {"type": "url", "url": photo_url}})
        brief = ("Poza de mai sus e din articolul sursă (altă publicație): folosește-o doar ca să "
                 "înțelegi subiectul, nu îi copia compoziția.\n\n" + brief)
    content.append({"type": "text", "text": brief})
    return content


# ---------- Claude ----------

def make_client():
    from anthropic import Anthropic
    return Anthropic()


def draw(client, settings, system_prompt, article, now):
    """Un apel la Claude -> (svg_curat, alt). Ridică ValueError dacă răspunsul nu e folosibil."""
    import anthropic

    photo = source_photo(article) if settings["use_source_photo"] else None
    for attempt_photo in ([photo, None] if photo else [None]):
        try:
            with client.beta.messages.stream(
                model=settings["model"],
                max_tokens=48000,
                system=system_prompt,
                messages=[{"role": "user", "content": build_user_content(article, attempt_photo)}],
                output_config={"effort": settings["effort"],
                               "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                # pe SDK-ul vechi din producție parametrul nu există încă: îl trimitem în corp
                extra_body={"fallbacks": "default"},
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.BadRequestError as e:
            if attempt_photo:  # poza sursă nu se poate descărca (link expirat): încercăm fără ea
                log.info("Poza sursă refuzată (%s); desenez doar din text.", str(e)[:120])
                continue
            raise
        usd, total = record_cost(now, settings["model"], msg.usage)
        log.info("Cost %.4f USD (luna: %.2f USD)", usd, total)
        if msg.stop_reason == "refusal":
            raise ValueError("Modelul a refuzat desenul")
        if msg.stop_reason != "end_turn":
            raise ValueError(f"Răspuns incomplet (stop: {msg.stop_reason})")
        text = next((b.text for b in msg.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ValueError(f"JSON invalid: {e}") from e
        alt = re.sub(r"\s+", " ", str(data.get("alt") or "")).strip()[:250]
        if not alt:
            raise ValueError("Lipsește textul alternativ")
        return add_metadata(sanitize_svg(data.get("svg") or ""), alt), alt
    raise ValueError("Nicio încercare reușită")


def apply_illustration(path, article, svg, alt):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{editorial_store._safe_id(article['id'])}.svg"
    tmp = OUT_DIR / f".tmp-{name}"
    tmp.write_text(svg, encoding="utf-8")
    os.replace(tmp, OUT_DIR / name)
    fresh = _read(path)  # recitim: poate a fost editat între timp din admin
    if fresh.get("image") and fresh.get("image") != PUBLIC_PREFIX + name:
        fresh["image_original"] = fresh["image"]
    fresh.update(image=PUBLIC_PREFIX + name, image_alt=alt, image_credit=CREDIT,
                 illustrated_at=datetime.now().isoformat(timespec="seconds"))
    editorial_store._write_json_atomic(path, fresh)
    return fresh


def mark_failed(path, reason):
    fresh = _read(path)
    fresh["illustration_failed"] = reason[:200]
    editorial_store._write_json_atomic(path, fresh)


def run(limit=10, dry_run=False, only_id=None, client=None, now=None):
    now = now or datetime.now()
    settings = load_settings()
    todo = candidates(limit=limit, only_id=only_id)
    if dry_run:
        for path, art in todo:
            log.info("De ilustrat: %s | %s | poză sursă: %s", art["id"], art["title"][:70], bool(source_photo(art)))
        return {"todo": len(todo), "done": 0, "failed": 0}
    if not todo:
        return {"todo": 0, "done": 0, "failed": 0}
    check_budget(settings, now)
    client = client or make_client()
    system_prompt = load_prompt()
    done = failed = 0
    for path, art in todo:
        check_budget(settings, now)
        try:
            svg, alt = draw(client, settings, system_prompt, art, now)
        except ValueError as e:
            log.warning("Ilustrație eșuată pentru %s: %s", art["id"], e)
            mark_failed(path, str(e))
            failed += 1
            continue
        apply_illustration(path, art, svg, alt)
        log.info("Ilustrat: %s (%s)", art["title"][:70], alt[:80])
        done += 1
    return {"todo": len(todo), "done": done, "failed": failed}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Schițe în creion pentru articolele fără imagine")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="doar listează articolele")
    parser.add_argument("--id", dest="only_id", default=None, help="doar acest articol")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        stats = run(limit=args.limit, dry_run=args.dry_run, only_id=args.only_id)
    except BudgetExceeded as e:
        log.error("%s", e)
        return 2
    log.info("Ilustrator: %(done)d desenate, %(failed)d eșuate, din %(todo)d", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
