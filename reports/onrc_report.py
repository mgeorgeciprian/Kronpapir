"""Raport lunar: firmele din județul Brașov, din statisticile ONRC colectate de sources/onrc.py.

Fără LLM: cifrele se copiază din data/business/onrc/latest.json, variațiile se calculează aici,
iar textul e un șablon. Înainte de publicare, o verificare deterministă confirmă că fiecare număr
din articol este o cifră ONRC sau o variație calculată din ele. Articolul e de date oficiale, deci
se publică automat (CLAUDE.md, regula 3), cu semnătura „Generat automat … din date oficiale”.
Un raport deja publicat pentru aceeași lună nu se suprascrie.

Rulare: python -m reports.onrc_report [--dry-run] [--data-dir data]
"""
import argparse
import json
import logging
import re
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from editorial import store as editorial_store
from editorial.factcheck import _NUM, _norm_number
from web.business import (COUNTY, HUB_PATH, active, fmt_int, fmt_pct, forms, indicators,
                          pct_change, peers, period_label, rank)

log = logging.getLogger("reports.onrc")

TZ = ZoneInfo("Europe/Bucharest")
BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_NAME = "ONRC"
SOURCE_URL = "https://www.onrc.ro/index.php/ro/statistici"
NOTABLE = 15.0  # o variație de peste 15% merită titlul


def report_id(period_end):
    return f"onrc-raport-{period_end[:7]}"


def num(n, noun):
    """„169 de firme”, dar „115 firme” și „12 firme” (româna cere „de” de la 20 în sus, cu excepția 01–19)."""
    if n is None:
        return f"– {noun}"
    return f"{fmt_int(n)} {noun}" if (n % 100 < 20 and n % 100 != 0) or n < 20 else f"{fmt_int(n)} de {noun}"


def _row(rows, key):
    return next((r for r in rows if r["key"] == key), None)


def _more_less(p, more="mai multe", less="mai puține"):
    return more if p > 0 else less


def _cmp(p, what, year, more="mai multe", less="mai puține"):
    """„cu 20,2% mai puține decât în 2025” / „la fel ca în 2025”."""
    if p is None:
        return ""
    if p == 0:
        return f"la fel ca în {year}"
    return f"cu {fmt_pct(p, sign=False)} {_more_less(p, more, less)} {what}decât în {year}"


def headline(rows, ytd):
    ins, reg = _row(rows, "insolvente"), _row(rows, "inmatriculari")
    if ins and ins["change"] is not None and abs(ins["change"]) >= NOTABLE:
        word = "mai multe" if ins["change"] > 0 else "mai puține"
        return f"Firmele din Brașov, {ytd}: cu {fmt_pct(ins['change'], sign=False)} {word} insolvențe"
    if reg and reg["change"] is not None:
        word = "mai multe" if reg["change"] > 0 else "mai puține"
        return f"Firmele din Brașov, {ytd}: cu {fmt_pct(reg['change'], sign=False)} {word} firme noi"
    return f"Firmele din județul Brașov, {ytd}"


def _table(head, body):
    th = "".join(f"<th>{escape(h)}</th>" for h in head)
    rows = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in body)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>"


def render(payload):
    stats = payload["stats"]
    period_end = payload["period_end"]
    ytd, month = period_label(period_end)
    year = int(period_end[:4])
    prev = year - 1
    rows = indicators(payload)
    act, frm, cmp_rows = active(payload), forms(payload), peers(payload)
    reg, rad, diz, sus, ins = (_row(rows, k) for k in ("inmatriculari", "radieri", "dizolvari", "suspendari", "insolvente"))
    if not reg:
        raise RuntimeError("Lipsesc înmatriculările ONRC pentru Brașov; nu fac raportul.")
    hub = f'<a href="{HUB_PATH}">Afaceri în Brașov</a>'
    src = f'<a href="{SOURCE_URL}" rel="noopener" target="_blank">statisticile ONRC</a>'
    p = []

    lead = (f"<p>În județul Brașov s-au înmatriculat {num(reg['ytd'], 'firme, PFA-uri și întreprinderi')} "
            f"în {ytd}, {_cmp(reg['change'], '', prev)}, arată {src}.")
    if ins:
        lead += (f" În aceeași perioadă, {num(ins['ytd'], 'profesioniști (firme și PFA-uri)')} au intrat în insolvență, "
                 f"{_cmp(ins['change'], '', prev, 'mai mulți', 'mai puțini')}")
        if ins["national_change"] is not None:
            lead += f" (în toată țara, variația e de {fmt_pct(ins['national_change'])})"
        lead += "."
    p.append(lead + "</p>")

    p.append("<h2>Câte firme noi și de ce fel</h2>")
    reg_rank = rank(stats, "inmatriculari")
    text = f"<p>Doar în {month} s-au înmatriculat {fmt_int(reg['month'])}."
    if reg_rank[0]:
        text += f" Brașovul e pe locul {reg_rank[0]} din {num(reg_rank[1], 'județe')} la înmatriculări, fără București."
    if reg["national_change"] is not None:
        text += f" La nivel național, înmatriculările au o variație de {fmt_pct(reg['national_change'])} față de {prev}."
    p.append(text + "</p>")
    if frm:
        p.append(_table(["Formă", ytd, f"Aceeași perioadă {prev}", "Variație"],
                        [[escape(f["label"]), fmt_int(f["ytd"]), fmt_int(f["ytd_prev"]), fmt_pct(f["change"])] for f in frm]))
        srl = next((f for f in frm if f["form"] == "SRL"), None)
        pfa = next((f for f in frm if f["form"] == "PFA"), None)
        if srl and pfa and srl["change"] is not None and pfa["change"] is not None and (srl["change"] < 0 < pfa["change"]):
            p.append(f"<p>Se înființează mai puține SRL-uri ({fmt_pct(srl['change'])}) și mai multe PFA-uri "
                     f"({fmt_pct(pfa['change'])}). Fișierele ONRC nu spun de ce. Le-am trecut așa cum sunt.</p>")

    p.append("<h2>Câte firme se închid</h2>")
    closing = []
    if rad:
        closing.append(f"{num(rad['ytd'], 'radieri')} (firme șterse definitiv din registru, {fmt_pct(rad['change'])})")
    if diz:
        closing.append(f"{num(diz['ytd'], 'dizolvări')} ({fmt_pct(diz['change'])})")
    if sus:
        closing.append(f"{num(sus['ytd'], 'suspendări de activitate')} ({fmt_pct(sus['change'])})")
    if closing:
        p.append(f"<p>În {ytd}, Registrul Comerțului a înregistrat în județul Brașov " + ", ".join(closing)
                 + f", toate comparate cu aceeași perioadă din {prev}. O firmă dizolvată nu e neapărat "
                 "închisă încă: dizolvarea e primul pas, radierea e ultimul.</p>")
    if ins:
        p.append("<h2>Insolvențele</h2>")
        p.append(f"<p>{num(ins['ytd'], 'profesioniști din județ')} au intrat în insolvență în {ytd}, față de "
                 f"{fmt_int(ins['ytd_prev'])} în aceeași perioadă din {prev} ({fmt_pct(ins['change'])}). "
                 f"Doar în {month} au fost {fmt_int(ins['month'])}. Insolvența nu înseamnă faliment: "
                 "firma poate intra în reorganizare și poate continua să lucreze.</p>")

    if act:
        p.append("<h2>Câte firme active are județul</h2>")
        act_rank = rank(stats, "activi", field="total")
        text = (f"<p>La {period_end[8:10]}.{period_end[5:7]}.{period_end[:4]}, județul Brașov avea "
                f"{num(act['total'], 'profesioniști activi')} ({fmt_pct(act['change'])} într-un an): "
                f"{num(act['pj'], 'persoane juridice')} și {num(act['pf'], 'PFA-uri')}, "
                "întreprinderi individuale și familiale.")
        if act_rank[0]:
            text += f" E locul {act_rank[0]} din {num(act_rank[1], 'județe')}, fără București."
        p.append(text + "</p>")

    if len(cmp_rows) > 1:
        p.append("<h2>Brașovul față de alte județe</h2>")
        p.append(_table(["Județ", f"Înmatriculări {ytd}", "Variație", "Insolvențe", "Variație"],
                        [[escape(r["name"]), fmt_int(r["reg"]), fmt_pct(r["reg_change"]),
                          fmt_int(r["ins"]), fmt_pct(r["ins_change"])] for r in cmp_rows]))

    p.append("<h2>De unde sunt datele</h2>")
    p.append(f"<p>Toate cifrele sunt din {src}, publicate lunar de Oficiul Național al Registrului Comerțului. "
             f"Variațiile procentuale le-am calculat noi, față de aceeași perioadă din {prev}. Clasamentele "
             f"nu includ Bucureștiul. Indicatorii se actualizează lunar pe pagina {hub}, unde găsești și "
             "licitațiile Primăriei Brașov, locurile de muncă AJOFM și știrile economice.</p>")

    title = headline(rows, ytd)
    excerpt = (f"{num(reg['ytd'], 'înmatriculări')}"
               + (f" și {num(ins['ytd'], 'insolvențe')}" if ins else "")
               + f" în județul Brașov în {ytd}, după datele ONRC. Ce firme se deschid, câte se închid "
               "și cum stă Brașovul față de alte județe.")
    return {
        "id": report_id(period_end),
        "title": title,
        "slug": f"firme-judetul-brasov-onrc-{period_end[:7]}",
        "excerpt": excerpt,
        "meta_description": excerpt[:155],
        "content": "\n".join(p),
        "category": "economie",
        "type": "local",
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "url": SOURCE_URL,
        "source_type": "date_oficiale",
        "keywords": ["firme Brașov", "ONRC Brașov", "insolvențe Brașov", "firme noi Brașov", "afaceri Brașov"],
        "date": datetime.now(TZ).isoformat(timespec="seconds"),
        "report_period_end": period_end,
    }


# ---------- verificare ----------

def allowed_numbers(payload):
    """Toate formele numerelor pe care articolul are voie să le conțină."""
    vals = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            vals.add(fmt_int(int(x)))
            vals.add(str(int(x)))
    stats = payload["stats"]
    for s in stats.values():
        walk(s.get("counties"))
        walk(s.get("national"))
        for county in (s.get("counties") or {}).values():
            for a, b in (("ytd", "ytd_prev"), ("total", "total_prev"), ("pf", "pf_prev"), ("pj", "pj_prev")):
                if a in county:
                    vals.add(fmt_pct(pct_change(county.get(a), county.get(b)), sign=False))
            for f, v in (county.get("forms") or {}).items():
                vals.add(fmt_pct(pct_change(v, (county.get("forms_prev") or {}).get(f)), sign=False))
        nat = s.get("national") or {}
        vals.add(fmt_pct(pct_change(nat.get("ytd"), nat.get("ytd_prev")), sign=False))
    pe = payload["period_end"]
    vals |= {pe[:4], str(int(pe[:4]) - 1), pe[8:10], pe[5:7], f"{pe[8:10]}.{pe[5:7]}", f"{pe[8:10]}.{pe[5:7]}.{pe[:4]}"}
    for name in ("inmatriculari", "activi"):
        n = rank(stats, name, field="ytd" if name == "inmatriculari" else "total")
        vals |= {str(n[0]), str(n[1])}
    out = set()
    for v in vals:
        if v and v != "–":
            out |= _norm_number(v.rstrip("%"))
    return out


def verify(article, payload):
    """Numerele din articol care nu vin din date (lista goală = trecut)."""
    allowed = allowed_numbers(payload)
    # „ | ” între celule, ca două numere vecine din tabel să nu fie citite ca unul („108 137”)
    text = " | ".join(re.sub(r"<[^>]+>", " | ", article.get(k) or "") for k in ("title", "excerpt", "content"))
    bad = []
    for m in _NUM.finditer(text):
        if not (_norm_number(m.group(0)) & allowed):
            bad.append(m.group(0))
    return bad


# ---------- rulare ----------

def run(data_dir=None, dry_run=False):
    data_root = Path(data_dir or BASE_DIR / "data")
    path = data_root / "business" / "onrc" / "latest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    article = render(payload)
    bad = verify(article, payload)
    if bad:
        raise RuntimeError(f"Numere care nu vin din datele ONRC: {bad[:10]}; nu public.")
    target = editorial_store.PROCESSED_DIR / f"{article['id']}.json"
    if target.exists() or (editorial_store.DRAFTS_DIR / f"{article['id']}.json").exists():
        log.info("Raportul ONRC pentru %s există deja; nu-l suprascriu.", payload["period_end"][:7])
        return article, False
    if dry_run:
        return article, False
    article["fact_check"] = {"scor": 10, "erori_blocante": [], "recomandari": [],
                             "model": "verificare deterministă (fiecare număr provine din fișierele ONRC)"}
    editorial_store.publish_automatic(article)
    return article, True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raportul lunar ONRC pentru județul Brașov")
    parser.add_argument("--dry-run", action="store_true", help="afișează articolul, nu publică")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        article, saved = run(data_dir=args.data_dir, dry_run=args.dry_run)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        log.error("%s", e)
        return 1
    if args.dry_run:
        print(article["title"])
        print(article["content"])
    log.info("Raport ONRC %s: %s", article["id"], "publicat" if saved else "nepublicat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
