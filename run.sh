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
# Clean up any lingering processes from a previous run (zombie workers, stale
# uvicorn instances, etc.) before starting fresh. This prevents the "multiple
# workers / no worker / port in use" bugs that happen on repeated restarts.
PIDFILE_WORKER="/tmp/gtmflow-worker.pid"
PIDFILE_WEB="/tmp/gtmflow-web.pid"

kill_existing() {
    local name="$1" pidfile="$2" pattern="$3" pids
    if [ -f "$pidfile" ]; then
        local old_pid
        old_pid=$(cat "$pidfile" 2>/dev/null || echo "")
        if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
            echo "==> Stopping old $name (PID $old_pid)..."
            kill "$old_pid" 2>/dev/null || true
            # Wait up to 5s for clean shutdown
            for _ in $(seq 1 5); do
                kill -0 "$old_pid" 2>/dev/null || break
                sleep 1
            done
            kill -9 "$old_pid" 2>/dev/null || true
        fi
    fi
    # Also kill any orphaned processes (handles stale pids or manual launches)
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "==> Cleaning up stray $name processes: $pids"
        kill $pids 2>/dev/null || true
        sleep 1
        pids=$(pgrep -f "$pattern" 2>/dev/null || true)
        [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
    fi
}

kill_existing "rq worker" "$PIDFILE_WORKER" "rq worker pipeline"
kill_existing "uvicorn" "$PIDFILE_WEB" "uvicorn app.main:app"

# Small delay so the port is definitely released before uvicorn binds
sleep 1

# ---------------------------------------------------------------------------
echo "==> Starting background worker..."
rq worker pipeline &
WORKER_PID=$!
echo "$WORKER_PID" > "$PIDFILE_WORKER"
echo "    worker PID $WORKER_PID — started"

echo "==> Starting web server (http://0.0.0.0:8000)..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!
echo "$UVICORN_PID" > "$PIDFILE_WEB"
echo "    uvicorn PID $UVICORN_PID — started"

# Wait briefly to let uvicorn bind (or fail fast if port is stuck)
sleep 2
if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "ERROR: uvicorn failed to start. Check logs above."
    exit 1
fi

echo ""
echo "=========================================="
echo "  GTMFlow is running"
echo ""
echo "  Web server:  http://0.0.0.0:8000"
echo "  Worker:      PID $WORKER_PID"
echo ""
echo "  To stop:     kill $WORKER_PID $UVICORN_PID"
echo "  To restart:  bash $0"
echo "=========================================="

# Wait for either process to exit, then clean up the other
wait -n "$WORKER_PID" "$UVICORN_PID" 2>/dev/null || true
echo "==> One process exited — shutting down..."
kill "$WORKER_PID" "$UVICORN_PID" 2>/dev/null || true
rm -f "$PIDFILE_WORKER" "$PIDFILE_WEB"
