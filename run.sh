#!/usr/bin/env bash
#
# run.sh — one-command local/dev bootstrap + run for GTMFlow
#
# Steps:
#   1. Install system packages
#   2. Enable + start Redis
#   3. Create venv and install dependencies (from pyproject.toml / uv.lock)
#   4. Apply DB migrations
#   5. Start the web server + background worker
#
set -euo pipefail

# Run from the directory this script lives in, so relative paths work
cd "$(dirname "$0")"

VENV_DIR=".venv"

# ---------------------------------------------------------------------------
echo "==> Updating apt and installing system packages..."
sudo apt update
sudo apt install -y \
    libffi-dev \
    python3 \
    python3-dev \
    python3-venv \
    build-essential \
    curl \
    git \
    libssl-dev \
    ufw \
    python3-pip \
    redis-server \
    nginx

# ---------------------------------------------------------------------------
echo "==> Enabling Redis..."
sudo systemctl enable redis-server
sudo systemctl start redis-server

# ---------------------------------------------------------------------------
echo "==> Creating Python venv and installing dependencies..."
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip

# This repo uses pyproject.toml + uv.lock — there is no requirements.txt.
if command -v uv >/dev/null 2>&1; then
    echo "    uv found — syncing from uv.lock"
    uv sync
else
    echo "    uv not found — installing project with pip (-e .)"
    pip install -e .
fi

# ---------------------------------------------------------------------------
# The app fails fast at boot if ZOHO_WEBHOOK_SECRET / ANTHROPIC_API_KEY are
# missing. Make sure a .env exists before we try to start anything.
if [ ! -f ".env" ]; then
    echo "ERROR: no .env file found."
    echo "       Copy the template and fill it in:  cp .env.example .env && nano .env"
    exit 1
fi

# ---------------------------------------------------------------------------
echo "==> Applying database migrations..."
alembic upgrade head

# ---------------------------------------------------------------------------
echo "==> Starting background worker..."
rq worker pipeline &
WORKER_PID=$!

# Clean up the worker if the web server exits or this script is interrupted
trap 'echo "==> Stopping worker ($WORKER_PID)..."; kill "$WORKER_PID" 2>/dev/null || true' EXIT INT TERM

echo "==> Starting web server (http://0.0.0.0:8000)..."
uvicorn app.main:app --host 0.0.0.0 --port 8000
