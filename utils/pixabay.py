"""
Pixabay image search utility for KronPapir articles.
Provides fallback images when articles have no image from scraping.
"""

import os
import logging
import requests

logger = logging.getLogger("KronPapir.Pixabay")

# Maps Romanian keywords found in article titles to Pixabay search terms
KEYWORD_SEARCH_MAP = {
    "ultimul drum": "memorial candles flowers",
    "înmormânt": "funeral flowers candles",
    "inmormant": "funeral flowers candles",
    "funerar": "funeral ceremony church",
    "doliu": "mourning flowers wreath",
    "condoleanțe": "memorial candles flowers",
    "condoleante": "memorial candles flowers",
    "a murit": "memorial candles flowers",
    "a decedat": "memorial candles flowers",
    "accident": "car accident road",
    "incendiu": "fire building firefighter",
    "foc": "fire building firefighter",
    "spital": "hospital building medical",
    "medical": "hospital health medicine",
    "scoala": "school education classroom",
    "școală": "school education classroom",
    "universit": "university campus education",
    "politie": "police car law enforcement",
    "poliție": "police car law enforcement",
    "primari": "city hall government building",
    "primăria": "city hall government building",
    "consiliu": "government council meeting",
    "alegeri": "election voting democracy",
    "brasov": "Brasov Romania city center",
    "brașov": "Brasov Romania city center",
    "tramvai": "tram public transport city",
    "autobuz": "bus public transport city",
    "trafic": "traffic road cars city",
    "drum": "road highway construction",
    "autostrad": "highway motorway construction",
    "constructi": "construction building crane",
    "construcți": "construction building crane",
    "parc": "park green nature city",
    "munte": "mountain Romania landscape",
    "turism": "tourism travel Romania",
    "hotel": "hotel tourism accommodation",
    "restaur": "restaurant food dining",
    "magazin": "shopping store retail",
    "piata": "market square city",
    "piață": "market square city",
    "fotbal": "football soccer stadium",
    "sport": "sport competition athlete",
    "concert": "concert music stage",
    "festival": "festival event crowd",
    "teatru": "theater performance stage",
    "muzeu": "museum art culture",
    "biserica": "church Romania orthodox",
    "biserică": "church Romania orthodox",
    "vremea": "weather forecast sky",
    "meteo": "weather forecast sky",
    "ploaie": "rain weather storm",
    "ninsoare": "snow winter cold",
    "inundati": "flood water disaster",
    "inundați": "flood water disaster",
    "cutremur": "earthquake disaster building",
    "buget": "budget finance money",
    "economie": "economy finance business",
    "investiti": "investment business finance",
    "investiți": "investment business finance",
    "munca": "work office employment",
    "muncă": "work office employment",
    "greva": "strike protest workers",
    "grevă": "strike protest workers",
    "protest": "protest demonstration crowd",
    "covid": "health medical virus",
    "vaccin": "vaccine medical health",
    "copil": "children family education",
    "elev": "students school education",
    "student": "university students campus",
    "mediu": "environment nature green",
    "poluare": "pollution environment air",
    "reciclare": "recycling environment green",
    "urs": "bear wildlife nature Romania",
    "animal": "animal wildlife nature",
    "deces": "memorial candles flowers",
    "mort": "memorial candles flowers",
}

# Maps article categories to fallback search terms
CATEGORY_SEARCH_TERMS = {
    "local": "Brasov Romania city",
    "national": "Romania Bucharest parliament",
    "politica": "politics parliament Romania",
    "economie": "economy business finance",
    "cultura": "culture art Romania",
    "sport": "sport football Romania",
    "sanatate": "hospital health medicine",
    "social": "community people Romania",
    "mediu": "environment nature Romania",
    "tehnologie": "technology digital computer",
    "accidente": "accident emergency road",
    "evenimente": "event festival Romania",
    "editorial": "newspaper journalism editorial",
    "international": "world globe international",
}

# Generic fallback
DEFAULT_SEARCH = "Brasov Romania Transylvania"


def _get_api_key():
    """Get Pixabay API key from environment."""
    return os.environ.get("PIXABAY_API_KEY", "")


def search_pixabay(query, min_width=640):
    """
    Search Pixabay for an image matching the query.

    Args:
        query: Search terms for Pixabay
        min_width: Minimum image width

    Returns:
        Image URL string, or empty string if no results
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("PIXABAY_API_KEY not set")
        return ""

    try:
        resp = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "image_type": "photo",
                "orientation": "horizontal",
                "min_width": min_width,
                "per_page": 3,
                "safesearch": "true",
                "lang": "ro",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        hits = data.get("hits", [])
        if hits:
            return hits[0].get("webformatURL", "")

    except Exception as e:
        logger.error(f"Pixabay search failed for '{query}': {e}")

    return ""


def get_article_image(title, category="local"):
    """
    Get a relevant image for an article based on its title and category.

    Tries keyword matching first (most specific), then category fallback,
    then generic Brasov image.

    Args:
        title: Article title (Romanian)
        category: Article category

    Returns:
        Image URL string, or empty string if all searches fail
    """
    title_lower = title.lower()

    # Try keyword-based search (most specific match)
    for keyword, search_terms in KEYWORD_SEARCH_MAP.items():
        if keyword in title_lower:
            result = search_pixabay(search_terms)
            if result:
                logger.debug(f"Pixabay keyword match '{keyword}' for: {title[:50]}")
                return result

    # Try category-based search
    category_terms = CATEGORY_SEARCH_TERMS.get(category.lower(), "")
    if category_terms:
        result = search_pixabay(category_terms)
        if result:
            logger.debug(f"Pixabay category match '{category}' for: {title[:50]}")
            return result

    # Generic fallback
    result = search_pixabay(DEFAULT_SEARCH)
    if result:
        logger.debug(f"Pixabay generic fallback for: {title[:50]}")
    return result
