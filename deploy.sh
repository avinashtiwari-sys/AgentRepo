#!/bin/bash
# =============================================================================
# GTMFlow — Deployment Script (Ubuntu 20.04)
# Usage: cd ~/AgentRepo && bash deploy.sh
# =============================================================================
set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}==>${NC} $*"; }
warn()  { echo -e "${YELLOW}WARN:${NC} $*"; }
die()   { echo -e "${RED}ERROR:${NC} $*" >&2; exit 1; }
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="$(whoami)"
[ -f "$APP_DIR/requirements.txt" ] || die "Run from inside AgentRepo folder."
info "Pulling latest code from GitHub..."
git -C "$APP_DIR" stash
git -C "$APP_DIR" pull
info "Setting up Python venv..."
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
source "$APP_DIR/.venv/bin/activate"
pip install --upgrade pip wheel -q
pip install -r "$APP_DIR/requirements.txt" -q
deactivate
info "Python dependencies installed."
info "Checking .env..."
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  warn ".env created — fill in secrets: nano $APP_DIR/.env"
  echo "Then re-run: bash deploy.sh"
  exit 1
fi
chmod 600 "$APP_DIR/.env"
grep -q '^DATABASE_URL=' "$APP_DIR/.env" || echo "DATABASE_URL=sqlite:///$APP_DIR/gtmflow.db" >> "$APP_DIR/.env"
info "Checking Redis..."
sudo systemctl is-active --quiet redis-server || {
  warn "Redis not running — starting..."
  sudo systemctl start redis-server
  sleep 2
  sudo systemctl is-active --quiet redis-server || die "Redis failed. Run fresh_setup.sh first."
}
redis-cli ping | grep -q PONG && info "Redis OK." || die "Redis not responding."
info "Checking SSL certificates..."
[ -f /etc/ssl/ssl_bundle.crt ] || die "SSL cert not found at /etc/ssl/ssl_bundle.crt"
[ -f /etc/ssl/server.key ]     || die "SSL key not found at /etc/ssl/server.key"
info "SSL certs found."
info "Installing systemd service: gtmflow-web..."
sudo tee /etc/systemd/system/gtmflow-web.service > /dev/null <<EOF
[Unit]
Description=GTMFlow FastAPI Web Server
After=network.target redis-server.service
[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --log-level info
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$APP_DIR
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
info "Installing systemd service: gtmflow-worker..."
sudo tee /etc/systemd/system/gtmflow-worker.service > /dev/null <<EOF
[Unit]
Description=GTMFlow RQ Pipeline Worker
After=network.target redis-server.service
[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/rq worker pipeline
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ReadWritePaths=$APP_DIR
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable gtmflow-web gtmflow-worker
sudo systemctl restart gtmflow-web gtmflow-worker
sleep 3
for svc in gtmflow-web gtmflow-worker; do
  sudo systemctl is-active --quiet "$svc" && info "$svc is running." || die "$svc failed. Check: journalctl -u $svc -n 50 --no-pager"
done
info "Installing Nginx site: gtmflow..."
[ -f "$APP_DIR/nginx/gtmflow.conf" ] || die "Nginx config not found at $APP_DIR/nginx/gtmflow.conf"
sudo cp "$APP_DIR/nginx/gtmflow.conf" /etc/nginx/sites-available/gtmflow
sudo ln -sf /etc/nginx/sites-available/gtmflow /etc/nginx/sites-enabled/gtmflow
[ -L /etc/nginx/sites-enabled/default ] && sudo rm /etc/nginx/sites-enabled/default && info "Removed Nginx default site."
sudo nginx -t || die "Nginx config test failed."
sudo systemctl enable --now nginx
sudo systemctl reload nginx
info "Nginx reloaded."
sleep 2
HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health || true)
[ "$HTTP_CODE" = "200" ] && info "Health check passed (HTTP 200)." || warn "Health check returned HTTP $HTTP_CODE"
echo ""
echo -e "\033[0;32m============================================\033[0m"
echo -e "\033[0;32m GTMFlow deployed successfully!\033[0m"
echo "  Health:  curl http://127.0.0.1:8000/health"
echo "  Webhook: https://gtmflow.pcloudy.com/webhook/zoho"
echo "  Logs:    sudo journalctl -fu gtmflow-web"
echo -e "\033[0;32m============================================\033[0m"
