#!/bin/bash
# ============================================
# DMX Controller - Manual Start Script
# Use this for development or running outside systemd.
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load environment file if it exists (API token, config path)
ENV_FILE="/etc/dmx/dmx.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Activate virtual environment if present
if [ -d "venv" ]; then
    source venv/bin/activate
fi

exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
