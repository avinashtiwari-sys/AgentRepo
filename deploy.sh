#!/bin/bash
# GTMFlow — EC2 deployment script
# Run once on your AWS machine: bash deploy.sh

set -e
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Detecting OS..."
if [ -f /etc/debian_version ]; then
    PKG="apt"
    sudo apt update -y
    sudo apt install -y python3 python3-venv redis-server nginx
elif [ -f /etc/amazon-linux-release ] || [ -f /etc/system-release ]; then
    PKG="yum"
    sudo yum install -y python3 redis nginx
fi

echo "==> Starting Redis..."
sudo systemctl enable redis && sudo systemctl start redis

echo "==> Setting up Python venv..."
cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install . -q

echo "==> Setting up .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  !! .env created from .env.example"
    echo "  !! Edit it now:  nano $APP_DIR/.env"
    echo "  !! Then re-run:  bash deploy.sh"
    exit 1
fi

echo "==> Installing systemd services..."
USER_NAME=$(whoami)

sudo tee /etc/systemd/system/gtmflow-web.service > /dev/null <<EOF
[Unit]
Description=GTMFlow Web Server
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/gtmflow-worker.service > /dev/null <<EOF
[Unit]
Description=GTMFlow RQ Worker
After=network.target redis.service

[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/rq worker pipeline
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable gtmflow-web gtmflow-worker
sudo systemctl restart gtmflow-web gtmflow-worker

echo "==> Configuring Nginx..."
sudo cp "$APP_DIR/nginx.conf" /etc/nginx/conf.d/gtmflow.conf
sudo nginx -t && sudo systemctl enable nginx && sudo systemctl restart nginx

echo ""
echo "=========================================="
echo "  GTMFlow deployed successfully!"
echo ""
echo "  Health check:"
echo "  curl http://localhost/health"
echo ""
echo "  Zoho webhook URL:"
echo "  http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)/webhook/zoho"
echo "=========================================="
