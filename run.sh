#!/bin/bash

# KronPapir - Startup Script

echo "╔════════════════════════════════════════════╗"
echo "║        KronPapir - News Aggregator         ║"
echo "║      Știri din inima Transilvaniei         ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "Starting KronPapir server..."
echo "Access the site at: http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

cd web
python3 app.py
