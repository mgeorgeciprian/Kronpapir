"""
KronPapir - Romanian Local News Aggregator
Brașov/Covasna Area
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, jsonify, request, abort, session, redirect, url_for

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['JSON_SORT_KEYS'] = False
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'kronpapir-secret-key-change-this')

# Configuration
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data' / 'processed'

# Admin configuration
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'kronpapir2026')

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

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


def load_articles(limit=None, category=None, is_national=False):
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

    # Filter by category
    if category:
        articles = [a for a in articles if a.get('category', '').lower() == category.lower()]

    # Filter by national/local
    if is_national:
        articles = [a for a in articles if a.get('type', 'local') == 'national']
    else:
        articles = [a for a in articles if a.get('type', 'local') != 'national']

    # Sort by date
    articles = sorted(articles, key=lambda x: x.get('date', ''), reverse=True)

    # Limit results
    if limit:
        articles = articles[:limit]

    return articles


@app.route('/')
def index():
    """Homepage - latest local news with national summary sidebar."""
    local_articles = load_articles(limit=10, is_national=False)
    national_articles = load_articles(limit=5, is_national=True)
    featured = local_articles[0] if local_articles else None
    latest = local_articles[1:7] if len(local_articles) > 1 else []
    most_read = local_articles[7:10] if len(local_articles) > 7 else []

    return render_template(
        'index.html',
        featured=featured,
        latest=latest,
        national=national_articles,
        most_read=most_read,
        categories=CATEGORIES
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
    all_articles = load_articles()

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

    return render_template(
        'article.html',
        article=current_article,
        related=related,
        categories=CATEGORIES
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

    return render_template(
        'admin_dashboard.html',
        total_articles=len(all_articles),
        today_articles=len(today_articles),
        recent_articles=recent_articles,
        categories=CATEGORIES
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
    """List all articles with edit/delete options."""
    page = request.args.get('page', 1, type=int)
    per_page = 20

    all_articles = load_articles()
    total = len(all_articles)
    start = (page - 1) * per_page
    end = start + per_page
    articles = all_articles[start:end]

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'admin_articles.html',
        articles=articles,
        page=page,
        total_pages=total_pages,
        total=total,
        categories=CATEGORIES
    )


@app.route('/admin/logout')
def admin_logout():
    """Logout from admin panel."""
    session.clear()
    return redirect(url_for('index'))


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
