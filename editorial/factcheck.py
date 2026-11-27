"""Fact-check, pasul 1: verificări deterministe ale unei rescrieri față de textul sursă.

Blocante (duc la `rejected`): cifre care nu apar în sursă, date de contact (email, telefon).
Avertismente: diacritice cu sedilă (le corectăm automat), titlu SEO prea lung.
Pasul 2 (evaluarea editorială, LLM) e în ai/factcheck_llm.py; decizia finală în decide().
"""
import re
from datetime import datetime

SENSITIVE_CATEGORIES = {"politica", "accidente", "sanatate"}
SUMMARY_MAX_WORDS = 180  # rezumatele de presă: țintă 80–150, toleranță până la 180
WELL_KNOWN = {"112"}  # numărul de urgență: nu e un fapt despre caz
_NUM = re.compile(r"(?<![\w])\d+(?:[.,\s]\d{3})*(?:[.,]\d+)?(?![\w])")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(?:\+?40|0)\s?[237]\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3}(?!\d)")
_SEDILLA = str.maketrans({"ş": "ș", "ţ": "ț", "Ş": "Ș", "Ţ": "Ț"})


def plain(html):
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _norm_number(raw):
    """„1.204” = „1204” = „1 204”; „315,90” = „315.90” -> forme comparabile."""
    s = raw.replace(" ", " ").strip()
    forms = {s}
    compact = s.replace(" ", "")
    forms.add(compact)
    # separator de mii (punct sau virgulă urmat de exact 3 cifre)
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", compact):
        forms.add(re.sub(r"[.,]", "", compact))
    if re.fullmatch(r"\d+,\d+", compact):
        forms.add(compact.replace(",", "."))
    if re.fullmatch(r"\d+\.\d+", compact):
        forms.add(compact.replace(".", ","))
    return {f.rstrip(".,") for f in forms}


def numbers(text):
    out = set()
    for m in _NUM.finditer(text or ""):
        out |= _norm_number(m.group(0))
    return out


def fix_sedilla(article):
    """Înlocuiește ş/ţ cu ș/ț în câmpurile de text. Întoarce câte câmpuri s-au schimbat."""
    changed = 0
    for key in ("title", "seo_title", "content", "excerpt", "meta_description"):
        val = article.get(key)
        if isinstance(val, str):
            fixed = val.translate(_SEDILLA)
            if fixed != val:
                article[key] = fixed
                changed += 1
    return changed


def deterministic(source_text, article, now=None, official=False):
    """{'erori': [...], 'avertismente': [...]} pentru o rescriere, față de textul sursă."""
    now = now or datetime.now()
    src = plain(source_text)
    # documentele oficiale scriu uneori „9, 16 mp” sau „1. 204”: lipim zecimalele/miile despărțite de spațiu
    src_numbers = numbers(re.sub(r"(\d)([.,])\s+(\d)", r"\1\2\3", src)) | numbers(src)
    # în PDF-uri cifra e des lipită de unitate („501lei”, „400kV”): o despărțim doar în textul sursă
    src_numbers |= numbers(re.sub(r"(\d)([^\W\d_])", r"\1 \2", src))
    body = " ".join(plain(article.get(k) or "") for k in ("title", "content", "excerpt"))
    erori, avert = [], []

    allowed_years = {str(now.year), str(now.year - 1), str(now.year + 1)} | WELL_KNOWN
    for m in _NUM.finditer(body):
        raw = m.group(0)
        forms = _norm_number(raw)
        if forms & src_numbers or forms & allowed_years:
            continue
        digits = re.sub(r"\D", "", raw)
        if len(digits) <= 1:  # „3 zile” vs „trei zile”: nu blocăm cifrele mici
            avert.append({"tip": "numar_mic_nesursat", "valoare": raw})
            continue
        ctx = body[max(0, m.start() - 50): m.end() + 50]
        erori.append({"tip": "numar_inexistent", "valoare": raw, "context": ctx})

    src_digits = re.sub(r"\D", "", src)
    for rx, tip in ((_EMAIL, "email"), (_PHONE, "telefon")):
        for m in rx.finditer(body):
            value = m.group(0)
            # sursă oficială: contactele instituției din document (unde se depun propunerile) sunt permise
            in_source = (value.lower() in src.lower()) if tip == "email" else (re.sub(r"\D", "", value)[-9:] in src_digits)
            if official and in_source:
                avert.append({"tip": f"contact_institutional_{tip}", "valoare": value})
            else:
                erori.append({"tip": f"date_personale_{tip}", "valoare": value})

    if article.get("format") == "rezumat":
        words = len(plain(article.get("content") or "").split())
        if words > SUMMARY_MAX_WORDS:
            erori.append({"tip": "rezumat_prea_lung", "valoare": f"{words} de cuvinte",
                          "context": f"limita e {SUMMARY_MAX_WORDS}"})
        if article.get("url") and article["url"] not in (article.get("content") or ""):
            avert.append({"tip": "rezumat_fara_link_in_text"})

    if re.search(r"[şţŞŢ]", body):
        avert.append({"tip": "diacritice_cu_sedila"})
    seo_title = article.get("seo_title") or article.get("title") or ""
    if len(seo_title) > 60:
        avert.append({"tip": "titlu_seo_lung", "valoare": len(seo_title)})
    if not article.get("url"):
        avert.append({"tip": "lipsa_link_sursa"})
    # aceeași eroare o singură dată
    seen, uniq = set(), []
    for e in erori:
        key = (e["tip"], e.get("valoare"))
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return {"erori": uniq, "avertismente": avert}


def feedback(det, llm):
    """Textul pentru o nouă încercare de rescriere: ce trebuie scos."""
    items = [f"cifra „{e['valoare']}” nu apare în sursă" for e in det["erori"] if e["tip"] == "numar_inexistent"]
    items += [f"rezumatul are {e['valoare']}; limita e {SUMMARY_MAX_WORDS}, scurtează-l"
              for e in det["erori"] if e["tip"] == "rezumat_prea_lung"]
    for e in (llm or {}).get("erori_blocante", []):
        items.append(f"„{e.get('valoare', '')}”: {e.get('motiv', '')}")
    return "; ".join(items[:12])


def decide(article, det, llm):
    """Regula redactorului-șef (.claude/agents/redactor-sef.md) pentru o rescriere de presă.

    Întoarce (decizie, motiv): published | draft | rejected.
    - eroare blocantă (deterministă sau găsită de editor): rejected;
    - subiect sensibil (politică, accidente, sănătate, persoane private): draft pentru George;
    - fără evaluare editorială sau scor sub 8: draft;
    - altfel: published (rămâne cu noindex până o verifică George, ca toate rescrierile).
    """
    if det["erori"]:
        e = det["erori"][0]
        return "rejected", f"{e['tip']}: {e.get('valoare', '')}"
    if llm is None:
        return "draft", "fact-check editorial indisponibil"
    if llm.get("erori_blocante"):
        e = llm["erori_blocante"][0]
        return "rejected", f"{e.get('tip', 'eroare')}: {e.get('valoare', '')}"
    category = (article.get("category") or "").lower()
    if llm.get("subiect_sensibil") or category in SENSITIVE_CATEGORIES:
        return "draft", f"subiect sensibil ({llm.get('motiv_sensibil') or category})"
    score = llm.get("scor") or 0
    if score < 8:
        return "draft", f"scor {score} sub 8"
    return "published", f"scor {score}"
