"""Rapoartele de pe /afaceri-brasov, calculate din datele pe care le avem (ONRC, AJOFM, licitații).

Doar numărăm, sortăm și calculăm variații sau mediane; nu estimăm și nu completăm lipsurile.
O lună lipsă din istoric rămâne lipsă (graficul are o bară mai puțin, nu una inventată).
"""
import re
import json
import statistics
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

COUNTY = "Brașov"
FLOW_LABELS = {"inmatriculari": "Înmatriculările", "radieri": "Radierile", "dizolvari": "Dizolvările",
               "suspendari": "Suspendările", "insolvente": "Insolvențele"}
MIN_SERIES = 6  # sub atâtea luni nu desenăm graficul (ar arăta o tendință care nu există)


def de(n):
    """„ de” înaintea substantivului când regula o cere (20 de firme, 3.481 de firme, dar 105 firme)."""
    return " de" if n and (n % 100 >= 20 or (n >= 100 and n % 100 == 0)) else ""


def plural(n, one, many):
    """1 teren, 2 terenuri, 20 de terenuri (regula „de” de la 20 în sus)."""
    if n == 1:
        return f"1 {one}"
    return f"{n}{de(n)} {many}"


def load_history(folder):
    try:
        return json.loads((Path(folder) / "history.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def series(history, stat, county=COUNTY, months=24):
    """[(„AAAA-LL”, valoare)] pentru județ, ultimele `months` luni cu date."""
    pts = [(m, p["counties"].get(county)) for m, p in sorted((history.get(stat) or {}).items())]
    pts = [(m, v) for m, v in pts if v is not None]
    return pts[-months:]


def headline(rows):
    """Fraza de sus: indicatorul care s-a schimbat cel mai mult față de anul trecut.

    rows: rezultatul business.indicators(). Ignoră indicatorii cu valori mici (sub 50 pe an),
    unde o variație mare înseamnă doar câteva cazuri.
    """
    cands = [r for r in rows if r.get("change") is not None and (r.get("ytd_prev") or 0) >= 50]
    if not cands:
        return None
    r = max(cands, key=lambda r: abs(r["change"]))
    return {"key": r["key"], "label": FLOW_LABELS.get(r["key"], r["label"]), "change": r["change"],
            "ytd": r["ytd"], "ytd_prev": r["ytd_prev"], "national_change": r.get("national_change")}


def registrations_per_1000(payload, exclude=("București",), top=10, county=COUNTY):
    """Înmatriculări de la începutul anului la 1.000 de profesioniști activi, pe județe.

    Întoarce primele `top` județe și, dacă nu e între ele, și județul nostru, cu locul lui.
    """
    stats = payload.get("stats") or {}
    reg = (stats.get("inmatriculari") or {}).get("counties") or {}
    act = (stats.get("activi") or {}).get("counties") or {}
    rows = []
    for name, v in reg.items():
        total = (act.get(name) or {}).get("total")
        if name in exclude or not total or v.get("ytd") is None:
            continue
        rows.append({"name": name, "value": round(v["ytd"] * 1000 / total, 1)})
    rows.sort(key=lambda r: -r["value"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    shown = rows[:top]
    mine = next((r for r in rows if r["name"] == county), None)
    if mine and mine not in shown:
        shown.append(mine)
    return {"rows": shown, "mine": mine, "of": len(rows)}


def _median(vals):
    return int(round(statistics.median(vals))) if vals else None


def _company(name):
    """Numele angajatorului din MAJUSCULE AJOFM, scris normal, cu formele juridice tot cu majuscule."""
    if not name.isupper():
        return name
    return re.sub(r"\b(Srl|Sa|Srl-D|Pfa|Ii|If|Snc|Sca|Ong)\b", lambda m: m.group(0).upper(), name.title())


def jobs_report(jobs, today=None, top=6):
    """Ofertele AJOFM active pe domenii, localități și angajatori, plus câteva cifre-cheie.

    Salariile brut și net nu se amestecă: mediana se dă separat, din ofertele care le declară.
    """
    today = today or date.today()
    week_ago = (today - timedelta(days=7)).isoformat()
    by_domain, by_place, by_employer = Counter(), Counter(), Counter()
    brut, net = [], []
    no_exp = new_week = positions = 0
    for j in jobs:
        pos = j.get("positions") or 1
        positions += j.get("positions") or 0
        by_domain[j.get("domain") or "Nespecificat"] += pos
        by_place[j.get("locality") or "Nespecificat"] += pos
        by_employer[(j.get("employer_name") or "").strip() or "Nespecificat"] += pos
        if j.get("salary_min"):
            (brut if j.get("salary_type") == "brut" else net if j.get("salary_type") == "net" else []).append(j["salary_min"])
        if str(j.get("experience") or "").lower().startswith("fără experiență"):
            no_exp += 1
        if str(j.get("date_posted") or "")[:10] >= week_ago:
            new_week += 1
    other = by_domain.pop("Altele", 0)
    domains = by_domain.most_common(top) + ([("Altele", other)] if other else [])
    return {
        "offers": len(jobs), "positions": positions, "no_experience": no_exp, "new_week": new_week,
        "median_brut": _median(brut), "n_brut": len(brut), "median_net": _median(net), "n_net": len(net),
        "domains": domains, "places": by_place.most_common(top),
        "employers": [(_company(e), n) for e, n in by_employer.most_common(top)],
    }


def licitatii_report(groups, top=6):
    """Anunțurile pe localități (cu slug pentru filtrul hărții) și bunurile ANAF pe tipuri."""
    places = Counter()
    names = {}
    for key in ("achizitii", "terenuri", "anaf"):
        for it in groups.get(key, []):
            if it.get("loc"):
                places[it["loc"]] += 1
                names[it["loc"]] = it.get("place") or it["loc"]
    anaf_types = Counter((it.get("subcategory") or it.get("category") or "Altele") for it in groups.get("anaf", []))
    return {"places": [(names[s], n, s) for s, n in places.most_common(top)],
            "anaf_types": anaf_types.most_common(top),
            "total": sum(len(groups.get(k, [])) for k in ("achizitii", "terenuri", "anaf"))}


def _ratio(a, b, per):
    return round(a * per / b, 1) if a is not None and b else None


def health_index(payload, county=COUNTY):
    """Doi indicatori calculați la vedere din ONRC (ian.–luna curentă, față de anul trecut și de țară).

    - insolvențe la 1.000 de înmatriculări;
    - radieri la 100 de înmatriculări (fără dizolvări: multe firme dizolvate sunt radiate apoi, s-ar număra de două ori).
    Starea: „rau” dacă județul e peste media națională sau a crescut cu peste 20% față de anul trecut;
    „stabil” dacă variația e sub ±3%; altfel „bine” (scade) sau „atentie” (crește puțin).
    """
    stats = payload.get("stats") or {}

    def get(stat, who):
        s = stats.get(stat) or {}
        return (s.get("counties") or {}).get(county) if who == "county" else s.get("national")

    out = []
    for key, stat, per, label, unit in (("insolvente", "insolvente", 1000, "Insolvențe la 1.000 de firme noi", "la 1.000"),
                                         ("radieri", "radieri", 100, "Radieri la 100 de firme noi", "la 100")):
        c, r = get(stat, "county") or {}, get("inmatriculari", "county") or {}
        n, rn = get(stat, "nat") or {}, get("inmatriculari", "nat") or {}
        cur = _ratio(c.get("ytd"), r.get("ytd"), per)
        prev = _ratio(c.get("ytd_prev"), r.get("ytd_prev"), per)
        nat = _ratio(n.get("ytd"), rn.get("ytd"), per)
        if cur is None:
            continue
        change = round((cur - prev) * 100 / prev, 1) if prev else None
        if (nat is not None and cur > nat) or (change is not None and change > 20):
            state = "rau"
        elif change is not None and abs(change) < 3:
            state = "stabil"
        elif change is not None and change < 0:
            state = "bine"
        else:
            state = "atentie"
        out.append({"key": key, "label": label, "unit": unit, "value": cur, "prev": prev, "national": nat,
                    "change": change, "state": state,
                    "formula": f"{c.get('ytd')} {'insolvențe' if stat == 'insolvente' else 'radieri'} / {r.get('ytd')} înmatriculări × {per}"})
    return out


def _pct(p):
    return f"{'+' if p > 0 else '−' if p < 0 else ''}{abs(round(p)):.0f}%"


def _cap(s):
    return s[:1].upper() + s[1:]


def _n(v):
    return f"{v:,}".replace(",", ".")


def hero(rows):
    """Deschideri față de închideri (radieri) de la începutul anului: cifrele mari din capul paginii."""
    by = {r["key"]: r for r in rows or []}
    reg, rad = by.get("inmatriculari") or {}, by.get("radieri") or {}
    opened, closed = reg.get("ytd"), rad.get("ytd")
    if not opened or closed is None:
        return None
    per10 = round(closed * 10 / opened)
    return {"opened": opened, "closed": closed, "per10": per10,
            "closed_pct": min(100, round(closed * 100 / opened)),
            "opened_change": reg.get("change"), "closed_change": rad.get("change"),
            "net": opened - closed}


def insights(rows, forms, rank1000):
    """Cel mult trei constatări, fiecare cu cifra ei din ONRC. Doar comparații, fără estimări.

    tone: „rau” (veste proastă), „bine”, „info”. Constatările fără date sau cu variații mici nu apar.
    """
    out = []
    by = {r["key"]: r for r in rows or []}
    ins = by.get("insolvente") or {}
    ch, nat = ins.get("change"), ins.get("national_change")
    if ch is not None and abs(ch) >= 10 and (ins.get("ytd_prev") or 0) >= 50:
        text = f"{_n(ins['ytd'])}{de(ins['ytd'])} firme intrate în insolvență, față de {_n(ins['ytd_prev'])} anul trecut."
        if nat is not None:
            text += f" În toată țara: {_pct(nat)}."
            if ch > 0 and nat > 0 and ch / nat >= 1.5:
                text += f" În Brașov cresc de {ch / nat:.1f} ori mai repede.".replace(".", ",", 1)
        out.append({"key": "insolvente", "value": _pct(ch), "title": "Insolvențele au crescut" if ch > 0 else "Insolvențele au scăzut", "text": text,
                    "tone": "rau" if ch > 0 else "bine", "tab": "firme"})
    fm = {f["form"]: f for f in forms or []}
    srl, pfa = fm.get("SRL") or {}, fm.get("PFA") or {}
    if srl.get("change") is not None and pfa.get("change") is not None and srl["change"] * pfa["change"] < 0:
        up, down = (pfa, srl) if pfa["change"] > 0 else (srl, pfa)
        out.append({"key": "forme", "value": f"{up['form']} {_pct(up['change'])}", "title": f"{up['form']} în loc de {down['form']}",
                    "text": f"{_cap(up['label'])} noi: {_n(up['ytd'])} ({_pct(up['change'])}). "
                            f"{_cap(down['label'])} noi: {_n(down['ytd'])} ({_pct(down['change'])}).",
                    "tone": "info", "tab": "firme"})
    mine = (rank1000 or {}).get("mine")
    if mine:
        out.append({"key": "loc", "value": f"Locul {mine['rank']}", "title": f"din {rank1000['of']} de județe la firme noi",
                    "text": f"{str(mine['value']).replace('.', ',')} firme noi la 1.000 de firme active, "
                            f"ca să comparăm județe de mărimi diferite. Fără București.",
                    "tone": "info", "tab": "firme"})
    return out[:3]
