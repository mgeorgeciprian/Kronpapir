#!/bin/bash
# KronPapir.ro - Cron Setup
# 5 joburi zilnice:
#   06:00 - Scrape + 5 articole locale (dimineața)
#   14:00 - Scrape + 5 articole locale (după-amiaza)
#   22:00 - Editoriale zilnice (3 editoriale: național, internațional, tematic)

set -e

APP_DIR="/home/kronpapir/app"
VENV_PYTHON="$APP_DIR/venv/bin/python"
PIPELINE="$APP_DIR/run_pipeline.py"
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
crontab -l 2>/dev/null | grep -v "run_pipeline.py" | crontab -

# Adaugă cele 3 cron jobs
(crontab -l 2>/dev/null; cat <<CRONEOF

# === KronPapir.ro - Pipeline Automat ===
# Dimineata 06:00 - Scrape + 5 articole locale
0 6 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE full >> $LOG_DIR/cron_morning.log 2>&1

# Dupa-amiaza 14:00 - Scrape + 5 articole locale
0 14 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE full >> $LOG_DIR/cron_afternoon.log 2>&1

# 08:00 si 17:00 - Agent Reporter: stiri originale din comunicate oficiale
0 8 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE report >> $LOG_DIR/cron_reporter.log 2>&1
0 17 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE report >> $LOG_DIR/cron_reporter.log 2>&1

# Seara 22:00 - Editoriale zilnice (Andrei Varga)
0 22 * * * cd $APP_DIR && ${ENV_LOAD}$VENV_PYTHON $PIPELINE editorial >> $LOG_DIR/cron_editorial.log 2>&1
CRONEOF
) | crontab -

echo "✅ Cron jobs configurate cu succes!"
echo ""
echo "Program zilnic KronPapir.ro:"
echo "  06:00 - Scrape + 5 articole locale rescrise AI"
echo "  14:00 - Scrape + 5 articole locale rescrise AI"
echo "  08:00 - Reporter: meteo + pana la 5 stiri originale din comunicate oficiale"
echo "  17:00 - Reporter: pana la 5 stiri originale din comunicate oficiale"
echo "  22:00 - 3 editoriale: national + international + tematic"
echo ""
echo "Total zilnic: ~10 articole locale + 3 editoriale = 13 articole/zi"
echo "Modele: Sonnet 5.5 (știri) + Opus 5.5 (editoriale) — vezi CLAUDE_MODEL / CLAUDE_EDITORIAL_MODEL în .env"
echo ""
echo "Verifica cu: crontab -l"
echo ""
echo "Pentru a elimina cron-urile:"
echo "  crontab -l | grep -v 'run_pipeline.py' | crontab -"
