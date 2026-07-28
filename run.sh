#!/usr/bin/env bash
#
# run.sh — restart GTMFlow daemons (worker + web server)
#
# This script is meant to be run from any terminal — it fully detaches both
# processes so they survive the terminal being closed.
#
# On first run it also bootstraps the environment (venv, deps, etc.). On
# subsequent runs it skips straight to stopping old processes and starting
# fresh ones.
#
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"
LOG_DIR="logs/$(date +%Y-%m-%d)"
mkdir -p "$LOG_DIR"

PIDFILE_WORKER="/tmp/gtmflow-worker.pid"
PIDFILE_WEB="/tmp/gtmflow-web.pid"

# ── Bootstrap (only if venv is missing) ────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Bootstrapping environment (first run)..."

    sudo apt update
    sudo apt install -y \
        libffi-dev python3 python3-dev python3-venv build-essential \
        curl git libssl-dev ufw python3-pip redis-server nginx

    sudo systemctl enable redis-server
    sudo systemctl start redis-server

    python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    python -m pip install --upgrade pip -q

    if command -v uv >/dev/null 2>&1; then
        uv sync
    else
        pip install -e . -q
    fi

    echo "==> Bootstrap complete."
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── Guard: .env must exist ─────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "ERROR: no .env file found."
    echo "       cp .env.example .env && nano .env"
    exit 1
fi

# ── Migrations ─────────────────────────────────────────────────────────
echo "==> Applying database migrations..."
alembic upgrade head

# ═══════════════════════════════════════════════════════════════════════
#  STOP
# ═══════════════════════════════════════════════════════════════════════
echo "==> Stopping existing GTMFlow services..."

# 1. systemd services (from deploy.sh)
for svc in gtmflow-web gtmflow-worker; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        echo "    Stopping systemd service: $svc"
        sudo systemctl stop "$svc" 2>/dev/null || true
        for _ in $(seq 1 10); do
            systemctl is-active --quiet "$svc" 2>/dev/null || break
            sleep 0.5
        done
        sudo systemctl kill "$svc" 2>/dev/null || true
        echo "    $svc stopped"
    fi
done

# 2. Orphaned processes by pattern
_kill_by_pattern() {
    local name="$1" pattern="$2"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    [ -z "$pids" ] && return
    echo "    Killing $name: $pids"
    kill $pids 2>/dev/null || true
    sleep 1
    pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
}

_kill_by_pattern "rq worker"    "rq worker pipeline"
_kill_by_pattern "uvicorn"      "uvicorn app.main:app"
_kill_by_pattern "gunicorn"     "gunicorn.*gtmflow"
_kill_by_pattern "supervisord"  "supervisord.*gtmflow"

# 3. Anything holding port 8000
PORT_PID=$(sudo lsof -ti :8000 2>/dev/null || true)
if [ -n "$PORT_PID" ]; then
    echo "    Killing port 8000 holder(s): $PORT_PID"
    kill $PORT_PID 2>/dev/null || true
    sleep 1
    PORT_PID=$(sudo lsof -ti :8000 2>/dev/null || true)
    [ -n "$PORT_PID" ] && kill -9 $PORT_PID 2>/dev/null || true
    echo "    Port 8000 freed"
fi

# 4. Cleanup
rm -f "$PIDFILE_WORKER" "$PIDFILE_WEB"
sleep 1

if sudo lsof -ti :8000 &>/dev/null; then
    echo "ERROR: Port 8000 still in use. Aborting."
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════════
#  START (fully detached from terminal)
# ═══════════════════════════════════════════════════════════════════════

# Worker
_log="$LOG_DIR/worker.log"
nohup rq worker pipeline > "$_log" 2>&1 &
WPID=$!
echo "$WPID" > "$PIDFILE_WORKER"
disown "$WPID"
echo "    worker PID $WPID — started (log: $_log)"

# Web server
_log="$LOG_DIR/web.log"
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$_log" 2>&1 &
UPID=$!
echo "$UPID" > "$PIDFILE_WEB"
disown "$UPID"
echo "    uvicorn PID $UPID — started  (log: $_log)"

# Quick sanity check
sleep 2
if ! kill -0 "$UPID" 2>/dev/null; then
    echo "ERROR: uvicorn failed to start. Check: $_log"
    exit 1
fi

echo ""
echo "=========================================="
echo "  GTMFlow is running"
echo ""
echo "  Web server:  http://0.0.0.0:8000"
echo "  Worker:      PID $WPID"
echo ""
echo "  Logs:        $LOG_DIR/{web,worker}.log"
echo "  PID files:   $PIDFILE_WEB"
echo "               $PIDFILE_WORKER"
echo ""
echo "  To stop:     kill $WPID $UPID"
echo "  To restart:  bash run.sh"
echo "=========================================="
