"""Rapoartele de pe /afaceri-brasov, calculate din datele pe care le avem (ONRC, AJOFM, licitații).

Doar numărăm, sortăm și calculăm variații sau mediane; nu estimăm și nu completăm lipsurile.
O lună lipsă din istoric rămâne lipsă (graficul are o bară mai puțin, nu una inventată).
"""
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
        "employers": [(e.title() if e.isupper() else e, n) for e, n in by_employer.most_common(top)],
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
