# KronPapir Frontend - Complete Web Application

This is the professional frontend for KronPapir, a Romanian local news aggregator focused on Brașov/Covasna region.

## Files Created

### Core Application
- **web/app.py** - Flask web server with all routes and API endpoints
- **requirements.txt** - Python dependencies (Flask, Jinja2, Werkzeug)
- **run.sh** - Startup script for the application

### Templates (HTML/Jinja2)
- **templates/base.html** - Main layout template with header/footer
- **templates/index.html** - Homepage with featured article and latest news
- **templates/local.html** - Local news page with pagination
- **templates/national.html** - National news page
- **templates/category.html** - Category pages with filtered articles
- **templates/article.html** - Single article page with sharing options
- **templates/about.html** - About/Transparency page
- **templates/404.html** - 404 error page
- **templates/500.html** - 500 error page

### Styling
- **static/css/style.css** - Modern newspaper design CSS (3500+ lines)
  - Dark green + cream color scheme
  - Responsive mobile-first design
  - Dark mode support
  - Print-friendly styles
  - Accessibility features

### Sample Data
- **data/processed/sample.json** - 8 sample articles for testing

## Features Implemented

✅ Professional newspaper design
✅ Responsive layout (mobile/tablet/desktop)
✅ 8 article categories
✅ Pagination system
✅ Dark mode support
✅ SEO optimization (meta tags, Open Graph)
✅ JSON API endpoint
✅ Share buttons (Facebook, Twitter, Copy, Print)
✅ Breaking news ticker
✅ Newsletter signup widget
✅ Weather widget placeholder
✅ Related articles suggestion
✅ Source attribution
✅ Search-friendly URLs
✅ Accessibility compliant (WCAG)

## Color Scheme

| Element | Color |
|---------|-------|
| Primary (Nav, Links) | #1a472a (Dark Green) |
| Secondary (Hover) | #2d6a42 (Medium Green) |
| Accent (Breaking News) | #c41e3a (Red) |
| Background | #f5f0e8 (Cream) |
| Text Primary | #1a1a1a (Black) |
| Text Secondary | #666666 (Gray) |

## Typography

- **Headlines**: Playfair Display (Google Fonts)
- **Body**: Inter (Google Fonts)
- **Code**: Courier New

## Routes

| Route | Description |
|-------|-------------|
| `/` | Homepage with latest articles |
| `/local` | All local news with pagination |
| `/national` | National news summary |
| `/categorie/<cat>` | Articles by category |
| `/articol/<id>` | Full article page |
| `/despre` | About/Transparency page |
| `/api/articles` | JSON API |

## JSON Article Structure

```json
{
  "id": "1",
  "title": "Article Title",
  "excerpt": "Short summary",
  "content": "Full HTML content",
  "category": "politica|economie|cultura|sport|sanatate|social|mediu|local",
  "date": "2024-02-08",
  "source": "Publication Name",
  "type": "local|national",
  "author": "Author Name",
  "image": "https://...",
  "url": "https://original-article"
}
```

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Place article JSON files in `data/processed/`

3. Run the server:
   ```bash
   cd web
   python app.py
   ```

4. Access at: http://localhost:5000

## API Usage

```bash
# Get local news (page 1, 20 per page)
curl "http://localhost:5000/api/articles?page=1&type=local"

# Get specific category
curl "http://localhost:5000/api/articles?category=politica"

# Custom limit
curl "http://localhost:5000/api/articles?limit=50"
```

## Responsive Breakpoints

- **Mobile**: < 768px
- **Tablet**: 768px - 1024px  
- **Desktop**: > 1024px

## Dark Mode

Automatically enabled via:
```css
@media (prefers-color-scheme: dark)
```

## Performance Optimizations

✅ Lazy loading for images
✅ CSS grid for efficient layout
✅ Minimal inline styles
✅ Semantic HTML5
✅ Optimized font loading

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Mobile)

## Future Enhancements

- [ ] Push notifications
- [ ] User accounts & personalization
- [ ] Full-text search
- [ ] Comments system
- [ ] AI-powered recommendations
- [ ] Mobile app
- [ ] Social media integration

---

**Created for KronPapir - Știri din inima Transilvaniei**
