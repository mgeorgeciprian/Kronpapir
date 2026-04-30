# KronPapir Admin Panel Setup Guide

## Overview

The KronPapir admin panel provides a complete article management system with authentication, CRUD operations, and automated pipeline scheduling.

## Features Implemented

### 1. Admin Panel Routes

- **`/admin`** - Dashboard with statistics and recent articles (requires authentication)
- **`/admin/login`** - Password-only login page
- **`/admin/logout`** - Logout endpoint
- **`/admin/scrie`** - Article creation form
- **`/admin/articol/editeaza/<article_id>`** - Article editing
- **`/admin/articole`** - Article management list with pagination
- **`/admin/articol/sterge/<article_id>`** - Article deletion (POST request)

### 2. Admin Templates

#### `admin_login.html`
- Clean password-only login form
- Error message display
- Links to contact/forgotten password
- Professional styling with inline CSS

#### `admin_dashboard.html`
- Statistics cards: Total Articles, Today's Articles, Recent Articles
- Quick action buttons (Write New, View All)
- List of 10 most recent articles with metadata
- Navigation tabs for all admin sections

#### `admin_write.html`
- Article creation form with fields:
  - Title (text input, max 300 chars)
  - Category (dropdown: politica, economie, sport, cultura, social, educatie, sanatate, evenimente, accidente)
  - Type (radio: local/national)
  - Content (large textarea with character counter)
  - Image URL (optional)
  - Source (text input)
- Preview button for seeing article as rendered
- Save/Preview/Clear buttons

#### `admin_edit.html`
- Full article editing interface
- Pre-populated form with current article data
- Same fields as write form
- Preview functionality
- Update/Preview/Cancel buttons

#### `admin_articles.html`
- Responsive table of all articles
- Columns: Title, Category, Type, Date, Source, Actions
- Pagination (20 articles per page)
- Actions: View, Edit, Delete
- Category and type badges with color coding
- Delete confirmation dialog

### 3. Authentication & Security

- Password-based admin access
- Admin password configured via `.env` file (default: `kronpapir2026`)
- Flask session-based authentication
- `@admin_required` decorator for protecting routes
- Session clearing on logout

### 4. Article Storage

- Articles stored as JSON files in `/data/processed/`
- Each article file named by UUID (e.g., `550e8400-e29b-41d4-a716-446655440000.json`)
- Article structure:
  ```json
  {
    "id": "uuid",
    "title": "Article Title",
    "content": "Full article content",
    "category": "politica",
    "type": "local",
    "image": "https://example.com/image.jpg",
    "source": "Admin",
    "date": "2026-02-10T15:48:30.123456",
    "author": "Redacția KronPapir",
    "updated": "2026-02-10T15:52:00.654321"
  }
  ```

## Setup Instructions

### 1. Environment Configuration

Create or update `.env` file in project root:

```bash
# Admin authentication
ADMIN_PASSWORD=kronpapir2026

# Flask configuration
FLASK_SECRET_KEY=your-secret-key-here
```

### 2. Initialize Admin Panel

The admin panel is automatically available once the Flask app is running. No additional setup needed.

### 3. Access Admin Panel

1. Navigate to `https://yoursite.com/admin`
2. You'll be redirected to `/admin/login`
3. Enter the admin password (from `.env`)
4. You'll be logged in and can access the dashboard

## Cron Setup

### Automated Pipeline Execution

The `setup_cron.sh` script automates article scraping every 3 hours.

#### Setup Instructions

1. Make script executable:
   ```bash
   chmod +x setup_cron.sh
   ```

2. Run the setup script:
   ```bash
   ./setup_cron.sh
   ```

3. The script will:
   - Verify Python venv at `/home/kronpapir/app/venv/bin/python`
   - Create logs directory at `/home/kronpapir/app/logs`
   - Add cron job to run `python run_pipeline.py full` every 3 hours
   - Log output to `/home/kronpapir/app/logs/cron.log`

#### Cron Job Details

- **Schedule**: Every 3 hours at minute 0 (00:00, 03:00, 06:00, etc.)
- **Command**: `source .env; /home/kronpapir/app/venv/bin/python /home/kronpapir/app/run_pipeline.py full`
- **Working Directory**: `/home/kronpapir/app`
- **Log File**: `/home/kronpapir/app/logs/cron.log`

#### Verify Cron Job

```bash
# List all cron jobs
crontab -l

# Should show something like:
# 0 */3 * * * cd /home/kronpapir/app && source .env 2>/dev/null; /home/kronpapir/app/venv/bin/python /home/kronpapir/app/run_pipeline.py full >> /home/kronpapir/app/logs/cron.log 2>&1
```

#### Remove Cron Job

```bash
crontab -e
# Find and delete the line containing "run_pipeline.py full"
```

## File Locations

### Admin Panel Files

```
kronpapir/
├── web/
│   └── app.py (modified with new routes)
├── templates/
│   ├── admin_login.html
│   ├── admin_dashboard.html
│   ├── admin_write.html
│   ├── admin_edit.html (NEW)
│   └── admin_articles.html
├── setup_cron.sh (NEW, executable)
└── ADMIN_SETUP.md (NEW)
```

### Data Storage

```
kronpapir/data/processed/
├── 550e8400-e29b-41d4-a716-446655440000.json
├── 550e8400-e29b-41d4-a716-446655440001.json
└── ... (more articles)
```

## Admin Features Usage

### Writing Articles

1. Go to `/admin`
2. Click "Scrie Articol" or navigate to `/admin/scrie`
3. Fill in all required fields (*)
4. Preview article using "Previzualizare" button
5. Click "Salvează Articol"

### Viewing Articles

1. Navigate to `/admin/articole`
2. Browse paginated list of articles
3. Click view icon (👁️) to see full article
4. Navigation buttons for previous/next pages

### Editing Articles

1. In article list, click edit icon (✏️)
2. Modify article fields
3. Preview changes with "Previzualizare"
4. Click "Actualizează Articol" to save

### Deleting Articles

1. In article list, click delete icon (🗑️)
2. Confirm deletion in dialog
3. Article is permanently removed

### Dashboard

- View total article count
- See today's article count
- Quick access links to all features
- List of 10 most recent articles

## Security Considerations

1. **Password Protection**
   - Always change `ADMIN_PASSWORD` from default in production
   - Store password in `.env` file, not in code

2. **Session Management**
   - Sessions expire when browser closes
   - Use HTTPS in production to protect session cookies
   - Set strong `FLASK_SECRET_KEY` in `.env`

3. **Article Access**
   - All admin routes require authentication
   - Non-authenticated users redirected to login

4. **Data Backup**
   - Articles are stored as JSON files
   - Regularly backup `/data/processed/` directory
   - Consider version control for article storage

## Troubleshooting

### Can't access admin panel

- Ensure Flask app is running
- Check password in `.env` file
- Clear browser cookies and try again

### Articles not saving

- Verify `/data/processed/` directory exists and is writable
- Check Flask error logs for detailed messages
- Ensure required fields are filled (marked with *)

### Cron job not running

```bash
# Check cron logs
grep CRON /var/log/syslog | tail -20

# Verify .env file is readable
ls -la /home/kronpapir/app/.env

# Test cron manually
cd /home/kronpapir/app && source .env && /home/kronpapir/app/venv/bin/python /home/kronpapir/app/run_pipeline.py full
```

### Preview not working

- Check browser console for JavaScript errors
- Ensure JavaScript is enabled
- Try clearing browser cache

## Database Schema

### Article JSON Structure

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Titlul articolului",
  "content": "Conținutul complet al articolului",
  "category": "politica",
  "type": "local",
  "image": "https://example.com/image.jpg",
  "source": "Admin",
  "date": "2026-02-10T15:48:30.123456",
  "author": "Redacția KronPapir",
  "updated": "2026-02-10T15:52:00.654321"
}
```

### Available Categories

- politica (Politică)
- economie (Economie)
- sport (Sport)
- cultura (Cultură)
- social (Social)
- educatie (Educație)
- sanatate (Sănătate)
- evenimente (Evenimente)
- accidente (Accidente)

## Future Enhancements

Possible improvements for future versions:

1. User management (multiple admin accounts)
2. Article scheduling (publish at specific time)
3. Article versioning/history
4. Bulk import/export
5. Search and advanced filtering
6. Article statistics and analytics
7. Comment moderation
8. Two-factor authentication
9. API access tokens
10. Activity logging

## Support

For issues or questions about the admin panel, contact: redactia@kronpapir.ro
