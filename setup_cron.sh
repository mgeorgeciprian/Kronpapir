#!/bin/bash
# KronPapir.ro - Cron Setup
# Joburi programate:
#   06:00 - Scrape + 5 articole locale (dimineața)
#   14:00 - Scrape + 5 articole locale (după-amiaza)
#   22:00 - Editoriale zilnice (3 editoriale: național, internațional, tematic)
#   03:30 - Arhivare/compresie articole (zilnic)
#   04:30 - Audit SEO (duminica)

set -e

APP_DIR="/home/kronpapir/app"
VENV_PYTHON="$APP_DIR/venv/bin/python"
PIPELINE="$APP_DIR/run_pipeline.py"
ARCHIVE="$APP_DIR/archive_articles.py"
SEO_AUDIT="$APP_DIR/seo_audit.py"
LOG_DIR="$APP_DIR/logs"
ENV_FILE="$APP_DIR/.env"

# Verifică că fișierele necesare există
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ Python venv not found at $VENV_PYTHON"
    exit 1
fi

mkdir -p "$LOG_DIR"

# Construiește comanda cu încărcare .env
ENV_LOAD=""
if [ -f "$ENV_FILE" ]; then
    ENV_LOAD="set -a && source $ENV_FILE && set +a && "
fi

# Elimină cron-urile vechi KronPapir
crontab -l 2>/dev/null | grep -v -e "run_pipeline.py" -e "archive_articles.py" -e "seo_audit.py" -e "KronPapir.ro - " | crontab -

# Adaugă cron jobs
(crontab -l 2>/dev/null; cat <<CRONEOF

# === KronPapir.ro - Pipeline Automat ===
# Dimineata 06:00 - Scrape + 5 articole locale
0 6 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE full >> $LOG_DIR/cron_morning.log 2>&1

# Dupa-amiaza 14:00 - Scrape + 5 articole locale
0 14 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE full >> $LOG_DIR/cron_afternoon.log 2>&1

# Seara 22:00 - Editoriale zilnice (Andrei Varga)
0 22 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE editorial >> $LOG_DIR/cron_editorial.log 2>&1

# Noaptea 03:30 - Arhivare brute vechi + compresie procesate >30 zile
30 3 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $ARCHIVE >> $LOG_DIR/cron_archive.log 2>&1

# Duminica 04:30 - Audit SEO
30 4 * * 0 cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $SEO_AUDIT >> $LOG_DIR/cron_seo_audit.log 2>&1
CRONEOF
) | crontab -

echo "✅ Cron jobs configurate cu succes!"
echo ""
echo "Program zilnic KronPapir.ro:"
echo "  06:00 - Scrape + 5 articole locale rescrise AI"
echo "  14:00 - Scrape + 5 articole locale rescrise AI"
echo "  22:00 - 3 editoriale: national + international + tematic"
echo "  03:30 - Arhivare/compresie articole vechi"
echo "  04:30 - Audit SEO (doar duminica)"
echo ""
echo "Total zilnic: ~10 articole locale + 3 editoriale = 13 articole/zi"
echo "Cost estimat: ~0.05-0.10 USD/zi (Claude Haiku)"
echo ""
echo "Verifica cu: crontab -l"
echo ""
echo "Pentru a elimina cron-urile:"
echo "  crontab -l | grep -v -e 'run_pipeline.py' -e 'archive_articles.py' -e 'seo_audit.py' | crontab -"
