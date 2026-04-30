"""
KronPapir - Romanian Local News Aggregator
Brașov/Covasna Area
"""

import json
import os
import uuid
import random
import re
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from html import escape as html_escape
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, jsonify, request, abort, session, redirect, url_for, Response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['JSON_SORT_KEYS'] = False
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'kronpapir-secret-key-change-this')

# Configuration
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data' / 'processed'
RAW_ARTICLES_DIR = BASE_DIR / 'data' / 'articles'

# Admin configuration
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'kronpapir2026')

# Contributor configuration
CONTRIBUTORS_DIR = BASE_DIR / 'data' / 'contributors'
CONTRIBUTORS_FILE = CONTRIBUTORS_DIR / 'users.json'
CONTRIBUTOR_ARTICLES_DIR = CONTRIBUTORS_DIR / 'articles'

# AdSense configuration
ADSENSE_ENABLED = os.getenv('ADSENSE_ENABLED', 'false').lower() == 'true'
ADSENSE_CLIENT_ID = os.getenv('ADSENSE_CLIENT_ID', 'ca-pub-XXXXXXXXXXXXXXXX')
GOOGLE_SEARCH_CONSOLE_TOKEN = os.getenv('GOOGLE_SEARCH_CONSOLE_TOKEN', '')
PIXABAY_API_KEY = os.getenv('PIXABAY_API_KEY', '')
GA4_ENABLED = os.getenv('GA4_ENABLED', 'false').lower() == 'true'
GA4_MEASUREMENT_ID = os.getenv('GA4_MEASUREMENT_ID', '')

# Analytics configuration
ANALYTICS_DIR = BASE_DIR / 'data' / 'analytics'

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


def contributor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('contributor_id'):
            return redirect(url_for('contributor_login'))
        return f(*args, **kwargs)
    return decorated


_contributors_lock = threading.Lock()


def load_contributors():
    """Load all contributors from users.json."""
    with _contributors_lock:
        if CONTRIBUTORS_FILE.exists():
            with open(CONTRIBUTORS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('contributors', [])
    return []


def save_contributors(contributors_list):
    """Save contributors list to users.json."""
    CONTRIBUTORS_DIR.mkdir(parents=True, exist_ok=True)
    with _contributors_lock:
        with open(CONTRIBUTORS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'contributors': contributors_list}, f, ensure_ascii=False, indent=2)


def get_contributor_by_id(cid):
    """Find a contributor by ID."""
    for c in load_contributors():
        if c.get('id') == cid:
            return c
    return None


def get_contributor_by_email(email):
    """Find a contributor by email."""
    for c in load_contributors():
        if c.get('email', '').lower() == email.lower():
            return c
    return None


def load_contributor_articles(contributor_id, status_filter=None):
    """Load articles for a specific contributor."""
    articles = []
    articles_dir = CONTRIBUTOR_ARTICLES_DIR / contributor_id
    if not articles_dir.exists():
        return articles
    for json_file in sorted(articles_dir.glob('*.json'), reverse=True):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                art = json.load(f)
            if status_filter and art.get('status') != status_filter:
                continue
            articles.append(art)
        except Exception as e:
            print(f"Error loading contributor article {json_file}: {e}")
    articles.sort(key=lambda x: x.get('date', ''), reverse=True)
    return articles


def load_all_contributor_articles(status_filter=None):
    """Load all contributor articles (for admin review)."""
    articles = []
    if not CONTRIBUTOR_ARTICLES_DIR.exists():
        return articles
    for contributor_dir in CONTRIBUTOR_ARTICLES_DIR.iterdir():
        if not contributor_dir.is_dir():
            continue
        for json_file in contributor_dir.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    art = json.load(f)
                if status_filter and art.get('status') != status_filter:
                    continue
                articles.append(art)
            except Exception as e:
                print(f"Error loading contributor article {json_file}: {e}")
    articles.sort(key=lambda x: x.get('date', ''), reverse=True)
    return articles


def save_contributor_article(article):
    """Save a contributor article to its directory."""
    cid = article.get('contributor_id')
    aid = article.get('id')
    article_dir = CONTRIBUTOR_ARTICLES_DIR / cid
    article_dir.mkdir(parents=True, exist_ok=True)
    with open(article_dir / f"{aid}.json", 'w', encoding='utf-8') as f:
        json.dump(article, f, ensure_ascii=False, indent=2)


def get_contributor_article(contributor_id, article_id):
    """Get a single contributor article."""
    article_file = CONTRIBUTOR_ARTICLES_DIR / contributor_id / f"{article_id}.json"
    if article_file.exists():
        with open(article_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def update_contributor_article_count(contributor_id):
    """Recount approved articles for a contributor and update."""
    contributors = load_contributors()
    approved = len(load_contributor_articles(contributor_id, status_filter='approved'))
    for c in contributors:
        if c.get('id') == contributor_id:
            c['article_count'] = approved
            break
    save_contributors(contributors)


# Categories
CATEGORIES = {
    'local': 'Știri Locale',
    'politica': 'Politică',
    'economie': 'Economie',
    'cultura': 'Cultură',
    'sport': 'Sport',
    'sanatate': 'Sănătate',
    'social': 'Social',
    'mediu': 'Mediu'
}

# Article categories for admin panel
ARTICLE_CATEGORIES = [
    'politica',
    'economie',
    'sport',
    'cultura',
    'social',
    'educatie',
    'sanatate',
    'evenimente',
    'accidente'
]


def _truncate_at_sentence(text, max_len=200):
    """Truncate text at the first complete sentence within max_len."""
    paragraphs = re.findall(r'<p>(.*?)</p>', text, re.DOTALL)
    if paragraphs:
        clean = ' '.join(re.sub(r'<[^>]+>', '', p).strip() for p in paragraphs)
    else:
        clean = re.sub(r'<[^>]+>', '', text).strip()
    if len(clean) <= max_len:
        return clean
    for match in re.finditer(r'[.!?](?:\s|$)', clean):
        pos = match.start()
        if clean[pos] == '.' and pos > 0 and clean[pos - 1].isdigit():
            continue
        if pos + 1 <= max_len and pos >= 40:
            return clean[:pos + 1]
    truncated = clean[:max_len]
    last_space = truncated.rfind(' ')
    if last_space > 50:
        return truncated[:last_space] + '...'
    return truncated + '...'


def generate_slug(title):
    """Generate URL-friendly slug from title."""
    slug = title.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')


def load_articles(limit=None, category=None, is_national=False, all_types=False, editorials_only=False):
    """Load articles from processed data files."""
    articles = []

    if not DATA_DIR.exists():
        return articles

    try:
        for json_file in sorted(DATA_DIR.glob('*.json'), reverse=True):
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

                if isinstance(data, list):
                    articles.extend(data)
                else:
                    articles.append(data)
    except Exception as e:
        print(f"Error loading articles: {e}")

    # Filter editorials only
    if editorials_only:
        articles = [a for a in articles if a.get('is_editorial') or a.get('category') == 'editorial']
    elif not all_types:
        # Exclude editorials from normal article lists
        if category:
            articles = [a for a in articles if a.get('category', '').lower() == category.lower()]
        elif is_national:
            articles = [a for a in articles if a.get('type', 'local') == 'national' and not a.get('is_editorial')]
        else:
            articles = [a for a in articles if a.get('type', 'local') != 'national' and not a.get('is_editorial')]
    else:
        # Filter by category even in all_types mode
        if category:
            articles = [a for a in articles if a.get('category', '').lower() == category.lower()]

    # Generate slugs for articles that don't have them
    for article in articles:
        if not article.get('slug'):
            article['slug'] = generate_slug(article.get('title', 'article'))

    # Sort by date
    articles = sorted(articles, key=lambda x: x.get('date', ''), reverse=True)

    # Limit results
    if limit:
        articles = articles[:limit]

    return articles


def _extract_text_from_html(html):
    """Extract readable text from raw HTML, stripping scripts/styles."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        # Remove scripts and styles only (keep structural elements for text extraction)
        for tag in soup.find_all(['script', 'style', 'iframe', 'noscript']):
            tag.decompose()
        # Try to find the main article body first
        article = soup.find('article') or soup.find(class_=re.compile(r'article[-_]?(body|content|text)|post[-_]?(body|content)', re.I))
        if article:
            text = article.get_text(separator='\n', strip=True)
            if len(text) > 200:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                return '\n'.join(lines)
        # Fallback: get all text, then strip nav-like short lines
        text = soup.get_text(separator='\n', strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip() and len(l.strip()) > 20]
        return '\n'.join(lines)
    except Exception:
        return ''


def _ensure_content(article):
    """Ensure article has usable text content for the AI rewriter."""
    content = article.get('content') or article.get('text') or ''
    # If content is too short and we have original_text (raw HTML), extract from it
    if len(content) < 200 and article.get('original_text'):
        extracted = _extract_text_from_html(article['original_text'])
        if len(extracted) > len(content):
            article['content'] = extracted
    return article


def load_raw_articles():
    """Load raw articles from data/articles/{source}/*.json directories."""
    articles = []

    if not RAW_ARTICLES_DIR.exists():
        return articles

    for json_file in RAW_ARTICLES_DIR.glob('**/*.json'):
        # Skip processed files and stats
        if '_processed' in json_file.name or json_file.name == 'scraper_stats.json':
            continue
        # Only consider files inside subdirectories (source folders)
        if json_file.parent == RAW_ARTICLES_DIR:
            continue

        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            items = data if isinstance(data, list) else [data]
            for art in items:
                art_id = art.get('id') or json_file.stem
                art['id'] = art_id
                art['source_id'] = json_file.parent.name
                art['is_processed'] = (DATA_DIR / f"{art_id}.json").exists()
                articles.append(art)
        except Exception as e:
            print(f"Error loading raw article {json_file}: {e}")

    # Sort by date descending
    articles.sort(key=lambda x: x.get('date', ''), reverse=True)
    return articles


def _fallback_copy_web(article):
    """Create an unprocessed copy of a raw article for the website."""
    article = _ensure_content(article)
    content = article.get('content') or article.get('text') or ''
    return {
        'id': article.get('id', ''),
        'title': article.get('title', 'Fără titlu'),
        'seo_title': article.get('title', 'Fără titlu')[:60],
        'content': content,
        'excerpt': _truncate_at_sentence(content, 200),
        'meta_description': _truncate_at_sentence(content, 155),
        'slug': '',
        'keywords': [],
        'category': article.get('category', 'Social'),
        'type': 'national' if article.get('category') == 'national' or article.get('source_category') == 'national' else 'local',
        'source': article.get('source', ''),
        'url': article.get('url', ''),
        'image': article.get('image_url') or article.get('image', ''),
        'date': article.get('date') or article.get('published') or datetime.now().isoformat(),
        'author': 'Redacția KronPapir',
        'processed': False,
    }


_analytics_lock = threading.Lock()

@app.before_request
def track_visit():
    """Lightweight internal analytics tracker."""
    path = request.path
    # Skip static, admin, API, SEO, contributor panel, and favicon paths
    if any(path.startswith(p) for p in ('/static', '/admin', '/api/', '/robots', '/sitemap', '/google6', '/colaborator/panou', '/colaborator/scrie', '/colaborator/editeaza', '/colaborator/sterge', '/colaborator/login', '/colaborator/logout', '/colaborator/inregistrare')):
        return
    if path == '/favicon.ico':
        return

    # Skip bots
    ua = (request.headers.get('User-Agent') or '').lower()
    if any(bot in ua for bot in ('bot', 'crawler', 'spider', 'curl', 'wget', 'python-requests')):
        return

    try:
        ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        analytics_file = ANALYTICS_DIR / f'{today}.json'

        # Parse referrer domain
        referrer = request.referrer or ''
        if referrer:
            try:
                referrer_domain = urllib.parse.urlparse(referrer).netloc or 'direct'
            except Exception:
                referrer_domain = 'direct'
        else:
            referrer_domain = 'direct'

        # UTM params
        utm_source = request.args.get('utm_source', '')
        utm_medium = request.args.get('utm_medium', '')
        utm_campaign = request.args.get('utm_campaign', '')

        view = {
            'path': path,
            'referrer': referrer_domain,
            'utm_source': utm_source,
            'utm_medium': utm_medium,
            'utm_campaign': utm_campaign,
            'timestamp': datetime.now().isoformat(),
        }

        with _analytics_lock:
            # Load existing data
            if analytics_file.exists():
                with open(analytics_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {
                    'date': today,
                    'total_views': 0,
                    'pages': {},
                    'referrers': {},
                    'utm_sources': {},
                    'utm_campaigns': {},
                    'views': [],
                }

            # Update summary counters
            data['total_views'] = data.get('total_views', 0) + 1
            pages = data.get('pages', {})
            pages[path] = pages.get(path, 0) + 1
            data['pages'] = pages

            referrers = data.get('referrers', {})
            referrers[referrer_domain] = referrers.get(referrer_domain, 0) + 1
            data['referrers'] = referrers

            if utm_source:
                utm_sources = data.get('utm_sources', {})
                utm_sources[utm_source] = utm_sources.get(utm_source, 0) + 1
                data['utm_sources'] = utm_sources

            if utm_campaign:
                # Store campaign with source for context
                campaign_key = utm_campaign
                utm_campaigns = data.get('utm_campaigns', {})
                if campaign_key not in utm_campaigns:
                    utm_campaigns[campaign_key] = {'count': 0, 'source': utm_source}
                utm_campaigns[campaign_key]['count'] = utm_campaigns[campaign_key].get('count', 0) + 1
                data['utm_campaigns'] = utm_campaigns

            # Append to views array (cap at 500)
            views = data.get('views', [])
            views.append(view)
            if len(views) > 500:
                views = views[-500:]
            data['views'] = views

            # Write back
            with open(analytics_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Analytics tracking error: {e}")


@app.route('/')
def index():
    """Homepage - latest local news with national summary sidebar."""
    local_articles = load_articles(limit=10, is_national=False)
    national_articles = load_articles(limit=5, is_national=True)
    editorial_articles = load_articles(limit=3, editorials_only=True)
    featured = local_articles[0] if local_articles else None
    latest = local_articles[1:7] if len(local_articles) > 1 else []
    most_read = local_articles[7:10] if len(local_articles) > 7 else []

    return render_template(
        'index.html',
        featured=featured,
        latest=latest,
        national=national_articles,
        editorials=editorial_articles,
        most_read=most_read,
        categories=CATEGORIES,
        adsense_enabled=ADSENSE_ENABLED,
        adsense_client_id=ADSENSE_CLIENT_ID
    )


@app.route('/local')
def local_news():
    """All local news with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 15

    all_articles = load_articles(is_national=False)
    total = len(all_articles)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_articles[start:end]

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'local.html',
        articles=articles,
        page=page,
        total_pages=total_pages,
        total=total,
        categories=CATEGORIES
    )


@app.route('/national')
def national_news():
    """National news summary."""
    page = request.args.get('page', 1, type=int)
    per_page = 15

    all_articles = load_articles(is_national=True)
    total = len(all_articles)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_articles[start:end]

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'national.html',
        articles=articles,
        page=page,
        total_pages=total_pages,
        total=total,
        categories=CATEGORIES
    )


@app.route('/categorie/<category>')
def category(category):
    """Articles by category with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = 15

    all_articles = load_articles(category=category, is_national=False)
    total = len(all_articles)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_articles[start:end]

    total_pages = (total + per_page - 1) // per_page
    category_name = CATEGORIES.get(category, category)

    return render_template(
        'category.html',
        articles=articles,
        category=category,
        category_name=category_name,
        page=page,
        total_pages=total_pages,
        total=total,
        categories=CATEGORIES
    )


@app.route('/articol/<article_id>')
def article(article_id):
    """Single article page."""
    all_articles = load_articles(all_types=True)

    # Find article by ID
    current_article = None
    for art in all_articles:
        if art.get('id') == article_id:
            current_article = art
            break

    if not current_article:
        abort(404)

    # Get related articles (same category, different article)
    category = current_article.get('category')
    related = []
    if category:
        related = [
            a for a in load_articles(category=category)
            if a.get('id') != article_id
        ][:5]

    # Contributor info for byline linking
    contributor_info = None
    if current_article.get('contributor_id'):
        contributor_info = get_contributor_by_id(current_article['contributor_id'])

    return render_template(
        'article.html',
        article=current_article,
        related=related,
        contributor_info=contributor_info,
        categories=CATEGORIES,
        adsense_enabled=ADSENSE_ENABLED,
        adsense_client_id=ADSENSE_CLIENT_ID
    )


@app.route('/stiri/<slug>')
def article_by_slug(slug):
    """Single article page accessed by slug."""
    all_articles = load_articles(all_types=True)

    # Find article by slug
    current_article = None
    for art in all_articles:
        article_slug = art.get('slug') or generate_slug(art.get('title', ''))
        if article_slug == slug:
            current_article = art
            break

    if not current_article:
        abort(404)

    # Get related articles (same category, different article)
    category = current_article.get('category')
    related = []
    if category:
        related = [
            a for a in load_articles(category=category)
            if a.get('id') != current_article.get('id')
        ][:5]

    # Contributor info for byline linking
    contributor_info = None
    if current_article.get('contributor_id'):
        contributor_info = get_contributor_by_id(current_article['contributor_id'])

    return render_template(
        'article.html',
        article=current_article,
        related=related,
        contributor_info=contributor_info,
        categories=CATEGORIES,
        adsense_enabled=ADSENSE_ENABLED,
        adsense_client_id=ADSENSE_CLIENT_ID
    )


@app.route('/editoriale')
def editoriale():
    """Editorial articles by Andrei Varga."""
    page = request.args.get('page', 1, type=int)
    per_page = 10

    all_editorials = load_articles(editorials_only=True)
    total = len(all_editorials)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_editorials[start:end]

    total_pages = (total + per_page - 1) // per_page

    # Featured editorial (most recent)
    featured_editorial = articles[0] if articles else None
    rest_editorials = articles[1:] if len(articles) > 1 else []

    return render_template(
        'editoriale.html',
        featured_editorial=featured_editorial,
        articles=rest_editorials,
        page=page,
        total_pages=total_pages,
        total=total,
        categories=CATEGORIES,
        adsense_enabled=ADSENSE_ENABLED,
        adsense_client_id=ADSENSE_CLIENT_ID
    )


@app.route('/despre')
def about():
    """About page."""
    return render_template('despre.html', categories=CATEGORIES)


@app.route('/confidentialitate')
def privacy_policy():
    """Privacy policy page."""
    return render_template('confidentialitate.html', categories=CATEGORIES)


@app.route('/termeni')
def terms_conditions():
    """Terms and conditions page."""
    return render_template('termeni.html', categories=CATEGORIES)


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact page - GET shows form, POST handles submission."""
    if request.method == 'POST':
        # Handle contact form submission
        try:
            nume = request.form.get('nume', '').strip()
            email = request.form.get('email', '').strip()
            subiect = request.form.get('subiect', '').strip()
            mesaj = request.form.get('mesaj', '').strip()
            gdpr = request.form.get('gdpr')

            # Validate required fields
            if not all([nume, email, subiect, mesaj, gdpr]):
                return render_template('contact.html', categories=CATEGORIES,
                                     error='Vă rugăm să completați toate câmpurile marcate cu *')

            # Validate email format
            if '@' not in email or '.' not in email:
                return render_template('contact.html', categories=CATEGORIES,
                                     error='Adresa de email nu este validă')

            # TODO: Send email or store in database
            # For now, just return success message
            return render_template('contact.html', categories=CATEGORIES,
                                 success='Mulțumim! Mesajul tău a fost trimis. Îți vom răspunde în maxim 48 de ore.')

        except Exception as e:
            print(f"Error handling contact form: {e}")
            return render_template('contact.html', categories=CATEGORIES,
                                 error='A apărut o eroare. Vă rugăm să încercați din nou.')

    # GET request - show contact form
    return render_template('contact.html', categories=CATEGORIES)


@app.route('/api/articles')
def api_articles():
    """JSON API for articles."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('limit', 20, type=int)
    category = request.args.get('category', None)
    is_national = request.args.get('type', 'local') == 'national'

    all_articles = load_articles(category=category, is_national=is_national)
    total = len(all_articles)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_articles[start:end]

    total_pages = (total + per_page - 1) // per_page

    return jsonify({
        'articles': articles,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages
        }
    })


# Admin Panel Routes

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page."""
    if request.method == 'POST':
        password = request.form.get('password', '')
        if password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error='Parolă incorectă', categories=CATEGORIES)

    return render_template('admin_login.html', categories=CATEGORIES)


@app.route('/admin', methods=['GET'])
@admin_required
def admin_dashboard():
    """Admin dashboard showing article statistics."""
    all_articles = load_articles()
    today = datetime.now().strftime('%Y-%m-%d')
    today_articles = [a for a in all_articles if a.get('date', '').startswith(today)]

    recent_articles = all_articles[:10]

    # Raw article stats
    raw_articles = load_raw_articles()
    raw_total = len(raw_articles)
    raw_unprocessed = sum(1 for a in raw_articles if not a.get('is_processed'))

    # Load analytics data
    analytics_today = {}
    analytics_yesterday = {}
    analytics_week = []

    try:
        today_dt = datetime.now()
        # Today
        today_file = ANALYTICS_DIR / f'{today}.json'
        if today_file.exists():
            with open(today_file, 'r', encoding='utf-8') as f:
                analytics_today = json.load(f)

        # Yesterday
        yesterday = (today_dt - timedelta(days=1)).strftime('%Y-%m-%d')
        yesterday_file = ANALYTICS_DIR / f'{yesterday}.json'
        if yesterday_file.exists():
            with open(yesterday_file, 'r', encoding='utf-8') as f:
                analytics_yesterday = json.load(f)

        # Last 7 days
        for i in range(6, -1, -1):
            day = (today_dt - timedelta(days=i)).strftime('%Y-%m-%d')
            day_file = ANALYTICS_DIR / f'{day}.json'
            if day_file.exists():
                with open(day_file, 'r', encoding='utf-8') as f:
                    day_data = json.load(f)
                analytics_week.append({'date': day, 'views': day_data.get('total_views', 0)})
            else:
                analytics_week.append({'date': day, 'views': 0})
    except Exception as e:
        print(f"Error loading analytics: {e}")

    # Compute top referrers, pages, UTM data
    views_today = analytics_today.get('total_views', 0)
    views_yesterday = analytics_yesterday.get('total_views', 0)

    top_referrers = sorted(
        analytics_today.get('referrers', {}).items(),
        key=lambda x: x[1], reverse=True
    )[:5]

    top_pages = sorted(
        analytics_today.get('pages', {}).items(),
        key=lambda x: x[1], reverse=True
    )[:5]

    utm_sources = sorted(
        analytics_today.get('utm_sources', {}).items(),
        key=lambda x: x[1], reverse=True
    )

    utm_campaigns_raw = analytics_today.get('utm_campaigns', {})
    utm_campaigns = sorted(
        [{'name': k, 'source': v.get('source', ''), 'count': v.get('count', 0)}
         for k, v in utm_campaigns_raw.items()],
        key=lambda x: x['count'], reverse=True
    )

    top_referrer_name = top_referrers[0][0] if top_referrers else '-'

    return render_template(
        'admin_dashboard.html',
        total_articles=len(all_articles),
        today_articles=len(today_articles),
        recent_articles=recent_articles,
        raw_total=raw_total,
        raw_unprocessed=raw_unprocessed,
        categories=CATEGORIES,
        views_today=views_today,
        views_yesterday=views_yesterday,
        top_referrer_name=top_referrer_name,
        top_referrers=top_referrers,
        top_pages=top_pages,
        utm_sources=utm_sources,
        utm_campaigns=utm_campaigns,
        analytics_week=analytics_week,
    )


@app.route('/admin/scrie', methods=['GET', 'POST'])
@admin_required
def admin_write():
    """Article writing form and processing."""
    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            category = request.form.get('category', 'local').strip()
            article_type = request.form.get('type', 'local').strip()
            content = request.form.get('content', '').strip()
            image_url = request.form.get('image_url', '').strip()
            source = request.form.get('source', 'Admin').strip()

            # Validate required fields
            if not all([title, category, article_type, content]):
                return render_template(
                    'admin_write.html',
                    error='Vă rugăm să completați toate câmpurile marcate cu *',
                    categories=CATEGORIES,
                    article_categories=ARTICLE_CATEGORIES
                )

            # Create article object
            article = {
                'id': str(uuid.uuid4()),
                'title': title,
                'category': category,
                'type': article_type,
                'content': content,
                'image': image_url if image_url else None,
                'source': source,
                'date': datetime.now().isoformat(),
                'author': 'Redacția KronPapir'
            }

            # Ensure data directory exists
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            # Save article as JSON
            article_file = DATA_DIR / f"{article['id']}.json"
            with open(article_file, 'w', encoding='utf-8') as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

            return render_template(
                'admin_write.html',
                success='Articol salvat cu succes!',
                categories=CATEGORIES,
                article_categories=ARTICLE_CATEGORIES
            )

        except Exception as e:
            print(f"Error saving article: {e}")
            return render_template(
                'admin_write.html',
                error=f'A apărut o eroare: {str(e)}',
                categories=CATEGORIES,
                article_categories=ARTICLE_CATEGORIES
            )

    return render_template(
        'admin_write.html',
        categories=CATEGORIES,
        article_categories=ARTICLE_CATEGORIES
    )


@app.route('/admin/articole')
@admin_required
def admin_articles():
    """List all articles with search/filter and edit/delete options."""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Get filter parameters
    q = request.args.get('q', '').strip()
    filter_category = request.args.get('category', '').strip()
    filter_type = request.args.get('type', '').strip()
    filter_source = request.args.get('source', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    all_articles = load_articles(all_types=True)

    # Collect unique sources for dropdown before filtering
    all_sources = sorted(set(a.get('source', '') for a in all_articles if a.get('source')))

    # Apply filters
    if q:
        q_lower = q.lower()
        all_articles = [a for a in all_articles if
                        q_lower in a.get('title', '').lower() or
                        q_lower in a.get('content', '')[:500].lower() or
                        q_lower in a.get('excerpt', '').lower()]
    if filter_category:
        all_articles = [a for a in all_articles if a.get('category', '').lower() == filter_category.lower()]
    if filter_type:
        if filter_type == 'editorial':
            all_articles = [a for a in all_articles if a.get('is_editorial') or a.get('category') == 'editorial']
        else:
            all_articles = [a for a in all_articles if a.get('type', 'local') == filter_type and not a.get('is_editorial')]
    if filter_source:
        all_articles = [a for a in all_articles if a.get('source', '') == filter_source]
    if date_from:
        all_articles = [a for a in all_articles if a.get('date', '')[:10] >= date_from]
    if date_to:
        all_articles = [a for a in all_articles if a.get('date', '')[:10] <= date_to]

    total = len(all_articles)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_articles[start:end]

    total_pages = (total + per_page - 1) // per_page

    # Build set of article IDs that have matching raw sources
    raw_article_ids = set()
    if RAW_ARTICLES_DIR.exists():
        for json_file in RAW_ARTICLES_DIR.glob('**/*.json'):
            if '_processed' in json_file.name or json_file.name == 'scraper_stats.json':
                continue
            if json_file.parent == RAW_ARTICLES_DIR:
                continue
            raw_article_ids.add(json_file.stem)

    # Check if any filter is active
    has_filters = any([q, filter_category, filter_type, filter_source, date_from, date_to])

    return render_template(
        'admin_articles.html',
        articles=articles,
        page=page,
        total_pages=total_pages,
        total=total,
        raw_article_ids=raw_article_ids,
        categories=CATEGORIES,
        article_categories=ARTICLE_CATEGORIES,
        all_sources=all_sources,
        q=q,
        filter_category=filter_category,
        filter_type=filter_type,
        filter_source=filter_source,
        date_from=date_from,
        date_to=date_to,
        has_filters=has_filters
    )


@app.route('/admin/articol/editeaza/<article_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit(article_id):
    """Edit existing article."""
    all_articles = load_articles()

    # Find article by ID
    article = None
    for art in all_articles:
        if art.get('id') == article_id:
            article = art
            break

    if not article:
        abort(404)

    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            category = request.form.get('category', 'local').strip()
            article_type = request.form.get('type', 'local').strip()
            content = request.form.get('content', '').strip()
            image_url = request.form.get('image_url', '').strip()
            source = request.form.get('source', 'Admin').strip()

            # Validate required fields
            if not all([title, category, article_type, content]):
                return render_template(
                    'admin_edit.html',
                    article=article,
                    error='Vă rugăm să completați toate câmpurile marcate cu *',
                    categories=CATEGORIES,
                    article_categories=ARTICLE_CATEGORIES
                )

            # Parse keywords from comma-separated hidden field
            keywords_raw = request.form.get('keywords', '').strip()
            keywords = [k.strip() for k in keywords_raw.split(',') if k.strip()] if keywords_raw else []

            # Update article object
            article.update({
                'title': title,
                'category': category,
                'type': article_type,
                'content': content,
                'image': image_url if image_url else None,
                'source': source,
                'keywords': keywords,
                'updated': datetime.now().isoformat()
            })

            # Save article as JSON
            article_file = DATA_DIR / f"{article['id']}.json"
            with open(article_file, 'w', encoding='utf-8') as f:
                json.dump(article, f, ensure_ascii=False, indent=2)

            return render_template(
                'admin_edit.html',
                article=article,
                success='Articol actualizat cu succes!',
                categories=CATEGORIES,
                article_categories=ARTICLE_CATEGORIES
            )

        except Exception as e:
            print(f"Error updating article: {e}")
            return render_template(
                'admin_edit.html',
                article=article,
                error=f'A apărut o eroare: {str(e)}',
                categories=CATEGORIES,
                article_categories=ARTICLE_CATEGORIES
            )

    return render_template(
        'admin_edit.html',
        article=article,
        categories=CATEGORIES,
        article_categories=ARTICLE_CATEGORIES
    )


@app.route('/admin/articol/sterge/<article_id>', methods=['POST'])
@admin_required
def admin_delete(article_id):
    """Delete article."""
    try:
        article_file = DATA_DIR / f"{article_id}.json"
        if article_file.exists():
            article_file.unlink()
            return jsonify({'success': True, 'message': 'Articol șters cu succes'})
        else:
            return jsonify({'success': False, 'message': 'Articol nu găsit'}), 404
    except Exception as e:
        print(f"Error deleting article: {e}")
        return jsonify({'success': False, 'message': f'Eroare: {str(e)}'}), 500


@app.route('/admin/brute')
@admin_required
def admin_raw_articles():
    """List raw/scraped articles that can be processed."""
    articles = load_raw_articles()
    total = len(articles)
    unprocessed = sum(1 for a in articles if not a.get('is_processed'))
    sources = list(set(a.get('source_id', '') for a in articles))

    # Results from redirect after processing
    results = {
        'success': request.args.get('success', type=int),
        'failed': request.args.get('failed', type=int),
        'editorial': request.args.get('editorial', ''),
    }

    return render_template(
        'admin_raw_articles.html',
        articles=articles,
        total=total,
        unprocessed=unprocessed,
        sources=sources,
        results=results,
        categories=CATEGORIES
    )


@app.route('/admin/process', methods=['POST'])
@admin_required
def admin_process():
    """Process selected raw articles with AI rewriter."""
    raw_articles = load_raw_articles()
    raw_by_id = {a['id']: a for a in raw_articles}

    auto_mode = request.form.get('auto_mode', '')
    selected_ids = request.form.getlist('article_ids[]')

    if auto_mode == 'one_per_source':
        # Pick latest unprocessed article from each source
        latest_per_source = {}
        for art in raw_articles:
            if art.get('is_processed'):
                continue
            src = art.get('source_id', '')
            if src not in latest_per_source:
                latest_per_source[src] = art
        selected_ids = [a['id'] for a in latest_per_source.values()]

    if not selected_ids:
        return redirect(url_for('admin_raw_articles', success=0, failed=0))

    # Try to use AI rewriter
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    rewriter = None

    if api_key:
        try:
            from ai.rewriter import ArticleRewriter
            rewriter = ArticleRewriter(
                api_key=api_key,
                model=os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929'),
            )
        except Exception as e:
            print(f"Could not initialize AI rewriter: {e}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    success_count = 0
    failed_count = 0
    processed_articles = []

    for art_id in selected_ids:
        art = raw_by_id.get(art_id)
        if not art:
            continue

        dest = DATA_DIR / f"{art_id}.json"
        if dest.exists():
            success_count += 1
            continue

        # Ensure article has usable content for AI
        art = _ensure_content(art)

        if rewriter:
            try:
                result = rewriter.rewrite_article(art)
                if result:
                    with open(dest, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    success_count += 1
                    processed_articles.append(result)
                    continue
                else:
                    failed_count += 1
            except Exception as e:
                print(f"AI processing failed for {art_id}: {e}")
                failed_count += 1

        # Fallback: copy without AI processing
        if not (DATA_DIR / f"{art_id}.json").exists():
            fallback = _fallback_copy_web(art)
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(fallback, f, ensure_ascii=False, indent=2)
            success_count += 1
            processed_articles.append(fallback)

    # Generate editorial if enough national articles
    editorial_name = ''
    if rewriter:
        national_articles = [a for a in processed_articles
                             if a.get('type') == 'national'
                             or a.get('category') == 'national']
        if len(national_articles) >= 3:
            try:
                raw_national = [raw_by_id[a['id']] for a in national_articles
                                if a['id'] in raw_by_id]
                if len(raw_national) >= 3:
                    editorial = rewriter.write_editorial(raw_national, editorial_type='national')
                    if editorial:
                        ed_dest = DATA_DIR / f"{editorial['id']}.json"
                        with open(ed_dest, 'w', encoding='utf-8') as f:
                            json.dump(editorial, f, ensure_ascii=False, indent=2)
                        editorial_name = editorial.get('title', '')
            except Exception as e:
                print(f"Editorial generation failed: {e}")

    return redirect(url_for('admin_raw_articles',
                            success=success_count,
                            failed=failed_count,
                            editorial=editorial_name))


def _find_raw_for_processed(processed_article):
    """Find the matching raw article for a processed article."""
    if not RAW_ARTICLES_DIR.exists():
        return None

    source = processed_article.get('source', '')
    article_id = processed_article.get('id', '')

    for json_file in RAW_ARTICLES_DIR.glob('**/*.json'):
        if '_processed' in json_file.name or json_file.name == 'scraper_stats.json':
            continue
        if json_file.parent == RAW_ARTICLES_DIR:
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            items = data if isinstance(data, list) else [data]
            for art in items:
                art_id = art.get('id') or json_file.stem
                if art_id == article_id:
                    art['_raw_file'] = str(json_file)
                    return art
        except Exception:
            continue
    return None


@app.route('/admin/articol/compara/<article_id>')
@admin_required
def admin_compare(article_id):
    """Side-by-side comparison of raw vs processed article."""
    # Find processed article
    processed = None
    processed_filename = None
    for json_file in sorted(DATA_DIR.glob('*.json'), reverse=True):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                if data.get('id') == article_id or json_file.stem == article_id:
                    processed = data
                    processed_filename = json_file.stem
                    break
        except Exception:
            continue

    if not processed:
        abort(404)

    # Find matching raw article
    raw = _find_raw_for_processed(processed)
    if raw:
        raw = _ensure_content(raw)

    return render_template(
        'admin_compare.html',
        processed=processed,
        raw=raw,
        processed_filename=processed_filename,
        categories=CATEGORIES
    )


@app.route('/admin/articol/reprocess/<processed_filename>', methods=['POST'])
@admin_required
def admin_reprocess(processed_filename):
    """Re-process a single article through AI rewriter."""
    dest = DATA_DIR / f"{processed_filename}.json"
    if not dest.exists():
        return jsonify({'success': False, 'message': 'Articol procesat nu a fost gasit'}), 404

    try:
        with open(dest, 'r', encoding='utf-8') as f:
            processed = json.load(f)
    except Exception:
        return jsonify({'success': False, 'message': 'Eroare la citirea articolului'}), 500

    raw = _find_raw_for_processed(processed)
    if not raw:
        return jsonify({'success': False, 'message': 'Articolul brut original nu a fost gasit'}), 404

    raw = _ensure_content(raw)

    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return jsonify({'success': False, 'message': 'ANTHROPIC_API_KEY nu e configurat'}), 500

    try:
        from ai.rewriter import ArticleRewriter
        rewriter = ArticleRewriter(
            api_key=api_key,
            model=os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929'),
        )
        result = rewriter.rewrite_article(raw)
        if result:
            # Keep original ID so the filename stays the same
            result['id'] = processed_filename
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            return jsonify({'success': True, 'message': 'Articol reprocesat cu succes!'})
        else:
            return jsonify({'success': False, 'message': 'AI rewriter a returnat None'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f'Eroare: {str(e)}'}), 500


@app.route('/admin/api/images')
@admin_required
def admin_api_images():
    """Proxy to Pixabay API for stock image search."""
    query = request.args.get('q', '').strip()
    if not query or not PIXABAY_API_KEY:
        return jsonify({'hits': []})

    params = urllib.parse.urlencode({
        'key': PIXABAY_API_KEY,
        'q': query,
        'image_type': 'photo',
        'per_page': 12,
        'safesearch': 'true',
        'lang': 'ro',
    })
    url = f'https://pixabay.com/api/?{params}'

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'KronPapir/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        hits = [
            {
                'previewURL': h.get('previewURL', ''),
                'webformatURL': h.get('webformatURL', ''),
                'tags': h.get('tags', ''),
            }
            for h in data.get('hits', [])
        ]
        return jsonify({'hits': hits})
    except Exception as e:
        print(f"Pixabay API error: {e}")
        return jsonify({'hits': [], 'error': str(e)}), 500


ROMANIAN_STOPWORDS = {
    'si', 'in', 'la', 'de', 'cu', 'pe', 'din', 'pentru', 'care', 'este',
    'sunt', 'a', 'o', 'un', 'se', 'nu', 'sa', 'mai', 'ca', 'dar',
    'sau', 'ce', 'acest', 'aceasta', 'unei', 'unui', 'ale', 'al',
    'ai', 'dintre', 'prin', 'fost', 'fi', 'va', 'vor', 'au', 'am',
    'era', 'fiind', 'asupra', 'intre', 'dupa', 'fara', 'iar', 'cel',
    'cea', 'cei', 'cele', 'foarte', 'doar', 'deja', 'inca', 'astfel',
    'precum', 'pana', 'apoi', 'cand', 'unde', 'cum', 'cat', 'fie',
    'poate', 'putea', 'acesta', 'aceasta', 'acestia', 'acestea',
    'lui', 'lor', 'celor', 'asemenea', 'ori', 'chiar', 'atunci',
    'tot', 'toate', 'toata', 'toti', 'acum', 'despre', 'care',
}


@app.route('/admin/api/suggest-keywords', methods=['POST'])
@admin_required
def admin_api_suggest_keywords():
    """Suggest keywords for an article based on title and content."""
    data = request.get_json(silent=True) or {}
    title = data.get('title', '')
    content = data.get('content', '')

    # Try AI-powered suggestion first
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if api_key and title:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = f"Genereaza 8 cuvinte cheie SEO relevante pentru acest articol romanesc. Returneaza DOAR cuvintele cheie separate prin virgula, fara numerotare.\n\nTitlu: {title}\nContinut: {content[:500]}"
            response = client.messages.create(
                model=os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-5-20250929'),
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            keywords = [k.strip() for k in text.split(',') if k.strip()]
            if keywords:
                return jsonify({'keywords': keywords[:10]})
        except Exception as e:
            print(f"AI keyword suggestion failed: {e}")

    # Fallback: extract keywords from title
    text = f"{title} {content[:300]}".lower()
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    # Extract multi-word phrases from title
    title_clean = re.sub(r'[^\w\s]', ' ', title.lower()).strip()
    title_words = [w for w in title_clean.split() if w not in ROMANIAN_STOPWORDS and len(w) > 2]

    keywords = []
    # Add title as potential keyword if short enough
    if len(title_clean) <= 50:
        keywords.append(title_clean)
    # Add individual title words
    for w in title_words:
        if w not in keywords and len(w) > 3:
            keywords.append(w)

    return jsonify({'keywords': keywords[:8]})


@app.route('/admin/logout')
def admin_logout():
    """Logout from admin panel."""
    session.pop('admin_logged_in', None)
    return redirect(url_for('index'))


# ================================================
# Contributor Routes
# ================================================

@app.route('/colaborator/inregistrare', methods=['GET', 'POST'])
def contributor_register():
    """Contributor registration page."""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        bio = request.form.get('bio', '').strip()

        if not all([name, email, password]):
            return render_template('contributor_register.html', error='Completați toate câmpurile obligatorii.', categories=CATEGORIES)

        if len(password) < 6:
            return render_template('contributor_register.html', error='Parola trebuie să aibă minim 6 caractere.', categories=CATEGORIES)

        if '@' not in email or '.' not in email:
            return render_template('contributor_register.html', error='Adresa de email nu este validă.', categories=CATEGORIES)

        if get_contributor_by_email(email):
            return render_template('contributor_register.html', error='Există deja un cont cu această adresă de email.', categories=CATEGORIES)

        contributor = {
            'id': str(uuid.uuid4()),
            'name': name,
            'email': email,
            'password_hash': generate_password_hash(password),
            'bio': bio,
            'registered_date': datetime.now().isoformat(),
            'status': 'active',
            'article_count': 0,
        }

        contributors = load_contributors()
        contributors.append(contributor)
        save_contributors(contributors)

        session['contributor_id'] = contributor['id']
        session['contributor_name'] = contributor['name']
        return redirect(url_for('contributor_dashboard'))

    return render_template('contributor_register.html', categories=CATEGORIES)


@app.route('/colaborator/login', methods=['GET', 'POST'])
def contributor_login():
    """Contributor login page."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        contributor = get_contributor_by_email(email)
        if not contributor or not check_password_hash(contributor.get('password_hash', ''), password):
            return render_template('contributor_login.html', error='Email sau parolă incorectă.', categories=CATEGORIES)

        if contributor.get('status') == 'suspended':
            return render_template('contributor_login.html', error='Contul tău a fost suspendat. Contactează redacția.', categories=CATEGORIES)

        session['contributor_id'] = contributor['id']
        session['contributor_name'] = contributor['name']
        return redirect(url_for('contributor_dashboard'))

    return render_template('contributor_login.html', categories=CATEGORIES)


@app.route('/colaborator/logout')
def contributor_logout():
    """Logout contributor."""
    session.pop('contributor_id', None)
    session.pop('contributor_name', None)
    return redirect(url_for('index'))


@app.route('/colaborator/panou')
@contributor_required
def contributor_dashboard():
    """Contributor dashboard with their articles and stats."""
    cid = session['contributor_id']
    contributor = get_contributor_by_id(cid)
    if not contributor:
        session.pop('contributor_id', None)
        return redirect(url_for('contributor_login'))

    articles = load_contributor_articles(cid)
    stats = {
        'total': len(articles),
        'draft': sum(1 for a in articles if a.get('status') == 'draft'),
        'pending': sum(1 for a in articles if a.get('status') == 'pending'),
        'approved': sum(1 for a in articles if a.get('status') == 'approved'),
        'rejected': sum(1 for a in articles if a.get('status') == 'rejected'),
    }

    return render_template('contributor_dashboard.html',
                           contributor=contributor, articles=articles,
                           stats=stats, categories=CATEGORIES)


@app.route('/colaborator/scrie', methods=['GET', 'POST'])
@contributor_required
def contributor_write():
    """Contributor article writing form."""
    cid = session['contributor_id']
    contributor = get_contributor_by_id(cid)
    if not contributor:
        return redirect(url_for('contributor_login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        cat = request.form.get('category', '').strip()
        content = request.form.get('content', '').strip()
        image_url = request.form.get('image_url', '').strip()
        action = request.form.get('action', 'draft')

        if not all([title, cat, content]):
            return render_template('contributor_write.html',
                                   error='Completați titlul, categoria și conținutul.',
                                   categories=CATEGORIES,
                                   article_categories=ARTICLE_CATEGORIES)

        status = 'pending' if action == 'submit' else 'draft'

        article = {
            'id': str(uuid.uuid4()),
            'title': title,
            'slug': generate_slug(title),
            'category': cat,
            'type': 'local',
            'content': content,
            'excerpt': _truncate_at_sentence(content, 200),
            'meta_description': _truncate_at_sentence(content, 155),
            'image': image_url or None,
            'source': 'Colaborator KronPapir',
            'date': datetime.now().isoformat(),
            'author': contributor['name'],
            'contributor_id': cid,
            'contributor_name': contributor['name'],
            'status': status,
            'admin_notes': '',
            'submitted_date': datetime.now().isoformat() if status == 'pending' else '',
            'approved_date': '',
        }

        save_contributor_article(article)

        msg = 'Articolul a fost trimis spre aprobare!' if status == 'pending' else 'Ciorna a fost salvată.'
        return render_template('contributor_write.html',
                               success=msg, categories=CATEGORIES,
                               article_categories=ARTICLE_CATEGORIES)

    return render_template('contributor_write.html',
                           categories=CATEGORIES,
                           article_categories=ARTICLE_CATEGORIES)


@app.route('/colaborator/editeaza/<article_id>', methods=['GET', 'POST'])
@contributor_required
def contributor_edit(article_id):
    """Edit own contributor article."""
    cid = session['contributor_id']
    article = get_contributor_article(cid, article_id)
    if not article:
        abort(404)

    if article.get('status') == 'approved':
        return redirect(url_for('contributor_dashboard'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        cat = request.form.get('category', '').strip()
        content = request.form.get('content', '').strip()
        image_url = request.form.get('image_url', '').strip()
        action = request.form.get('action', 'draft')

        if not all([title, cat, content]):
            return render_template('contributor_edit.html', article=article,
                                   error='Completați titlul, categoria și conținutul.',
                                   categories=CATEGORIES,
                                   article_categories=ARTICLE_CATEGORIES)

        new_status = 'pending' if action == 'submit' else 'draft'

        article.update({
            'title': title,
            'slug': generate_slug(title),
            'category': cat,
            'content': content,
            'excerpt': _truncate_at_sentence(content, 200),
            'meta_description': _truncate_at_sentence(content, 155),
            'image': image_url or None,
            'status': new_status,
            'updated': datetime.now().isoformat(),
        })
        if new_status == 'pending':
            article['submitted_date'] = datetime.now().isoformat()

        save_contributor_article(article)

        msg = 'Articolul a fost retrimis spre aprobare!' if new_status == 'pending' else 'Ciorna a fost actualizată.'
        return render_template('contributor_edit.html', article=article,
                               success=msg, categories=CATEGORIES,
                               article_categories=ARTICLE_CATEGORIES)

    return render_template('contributor_edit.html', article=article,
                           categories=CATEGORIES,
                           article_categories=ARTICLE_CATEGORIES)


@app.route('/colaborator/sterge/<article_id>', methods=['POST'])
@contributor_required
def contributor_delete(article_id):
    """Delete own contributor article (only draft/rejected)."""
    cid = session['contributor_id']
    article = get_contributor_article(cid, article_id)
    if not article:
        return jsonify({'success': False, 'message': 'Articol negăsit'}), 404

    if article.get('status') not in ('draft', 'rejected'):
        return jsonify({'success': False, 'message': 'Articolul nu poate fi șters în starea curentă'}), 400

    article_file = CONTRIBUTOR_ARTICLES_DIR / cid / f"{article_id}.json"
    if article_file.exists():
        article_file.unlink()

    return jsonify({'success': True, 'message': 'Articol șters cu succes'})


@app.route('/colaborator/<contributor_id>')
def contributor_profile(contributor_id):
    """Public contributor profile page."""
    contributor = get_contributor_by_id(contributor_id)
    if not contributor or contributor.get('status') == 'suspended':
        abort(404)

    approved_articles = load_contributor_articles(contributor_id, status_filter='approved')

    return render_template('contributor_profile.html',
                           contributor=contributor,
                           articles=approved_articles,
                           categories=CATEGORIES)


# ================================================
# Admin Contributor Management
# ================================================

@app.route('/admin/colaboratori')
@admin_required
def admin_contributors():
    """List all contributors."""
    contributors = load_contributors()
    for c in contributors:
        c['_articles'] = load_contributor_articles(c['id'])
        c['_pending'] = sum(1 for a in c['_articles'] if a.get('status') == 'pending')
    return render_template('admin_contributors.html',
                           contributors=contributors, categories=CATEGORIES)


@app.route('/admin/colaboratori/articole')
@admin_required
def admin_contributor_articles():
    """Review contributor articles (filterable by status)."""
    status_filter = request.args.get('status', '').strip()
    if status_filter:
        articles = load_all_contributor_articles(status_filter=status_filter)
    else:
        articles = load_all_contributor_articles()

    return render_template('admin_contributor_articles.html',
                           articles=articles,
                           status_filter=status_filter,
                           categories=CATEGORIES)


@app.route('/admin/colaborator/aproba/<article_id>', methods=['POST'])
@admin_required
def admin_approve_contributor_article(article_id):
    """Approve a contributor article and copy to data/processed/."""
    all_arts = load_all_contributor_articles()
    article = None
    for a in all_arts:
        if a.get('id') == article_id:
            article = a
            break

    if not article:
        return jsonify({'success': False, 'message': 'Articol negăsit'}), 404

    # Update status in contributor storage
    article['status'] = 'approved'
    article['approved_date'] = datetime.now().isoformat()
    article['admin_notes'] = request.form.get('notes', '').strip()
    save_contributor_article(article)

    # Copy to data/processed/ for the live site
    published = {
        'id': article['id'],
        'title': article['title'],
        'seo_title': article['title'][:60],
        'slug': article.get('slug') or generate_slug(article['title']),
        'content': article['content'],
        'excerpt': article.get('excerpt') or _truncate_at_sentence(article['content'], 200),
        'meta_description': article.get('meta_description') or _truncate_at_sentence(article['content'], 155),
        'keywords': [],
        'category': article.get('category', 'social'),
        'type': 'local',
        'source': 'Colaborator KronPapir',
        'url': '',
        'image': article.get('image'),
        'date': article.get('date', datetime.now().isoformat()),
        'author': article.get('contributor_name', ''),
        'contributor_id': article.get('contributor_id', ''),
        'contributor_name': article.get('contributor_name', ''),
        'processed': True,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / f"{article['id']}.json", 'w', encoding='utf-8') as f:
        json.dump(published, f, ensure_ascii=False, indent=2)

    update_contributor_article_count(article.get('contributor_id', ''))

    return jsonify({'success': True, 'message': 'Articol aprobat și publicat!'})


@app.route('/admin/colaborator/respinge/<article_id>', methods=['POST'])
@admin_required
def admin_reject_contributor_article(article_id):
    """Reject a contributor article with feedback."""
    all_arts = load_all_contributor_articles()
    article = None
    for a in all_arts:
        if a.get('id') == article_id:
            article = a
            break

    if not article:
        return jsonify({'success': False, 'message': 'Articol negăsit'}), 404

    article['status'] = 'rejected'
    article['admin_notes'] = request.form.get('notes', '').strip()
    save_contributor_article(article)

    return jsonify({'success': True, 'message': 'Articol respins.'})


@app.route('/admin/colaborator/status/<contributor_id>', methods=['POST'])
@admin_required
def admin_contributor_status(contributor_id):
    """Suspend or activate a contributor."""
    new_status = request.form.get('status', '').strip()
    if new_status not in ('active', 'suspended'):
        return jsonify({'success': False, 'message': 'Status invalid'}), 400

    contributors = load_contributors()
    found = False
    for c in contributors:
        if c.get('id') == contributor_id:
            c['status'] = new_status
            found = True
            break

    if not found:
        return jsonify({'success': False, 'message': 'Colaborator negăsit'}), 404

    save_contributors(contributors)
    return jsonify({'success': True, 'message': f'Status schimbat la {new_status}'})


@app.context_processor
def inject_random_articles():
    """Inject random articles and AdSense config into all templates."""
    try:
        all_articles = load_articles()
        if len(all_articles) > 6:
            rand_articles = random.sample(all_articles, 6)
        else:
            rand_articles = all_articles
    except Exception:
        rand_articles = []

    # Contributor pending count for admin badge
    contributor_pending_count = 0
    if session.get('admin_logged_in'):
        try:
            contributor_pending_count = len(load_all_contributor_articles(status_filter='pending'))
        except Exception:
            pass

    return dict(
        random_articles=rand_articles,
        adsense_enabled=ADSENSE_ENABLED,
        adsense_client_id=ADSENSE_CLIENT_ID,
        google_search_console_token=GOOGLE_SEARCH_CONSOLE_TOKEN,
        ga4_enabled=GA4_ENABLED,
        ga4_measurement_id=GA4_MEASUREMENT_ID,
        contributor_pending_count=contributor_pending_count,
        contributor_logged_in=bool(session.get('contributor_id')),
        contributor_name=session.get('contributor_name', ''),
    )


@app.template_filter('article_url')
def article_url_filter(article):
    """Template filter to get the best URL for an article."""
    if article.get('slug'):
        return f"/stiri/{article['slug']}"
    return f"/articol/{article.get('id')}"


# SEO Routes

@app.route('/google633262e78845128b.html')
def google_verification():
    return 'google-site-verification: google633262e78845128b.html'


@app.route('/robots.txt')
def robots_txt():
    """Generate robots.txt file."""
    robots_content = """User-agent: *
Allow: /
Sitemap: https://kronpapir.ro/sitemap.xml
Sitemap: https://kronpapir.ro/news-sitemap.xml

User-agent: Googlebot
Allow: /
Crawl-delay: 1

User-agent: Bingbot
Allow: /
Crawl-delay: 1
"""
    return Response(robots_content, mimetype='text/plain')


@app.route('/sitemap.xml')
def sitemap_xml():
    """Generate sitemap.xml dynamically."""
    try:
        all_articles = load_articles(all_types=True)
    except Exception:
        all_articles = []

    sitemap_urls = []

    # Homepage
    sitemap_urls.append({
        'loc': 'https://kronpapir.ro/',
        'lastmod': datetime.now().strftime('%Y-%m-%d'),
        'changefreq': 'daily',
        'priority': '1.0'
    })

    # Static pages
    static_pages = [
        ('/local', 'daily', '0.8'),
        ('/national', 'daily', '0.7'),
        ('/editoriale', 'daily', '0.8'),
        ('/despre', 'monthly', '0.7'),
        ('/confidentialitate', 'monthly', '0.5'),
        ('/termeni', 'monthly', '0.5'),
        ('/contact', 'monthly', '0.5'),
    ]

    for page_url, changefreq, priority in static_pages:
        sitemap_urls.append({
            'loc': f'https://kronpapir.ro{page_url}',
            'lastmod': datetime.now().strftime('%Y-%m-%d'),
            'changefreq': changefreq,
            'priority': priority
        })

    # Category pages
    for category in CATEGORIES.keys():
        sitemap_urls.append({
            'loc': f'https://kronpapir.ro/categorie/{category}',
            'lastmod': datetime.now().strftime('%Y-%m-%d'),
            'changefreq': 'daily',
            'priority': '0.6'
        })

    # Contributor profile pages
    try:
        for contributor in load_contributors():
            if contributor.get('status') == 'active' and contributor.get('article_count', 0) > 0:
                sitemap_urls.append({
                    'loc': f"https://kronpapir.ro/colaborator/{contributor['id']}",
                    'lastmod': datetime.now().strftime('%Y-%m-%d'),
                    'changefreq': 'weekly',
                    'priority': '0.5'
                })
    except Exception:
        pass

    # Article pages
    for article in all_articles:
        article_slug = article.get('slug') or generate_slug(article.get('title', ''))
        article_date = article.get('date', datetime.now().isoformat())
        if 'T' in article_date:
            article_date = article_date.split('T')[0]

        sitemap_urls.append({
            'loc': f'https://kronpapir.ro/stiri/{article_slug}',
            'lastmod': article_date,
            'changefreq': 'weekly',
            'priority': '0.8'
        })

    # Generate XML
    sitemap_xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap_xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url in sitemap_urls:
        sitemap_xml_content += '  <url>\n'
        sitemap_xml_content += f'    <loc>{url["loc"]}</loc>\n'
        sitemap_xml_content += f'    <lastmod>{url["lastmod"]}</lastmod>\n'
        sitemap_xml_content += f'    <changefreq>{url["changefreq"]}</changefreq>\n'
        sitemap_xml_content += f'    <priority>{url["priority"]}</priority>\n'
        sitemap_xml_content += '  </url>\n'

    sitemap_xml_content += '</urlset>'

    return Response(sitemap_xml_content, mimetype='application/xml')


@app.route('/news-sitemap.xml')
def news_sitemap_xml():
    """Google News Sitemap — doar articole din ultimele 48h."""
    try:
        all_articles = load_articles(all_types=True)
    except Exception:
        all_articles = []

    cutoff = datetime.now() - timedelta(hours=48)

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
    xml += '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'

    for article in all_articles:
        article_date_str = article.get('date', '')
        try:
            if 'T' in article_date_str:
                article_date = datetime.fromisoformat(article_date_str.replace('Z', '+00:00').split('+')[0])
            else:
                article_date = datetime.strptime(article_date_str, '%Y-%m-%d')
        except (ValueError, TypeError):
            continue

        if article_date < cutoff:
            continue

        slug = article.get('slug') or generate_slug(article.get('title', ''))
        title = html_escape(article.get('title', ''))
        pub_date = article_date.strftime('%Y-%m-%dT%H:%M:%S+03:00')

        xml += '  <url>\n'
        xml += f'    <loc>https://kronpapir.ro/stiri/{slug}</loc>\n'
        xml += '    <news:news>\n'
        xml += '      <news:publication>\n'
        xml += '        <news:name>KronPapir</news:name>\n'
        xml += '        <news:language>ro</news:language>\n'
        xml += '      </news:publication>\n'
        xml += f'      <news:publication_date>{pub_date}</news:publication_date>\n'
        xml += f'      <news:title>{title}</news:title>\n'
        xml += '    </news:news>\n'
        xml += '  </url>\n'

    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


@app.route('/feed')
def rss_feed():
    """RSS 2.0 feed — ultimele 20 articole."""
    try:
        articles = load_articles(limit=20, all_types=True)
    except Exception:
        articles = []

    rss = '<?xml version="1.0" encoding="UTF-8"?>\n'
    rss += '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
    rss += '<channel>\n'
    rss += '  <title>KronPapir — Știri din Brașov</title>\n'
    rss += '  <link>https://kronpapir.ro</link>\n'
    rss += '  <description>Agregator de știri locale din județul Brașov, Transilvania</description>\n'
    rss += '  <language>ro</language>\n'
    rss += '  <atom:link href="https://kronpapir.ro/feed" rel="self" type="application/rss+xml"/>\n'
    rss += f'  <lastBuildDate>{datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0300")}</lastBuildDate>\n'
    rss += '  <image>\n'
    rss += '    <url>https://kronpapir.ro/static/images/og-image.png</url>\n'
    rss += '    <title>KronPapir</title>\n'
    rss += '    <link>https://kronpapir.ro</link>\n'
    rss += '  </image>\n'

    for article in articles:
        slug = article.get('slug') or generate_slug(article.get('title', ''))
        title = html_escape(article.get('title', ''))
        link = f'https://kronpapir.ro/stiri/{slug}'
        desc = html_escape(article.get('excerpt') or article.get('meta_description') or '')
        guid = article.get('id', slug)

        # Format pubDate per RFC 822
        date_str = article.get('date', '')
        try:
            if 'T' in date_str:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00').split('+')[0])
            else:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
            pub_date = dt.strftime('%a, %d %b %Y %H:%M:%S +0300')
        except (ValueError, TypeError):
            pub_date = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0300')

        rss += '  <item>\n'
        rss += f'    <title>{title}</title>\n'
        rss += f'    <link>{link}</link>\n'
        rss += f'    <description>{desc}</description>\n'
        rss += f'    <pubDate>{pub_date}</pubDate>\n'
        rss += f'    <guid isPermaLink="false">{guid}</guid>\n'
        if article.get('image'):
            rss += f'    <enclosure url="{html_escape(article["image"])}" type="image/jpeg"/>\n'
        rss += '  </item>\n'

    rss += '</channel>\n'
    rss += '</rss>'
    return Response(rss, mimetype='application/rss+xml')


@app.route('/kronpapir2026seo.txt')
def indexnow_key():
    """IndexNow key verification file."""
    return Response('kronpapir2026seo', mimetype='text/plain')


# Error handlers
@app.errorhandler(404)
def not_found(error):
    """404 error page."""
    return render_template('404.html', categories=CATEGORIES), 404


@app.errorhandler(500)
def server_error(error):
    """500 error page."""
    return render_template('500.html', categories=CATEGORIES), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
