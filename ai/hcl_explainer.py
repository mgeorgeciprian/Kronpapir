"""Explicațiile „pe înțelesul tuturor” pentru proiectele de hotărâre ale Consiliului Local Brașov.

Pentru fiecare proiect HCL din data/brasovcity/store.json (scris de sources/brasovcity.py):
1. descărcăm documentele de bază (proiectul, referatul de aprobare, raportul de specialitate, prima anexă),
   cu PoliteClient (o cerere la 2 secunde, User-Agent identificabil) și le extragem textul cu pdftotext;
2. explicatorul (prompt: .claude/agents/explicator-hcl.md, model și plafon: config/agents.yaml)
   scrie explicația în format fix (JSON);
3. fact-check: verificarea deterministă (cifrele trebuie să existe în documente, fără date de contact
   personale) și editorul de fact-check (LLM, scor 1–10);
4. decizia (aprobată de George pe 27.11.2026): scor ≥ 8 și fără erori -> publicată automat, cu eticheta
   „explicație generată automat din documentele oficiale”; altfel ciornă, vizibilă doar în
   /admin/explicatii-hcl, unde George o poate publica sau ascunde.

Rezultatele: data/brasovcity/explicatii/<id>.json. Textul PDF-urilor: data/brasovcity/text/<id>.txt.

Rulare: python -m ai.hcl_explainer [--limit 3] [--year 2026] [--id hcl-123] [--dry-run]
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from ai import costs
from editorial import factcheck
from editorial.store import _write_json_atomic
from sources.brasovcity import pdf_to_text, redact_private, scrub, TZ

log = logging.getLogger("ai.hcl_explainer")

AGENT = "explicator-hcl"
DEFAULT_MODEL = "claude-sonnet-5-5"
BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_FILE = BASE_DIR / ".claude" / "agents" / "explicator-hcl.md"
PUBLISH_MIN_SCORE = 8
MAX_ATTEMPTS = 2
PER_DOC_CHARS = 25000
TOTAL_CHARS = 60000
LABEL = "Explicație generată automat de Redacția AI KronPapir din documentele oficiale ale proiectului."

# ordinea documentelor de citit; ce nu se potrivește (planuri, memorii tehnice de zeci de MB) nu descărcăm
_DOC_ORDER = (("proiect", r"proiect|phcl"), ("referat", r"referat"), ("raport", r"raport de specialitate"),
              ("anexa", r"anex|regulament"))
_SKIP = re.compile(r"plan|memoriu|mobilare|ilustrare|reglement|rlu|registru|formular|anun", re.I)
_SIZE = re.compile(r"\[([\d.]+)\s*(KB|MB)\]", re.I)
MAX_PDF_MB = 3.0

ITEMS = {"type": "array", "items": {"type": "string"}}
SCHEMA = {
    "type": "object",
    "properties": {
        "titlu_simplu": {"type": "string"},
        "pe_scurt": {"type": "string"},
        "ce_se_schimba": ITEMS,
        "pe_cine_afecteaza": ITEMS,
        "cifre_cheie": {"type": "array", "items": {
            "type": "object",
            "properties": {"cifra": {"type": "string"}, "ce_inseamna": {"type": "string"}},
            "required": ["cifra", "ce_inseamna"], "additionalProperties": False}},
        "ce_poti_face": {"type": "string"},
        "ce_nu_stim": {"type": "string"},
    },
    "required": ["titlu_simplu", "pe_scurt", "ce_se_schimba", "pe_cine_afecteaza", "cifre_cheie",
                 "ce_poti_face", "ce_nu_stim"],
    "additionalProperties": False,
}


def data_root(data_dir=None):
    return Path(data_dir or BASE_DIR / "data") / "brasovcity"


def explanation_path(root, doc_id):
    return Path(root) / "explicatii" / f"{doc_id}.json"


def load_explanations(root):
    out = {}
    folder = Path(root) / "explicatii"
    for p in folder.glob("*.json") if folder.exists() else []:
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return out


def _size_mb(name):
    m = _SIZE.search(name or "")
    if not m:
        return 0.0
    v = float(m.group(1))
    return v / 1024 if m.group(2).upper() == "KB" else v


def pick_documents(files):
    """Proiectul, referatul, raportul de specialitate și prima anexă (cel mult câte unul din fiecare)."""
    chosen = []
    for key, rx in _DOC_ORDER:
        for f in files:
            name = f["name"]
            if re.search(rx, name, re.I) and not _SKIP.search(name) \
                    and _size_mb(name) <= MAX_PDF_MB and f not in chosen:
                chosen.append(f)
                break
    return chosen


def source_text(item, client, root):
    """Textul documentelor (cu cache pe disc). Fără date de contact ale funcționarilor."""
    cache = Path(root) / "text" / f"{item['id']}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    parts = []
    for f in pick_documents(item.get("files") or []):
        try:
            text = pdf_to_text(client.request_bytes(f["url"], accept="application/pdf"))
        except Exception as e:  # FetchError sau PDF stricat: mergem mai departe cu ce avem
            log.warning("Nu pot citi %s: %s", f["url"], e)
            continue
        if text:
            parts.append(f"=== {f['name']} ===\n{text[:PER_DOC_CHARS]}")
    if parts and item.get("notes"):  # anunțul de pe card: unde și până când se trimit propunerile
        parts.insert(0, f"=== Anunțul de pe brasovcity.ro ===\n{item['notes']}")
    text = scrub("\n\n".join(parts))[:TOTAL_CHARS]
    if text:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return text


def _prompt():
    text = PROMPT_FILE.read_text(encoding="utf-8")
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def as_article(exp, item):
    """Explicația ca „articol”, ca să o putem trece prin aceleași verificări ca rescrierile."""
    body = [exp["pe_scurt"], *exp["ce_se_schimba"], *exp["pe_cine_afecteaza"],
            *(f"{c['cifra']}: {c['ce_inseamna']}" for c in exp["cifre_cheie"]), exp["ce_poti_face"], exp["ce_nu_stim"]]
    return {"title": exp["titlu_simplu"], "excerpt": exp["pe_scurt"],
            "content": "\n".join(f"<p>{b}</p>" for b in body), "url": item["url"]}


class Explainer:
    def __init__(self, client=None, fact_checker=None):
        self.cfg = costs.settings(AGENT, DEFAULT_MODEL)
        self.client = client
        self.fact_checker = fact_checker
        self.system = _prompt()

    def _client(self):
        if self.client is None:
            from anthropic import Anthropic
            self.client = Anthropic()
        return self.client

    def write(self, item, text, feedback=""):
        now = datetime.now()
        costs.check(self.cfg, now)
        user = (f"PROIECT DE HOTĂRÂRE (Consiliul Local Brașov)\nTitlu oficial: {redact_private(item['title'])}\n"
                f"Publicat: {item.get('published') or 'nespecificat'}\n"
                f"Termen pentru propuneri: {item.get('deadline') or 'nespecificat'}\n\n"
                f"DOCUMENTELE OFICIALE:\n{text}")
        if feedback:
            user += f"\n\nCORECTURI CERUTE DE FACT-CHECK (refă explicația fără aceste greșeli): {feedback}"
        msg = self._client().beta.messages.create(
            model=self.cfg["model"],
            max_tokens=16000,
            system=self.system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.cfg.get("effort") or "high",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        )
        costs.record(AGENT, self.cfg["model"], msg.usage, now)
        if msg.stop_reason != "end_turn":
            raise RuntimeError(f"explicația nu s-a terminat (stop: {msg.stop_reason})")
        exp = json.loads(next(b.text for b in msg.content if getattr(b, "type", "") == "text"))
        for key in ("titlu_simplu", "pe_scurt", "ce_poti_face", "ce_nu_stim"):
            exp[key] = exp[key].translate(factcheck._SEDILLA).strip()
        for key in ("ce_se_schimba", "pe_cine_afecteaza"):
            exp[key] = [s.translate(factcheck._SEDILLA).strip() for s in exp[key]][:5]
        exp["cifre_cheie"] = exp["cifre_cheie"][:5]
        return exp

    def explain(self, item, text, now=None):
        """Întoarce înregistrarea finală (cu status published / draft) sau None dacă nu avem text."""
        now = now or datetime.now(TZ).replace(tzinfo=None)
        if len(text) < 500:
            log.warning("Prea puțin text în documentele %s; sar peste.", item["id"])
            return None
        feedback, exp, det, llm = "", None, None, None
        for _ in range(MAX_ATTEMPTS):
            exp = self.write(item, text, feedback)
            art = as_article(exp, item)
            det = factcheck.deterministic(text, art, now, official=True)
            llm = None
            if not det["erori"] and self.fact_checker is not None:
                llm = self.fact_checker.check({"content": text, "source": "Primăria Brașov", "url": item["url"],
                                               "title": item["title"]}, art, source_chars=TOTAL_CHARS)
            if not det["erori"] and llm and not llm.get("erori_blocante") and llm["scor"] >= PUBLISH_MIN_SCORE:
                break
            feedback = factcheck.feedback(det, llm)
            if not feedback:
                break  # nimic concret de corectat (de ex. scor mic): a doua încercare n-ar ajuta
        ok = not det["erori"] and llm is not None and not llm.get("erori_blocante") and llm["scor"] >= PUBLISH_MIN_SCORE
        return {
            "id": item["id"], "url": item["url"], "status": "published" if ok else "draft",
            "explicatie": exp, "label": LABEL,
            "factcheck": {"scor": (llm or {}).get("scor"), "erori": det["erori"],
                          "erori_editor": (llm or {}).get("erori_blocante", []),
                          "subiect_sensibil": (llm or {}).get("subiect_sensibil"),
                          "motiv_sensibil": (llm or {}).get("motiv_sensibil"), "model": (llm or {}).get("model")},
            "model": self.cfg["model"], "status_hcl": item.get("status"),
            "documents": [f["name"] for f in pick_documents(item.get("files") or [])],
            "created_at": now.isoformat(timespec="seconds"),
        }


def candidates(store, done, year=None, only=None):
    """Proiectele HCL fără explicație: întâi cele în dezbatere, apoi cele mai noi."""
    items = [dict(it, id=k) for k, it in (store.get("items") or {}).items() if it.get("kind") == "hcl"]
    if only:
        return [it for it in items if it["id"] == only]
    items = [it for it in items if it["id"] not in done]
    if year:
        items = [it for it in items if (it.get("published") or "")[:4] >= str(year) or "dezbatere" in it["status"].lower()]
    items.sort(key=lambda it: ("dezbatere" not in it["status"].lower(), -int((it.get("published") or "0000-00-00").replace("-", ""))))
    return items


def run(limit=3, year=None, only=None, data_dir=None, client=None, explainer=None, dry_run=False):
    root = data_root(data_dir)
    try:
        store = json.loads((root / "store.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        log.warning("Lipsește %s; rulează întâi python -m sources.brasovcity.", root / "store.json")
        return {"explicate": 0}
    done = load_explanations(root)
    todo = candidates(store, done, year=year, only=only)[:limit]
    if dry_run:
        for it in todo:
            log.info("[de explicat] %s | %s | %s", it["id"], it.get("published"), it["title"][:90])
        return {"de_explicat": len(todo)}
    if client is None:
        from sources.http import PoliteClient
        client = PoliteClient(cache_dir=Path(data_dir or BASE_DIR / "data") / "cache" / "http", cache_ttl=86400)
    if explainer is None:
        from ai.factcheck_llm import FactChecker
        explainer = Explainer(fact_checker=FactChecker())
    stats = {"explicate": 0, "publicate": 0, "ciorne": 0}
    for it in todo:
        try:
            rec = explainer.explain(it, source_text(it, client, root))
        except costs.BudgetExceeded as e:
            log.warning("%s Mă opresc.", e)
            break
        except Exception as e:
            log.warning("Explicația pentru %s a eșuat: %s", it["id"], e)
            continue
        if rec is None:
            continue
        _write_json_atomic(explanation_path(root, it["id"]), rec)
        stats["explicate"] += 1
        stats["publicate" if rec["status"] == "published" else "ciorne"] += 1
        log.info("[%s] scor %s | %s", rec["status"], rec["factcheck"]["scor"], rec["explicatie"]["titlu_simplu"][:80])
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicații pe înțeles pentru proiectele HCL Brașov")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--year", type=int, default=None, help="doar proiectele publicate din acest an (plus cele în dezbatere)")
    parser.add_argument("--id", default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass
    stats = run(limit=args.limit, year=args.year, only=args.id, data_dir=args.data_dir, dry_run=args.dry_run)
    log.info("Explicații HCL: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
