#!/usr/bin/env python3
"""
KronPapir Facebook Auto-Poster

Posts articles to the Facebook Page on a schedule throughout the day.

Usage:
    python facebook_poster.py                        # Default: 1 editorial + 1 local
    python facebook_poster.py --mode editorial       # 1 editorial + 1 local article
    python facebook_poster.py --mode local           # 1 local article only
    python facebook_poster.py --mode national        # 1 national article only
    python facebook_poster.py --dry-run              # Show what would be posted
    python facebook_poster.py --dry-run --mode local # Dry-run for local mode
    python facebook_poster.py --test-token           # Check token validity

Schedule (cron):
    07:00 - editorial mode (1 editorial + 1 local)
    12:00 - local mode (1 local article)
    15:00 - local mode (1 local article)
    19:00 - local mode (1 local article)
"""

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# === Paths ===
BASE_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = BASE_DIR / "data" / "processed"
HISTORY_FILE = Path(__file__).resolve().parent / "posting_history.json"
LOG_FILE = BASE_DIR / "logs" / "facebook_poster.log"

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# === Logging ===
logger = logging.getLogger("facebook_poster")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


# === Config ===

class FacebookConfig:
    def __init__(self):
        self.page_access_token = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
        self.page_id = os.environ.get("FB_PAGE_ID", "").strip()
        self.posting_enabled = os.environ.get("FB_POSTING_ENABLED", "false").strip().lower() == "true"

    def validate(self):
        if not self.page_access_token:
            logger.error("FB_PAGE_ACCESS_TOKEN nu este setat in .env")
            return False
        if not self.page_id:
            logger.error("FB_PAGE_ID nu este setat in .env")
            return False
        if not self.posting_enabled:
            logger.error("FB_POSTING_ENABLED nu este 'true' — postarea este dezactivata")
            return False
        return True


# === Posting History ===

class PostingHistory:
    def __init__(self, path=HISTORY_FILE):
        self.path = path
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("Fisierul posting_history.json este corupt, se creeaza unul nou")
        return {"posted": []}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def is_posted(self, article_id):
        return any(entry["article_id"] == article_id for entry in self.data["posted"])

    def record(self, article_id, post_id, post_type):
        self.data["posted"].append({
            "article_id": article_id,
            "post_id": post_id,
            "post_type": post_type,
            "posted_at": datetime.now().isoformat(),
        })
        self._save()

    def cleanup_old(self, days=30):
        """Remove entries older than N days to keep the file small."""
        cutoff = datetime.now() - timedelta(days=days)
        before = len(self.data["posted"])
        self.data["posted"] = [
            entry for entry in self.data["posted"]
            if datetime.fromisoformat(entry["posted_at"]) > cutoff
        ]
        removed = before - len(self.data["posted"])
        if removed:
            logger.info(f"Curatare istoric: {removed} intrari vechi sterse")
            self._save()


# === Article Loading ===

def load_recent_articles(days=2):
    """Load processed articles from the last N days."""
    cutoff = datetime.now() - timedelta(days=days)
    articles = []

    if not PROCESSED_DIR.exists():
        logger.error(f"Directorul processed nu exista: {PROCESSED_DIR}")
        return articles

    for json_file in PROCESSED_DIR.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                article = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Nu pot citi {json_file.name}: {e}")
            continue

        date_str = article.get("date", "")
        if not date_str:
            continue

        try:
            article_date = datetime.fromisoformat(date_str)
        except ValueError:
            continue

        if article_date >= cutoff:
            articles.append(article)

    logger.info(f"Gasite {len(articles)} articole din ultimele {days} zile")
    return articles


# === Article Selection ===

def select_articles(articles, history, mode="editorial"):
    """
    Select articles based on mode:
    - editorial: 1 editorial + 1 local (morning post)
    - local: 1 local article (midday/afternoon/evening)
    - national: 1 national article
    """
    editorials = []
    locals_ = []
    nationals = []

    for art in articles:
        if history.is_posted(art.get("id", "")):
            continue

        if art.get("is_editorial") or art.get("category") == "editorial":
            editorials.append(art)
        elif art.get("type") == "local":
            locals_.append(art)
        elif art.get("type") == "national":
            nationals.append(art)

    # Sort by date descending (newest first)
    editorials.sort(key=lambda a: a.get("date", ""), reverse=True)
    locals_.sort(key=lambda a: a.get("date", ""), reverse=True)
    nationals.sort(key=lambda a: a.get("date", ""), reverse=True)

    selected = {}

    if mode == "editorial":
        # Morning: 1 editorial + 1 local
        if editorials:
            selected["editorial"] = editorials[0]
            logger.info(f"Editorial selectat: {editorials[0].get('title', 'N/A')}")
        else:
            logger.warning("Niciun editorial nou gasit pentru postare")

        if locals_:
            selected["local"] = locals_[0]
            logger.info(f"Articol local selectat: {locals_[0].get('title', 'N/A')}")
        else:
            logger.warning("Niciun articol local nou gasit pentru postare")

    elif mode == "local":
        # Single local article
        if locals_:
            selected["local"] = locals_[0]
            logger.info(f"Articol local selectat: {locals_[0].get('title', 'N/A')}")
        else:
            logger.warning("Niciun articol local nou gasit pentru postare")

    elif mode == "national":
        # Single national article
        if nationals:
            selected["national"] = nationals[0]
            logger.info(f"Articol national selectat: {nationals[0].get('title', 'N/A')}")
        else:
            logger.warning("Niciun articol national nou gasit pentru postare")

    return selected


# === URL Building ===

def build_article_url(article):
    """Build the public article URL with UTM tracking."""
    slug = article.get("slug", "")
    article_id = article.get("id", "")

    if slug:
        path = f"/stiri/{slug}"
    elif article_id:
        path = f"/articol/{article_id}"
    else:
        logger.error(f"Articolul nu are nici slug nici id: {article.get('title', 'N/A')}")
        return None

    utm_params = urllib.parse.urlencode({
        "utm_source": "facebook",
        "utm_medium": "social",
        "utm_campaign": "auto-post",
    })

    return f"https://kronpapir.ro{path}?{utm_params}"


# === Message Formatting ===

def format_post_message(article, post_type):
    """Format the Facebook post message."""
    title = article.get("title", "")
    excerpt = article.get("excerpt", "")
    author = article.get("author", "")

    # Trim excerpt to ~250 chars if needed
    if len(excerpt) > 250:
        excerpt = excerpt[:247].rsplit(" ", 1)[0] + "..."

    if post_type == "editorial":
        lines = [f"EDITORIAL | {title}"]
        if excerpt:
            lines.append(f"\n{excerpt}")
        if author:
            lines.append(f"\n\u2014 {author}")
    else:
        lines = [title]
        if excerpt:
            lines.append(f"\n{excerpt}")
        lines.append("\nCiteste pe KronPapir.ro")

    return "\n".join(lines)


# === Graph API ===

def post_to_facebook(config, message, link):
    """Post to Facebook Page via Graph API."""
    url = f"{GRAPH_API_BASE}/{config.page_id}/feed"

    data = urllib.parse.urlencode({
        "message": message,
        "link": link,
        "access_token": config.page_access_token,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            post_id = result.get("id", "")
            logger.info(f"Postat cu succes! Post ID: {post_id}")
            return post_id
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        try:
            error_data = json.loads(error_body)
            error_info = error_data.get("error", {})
            error_code = error_info.get("code", 0)
            error_msg = error_info.get("message", "Eroare necunoscuta")

            if error_code == 190:
                logger.error(f"Token expirat sau invalid: {error_msg}")
            elif error_code == 4:
                logger.error(f"Rate limit atins: {error_msg}")
            elif error_code == 200:
                logger.error(f"Permisiuni insuficiente: {error_msg}")
            else:
                logger.error(f"Eroare Graph API (cod {error_code}): {error_msg}")
        except json.JSONDecodeError:
            logger.error(f"Eroare HTTP {e.code}: {error_body[:500]}")
        return None
    except urllib.error.URLError as e:
        logger.error(f"Eroare retea: {e.reason}")
        return None


def verify_token(config):
    """Check token validity and expiry via debug_token endpoint."""
    url = (
        f"{GRAPH_API_BASE}/debug_token?"
        f"input_token={urllib.parse.quote(config.page_access_token)}"
        f"&access_token={urllib.parse.quote(config.page_access_token)}"
    )

    req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            data = result.get("data", {})

            is_valid = data.get("is_valid", False)
            app_id = data.get("app_id", "N/A")
            token_type = data.get("type", "N/A")
            expires_at = data.get("expires_at", 0)

            if not is_valid:
                logger.error("Token INVALID!")
                return False

            logger.info(f"Token valid — App ID: {app_id}, Tip: {token_type}")

            if expires_at == 0:
                logger.info("Token permanent (nu expira)")
            else:
                expiry_date = datetime.fromtimestamp(expires_at)
                days_left = (expiry_date - datetime.now()).days
                logger.info(f"Token expira pe {expiry_date.strftime('%Y-%m-%d')} ({days_left} zile ramase)")
                if days_left < 7:
                    logger.warning("ATENTIE: Tokenul expira in mai putin de 7 zile! Reinnoire necesara.")

            scopes = data.get("scopes", [])
            logger.info(f"Permisiuni: {', '.join(scopes) if scopes else 'N/A'}")

            return True

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error(f"Eroare la verificare token (HTTP {e.code}): {error_body[:300]}")
        return False
    except urllib.error.URLError as e:
        logger.error(f"Eroare retea la verificare token: {e.reason}")
        return False


# === Main ===

def main():
    parser = argparse.ArgumentParser(description="KronPapir Facebook Auto-Poster")
    parser.add_argument("--dry-run", action="store_true", help="Arata ce s-ar posta fara sa posteze")
    parser.add_argument("--test-token", action="store_true", help="Verifica validitatea tokenului")
    parser.add_argument("--mode", choices=["editorial", "local", "national"], default="editorial",
                        help="Mod postare: editorial (1 editorial + 1 local), local (1 local), national (1 national)")
    args = parser.parse_args()

    logger.info(f"=== KronPapir Facebook Auto-Poster (mod: {args.mode}) ===")

    config = FacebookConfig()

    # --test-token mode
    if args.test_token:
        if not config.page_access_token:
            logger.error("FB_PAGE_ACCESS_TOKEN nu este setat")
            sys.exit(1)
        ok = verify_token(config)
        sys.exit(0 if ok else 1)

    # Load articles and select candidates
    articles = load_recent_articles(days=2)
    if not articles:
        logger.warning("Niciun articol recent gasit. Iesire.")
        sys.exit(0)

    history = PostingHistory()
    history.cleanup_old(days=30)

    selected = select_articles(articles, history, mode=args.mode)
    if not selected:
        logger.info("Niciun articol nou de postat. Iesire.")
        sys.exit(0)

    # --dry-run mode
    if args.dry_run:
        logger.info("--- MOD DRY-RUN (nu se posteaza nimic) ---")
        for post_type, article in selected.items():
            url = build_article_url(article)
            message = format_post_message(article, post_type)
            logger.info(f"\n[{post_type.upper()}]")
            logger.info(f"  Titlu:  {article.get('title', 'N/A')}")
            logger.info(f"  ID:     {article.get('id', 'N/A')}")
            logger.info(f"  Data:   {article.get('date', 'N/A')}")
            logger.info(f"  URL:    {url}")
            logger.info(f"  Mesaj:\n{message}")
        logger.info("--- Sfarsit dry-run ---")
        sys.exit(0)

    # Live posting
    if not config.validate():
        sys.exit(1)

    posted_count = 0
    for post_type, article in selected.items():
        url = build_article_url(article)
        if not url:
            continue

        message = format_post_message(article, post_type)
        logger.info(f"Se posteaza {post_type}: {article.get('title', 'N/A')}")

        post_id = post_to_facebook(config, message, url)
        if post_id:
            history.record(article["id"], post_id, post_type)
            posted_count += 1
        else:
            logger.error(f"Esec la postarea articolului {post_type}: {article.get('id', 'N/A')}")

    logger.info(f"Finalizat: {posted_count}/{len(selected)} articole postate")


if __name__ == "__main__":
    main()
