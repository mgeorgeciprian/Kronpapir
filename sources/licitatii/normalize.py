"""Normalizarea textului și ghicirea județului (din trackerul de licitații al lui George)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Județele României, normalizate (fără diacritice, majuscule).
COUNTIES = [
    "ALBA", "ARAD", "ARGES", "BACAU", "BIHOR", "BISTRITA-NASAUD", "BOTOSANI",
    "BRAILA", "BRASOV", "BUZAU", "CALARASI", "CARAS-SEVERIN", "CLUJ", "CONSTANTA",
    "COVASNA", "DAMBOVITA", "DOLJ", "GALATI", "GIURGIU", "GORJ", "HARGHITA",
    "HUNEDOARA", "IALOMITA", "IASI", "ILFOV", "MARAMURES", "MEHEDINTI", "MURES",
    "NEAMT", "OLT", "PRAHOVA", "SALAJ", "SATU MARE", "SIBIU", "SUCEAVA",
    "TELEORMAN", "TIMIS", "TULCEA", "VALCEA", "VASLUI", "VRANCEA", "BUCURESTI",
]

# Localități care nu conțin numele județului (doar pentru județele urmărite atent).
CITY_TO_COUNTY = {
    "FAGARAS": "BRASOV", "CODLEA": "BRASOV", "SACELE": "BRASOV", "RASNOV": "BRASOV",
    "ZARNESTI": "BRASOV", "RUPEA": "BRASOV", "GHIMBAV": "BRASOV",
    "PREDEAL": "BRASOV", "PREJMER": "BRASOV", "HARMAN": "BRASOV",
    "SANPETRU": "BRASOV", "FELDIOARA": "BRASOV", "TARLUNGENI": "BRASOV",
    "BRAN": "BRASOV", "HALCHIU": "BRASOV",
    "SFANTU GHEORGHE": "COVASNA", "MIERCUREA CIUC": "HARGHITA",
    "ODORHEIUL SECUIESC": "HARGHITA", "TARGU MURES": "MURES", "ALBA IULIA": "ALBA",
    "CLUJ-NAPOCA": "CLUJ", "TIMISOARA": "TIMIS", "PLOIESTI": "PRAHOVA",
    "PITESTI": "ARGES", "CRAIOVA": "DOLJ", "RAMNICU VALCEA": "VALCEA",
    "PIATRA NEAMT": "NEAMT", "TARGOVISTE": "DAMBOVITA", "DEVA": "HUNEDOARA",
    "ORADEA": "BIHOR", "BAIA MARE": "MARAMURES", "ZALAU": "SALAJ",
    "DROBETA-TURNU SEVERIN": "MEHEDINTI", "SLATINA": "OLT", "TARGU JIU": "GORJ",
    "RESITA": "CARAS-SEVERIN", "FOCSANI": "VRANCEA", "SLOBOZIA": "IALOMITA",
    "ALEXANDRIA": "TELEORMAN", "BISTRITA": "BISTRITA-NASAUD",
}


def norm_text(value: Any) -> str:
    """Majuscule, fără diacritice, spații comprimate."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().upper()


def guess_county(*texts: str | None) -> str | None:
    """Ghicește județul din numele autorității / localitate. Întoarce nume normalizat."""
    blob = " " + " ".join(norm_text(t) for t in texts if t) + " "
    blob = re.sub(r"[^A-Z0-9-]+", " ", blob)
    for county in COUNTIES:
        if re.search(rf"(?<![A-Z-]){re.escape(county)}(?![A-Z-])", blob):
            return county
    if re.search(r"\bSECTOR(UL)? [1-6]\b", blob):
        return "BUCURESTI"
    for city, county in CITY_TO_COUNTY.items():
        if re.search(rf"(?<![A-Z-]){re.escape(city)}(?![A-Z-])", blob):
            return county
    return None
