# ===== reset_fleet.sh =====
set -euo pipefail

echo "🔎 Running as: $(whoami)"
echo "📍 Project root assumed: /home/thermo/Thermo"
echo "📦 Venv assumed: /home/thermo/Thermo/venv"
echo "🌐 Nginx site name: fleet"

PROJECT_DIR="/home/thermo/Thermo"
VENV_DIR="$PROJECT_DIR/venv"
WSGI_MODULE="transport_mgmt.wsgi:application"
SERVICE_NAME="fleet"
ENV_FILE="/etc/fleet.env"
NGINX_SITE="/etc/nginx/sites-available/$SERVICE_NAME.conf"
NGINX_LINK="/etc/nginx/sites-enabled/$SERVICE_NAME.conf"
SYSTEMD_UNIT="/etc/systemd/system/$SERVICE_NAME.service"

# 0) Sanity checks
[ -x "$VENV_DIR/bin/gunicorn" ] || { echo "❌ $VENV_DIR/bin/gunicorn not found"; exit 1; }
[ -d "$PROJECT_DIR" ] || { echo "❌ $PROJECT_DIR not found"; exit 1; }

echo "🧹 Step 1: Stop and remove any auto-spawners"

# A) Stop our managed service (if exists)
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true

# B) Kill ALL gunicorns (twice, just to be sure)
sudo pkill -f 'gunicorn' || true
sleep 1
sudo pkill -9 -f 'gunicorn' || true

# C) Disable and MASK any leftover systemd services that mention gunicorn (except our target name—we'll rewrite it)
echo "🔎 Searching for systemd units that mention gunicorn…"
HITS=$(grep -RIl "gunicorn" /etc/systemd/system /lib/systemd/system ~/.config/systemd/user 2>/dev/null || true)
if [ -n "${HITS}" ]; then
  echo "$HITS" | while read -r FILE; do
    UNIT="$(basename "$FILE")"
    # Skip our target unit; we'll overwrite it later anyway
    if [[ "$UNIT" != "$SERVICE_NAME.service" ]]; then
      NAME="${UNIT%.service}"
      echo "🚫 Disabling and masking unit: $NAME"
      sudo systemctl stop "$NAME" 2>/dev/null || true
      sudo systemctl disable "$NAME" 2>/dev/null || true
      sudo systemctl mask "$NAME" 2>/dev/null || true
    fi
  done
fi

# D) Supervisor (if installed)
if command -v supervisorctl >/dev/null 2>&1; then
  echo "🔎 Checking Supervisor for gunicorn programs…"
  SUP_HITS=$(grep -RIl "gunicorn" /etc/supervisor* 2>/dev/null || true)
  if [ -n "${SUP_HITS}" ]; then
    echo "$SUP_HITS" | while read -r F; do
      echo "🗑️ Removing Supervisor config: $F"
      sudo rm -f "$F"
    done
    sudo supervisorctl reread || true
    sudo supervisorctl update || true
  fi
fi

# E) Kill tmux/screen sessions that might hold gunicorn
if command -v tmux >/dev/null 2>&1; then
  tmux ls 2>/dev/null | awk -F: '{print $1}' | while read -r S; do
    tmux capture-pane -pt "$S" 2>/dev/null | grep -qi gunicorn && { echo "🔪 Killing tmux session: $S"; tmux kill-session -t "$S"; }
  done
fi
if command -v screen >/dev/null 2>&1; then
  screen -ls 2>/dev/null | grep -Eo '[0-9]+\.[^ \t]+' | while read -r S; do
    screen -S "$S" -X hardcopy /tmp/screen_$S.txt 2>/dev/null || true
    grep -qi gunicorn /tmp/screen_$S.txt 2>/dev/null && { echo "🔪 Killing screen session: $S"; screen -S "$S" -X quit; }
    rm -f /tmp/screen_$S.txt 2>/dev/null || true
  done
fi

# F) Remove @reboot crons that launch gunicorn (backup first)
echo "🕒 Cleaning crontabs (user and root) of gunicorn @reboot entries…"
( crontab -l 2>/dev/null || true ) > /tmp/cron_user.bak || true
( crontab -l 2>/dev/null | grep -v 'gunicorn' || true ) | crontab - || true

( sudo crontab -l 2>/dev/null || true ) > /tmp/cron_root.bak || true
( sudo crontab -l 2>/dev/null | grep -v 'gunicorn' || true ) | sudo crontab - || true

echo "✅ Kill anything left on :8000 (should be empty after this)"
sudo lsof -t -i :8000 | xargs -r sudo kill -9 || true

echo "🛠 Step 2: Create clean systemd unit (socket-based Gunicorn)"
sudo tee "$SYSTEMD_UNIT" >/dev/null <<EOF
[Unit]
Description=Thermo Fam ERP (Gunicorn via Unix socket)
Wants=network-online.target
After=network-online.target mariadb.service mysql.service

[Service]
User=thermo
Group=www-data
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=-$ENV_FILE

# Socket to /run/fleet/fleet.sock with secure perms for www-data
ExecStart=$VENV_DIR/bin/gunicorn \\
  -w 3 \\
  --bind unix:/run/$SERVICE_NAME/$SERVICE_NAME.sock \\
  --umask 007 \\
  $WSGI_MODULE

RuntimeDirectory=$SERVICE_NAME
Restart=always
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

echo "🌐 Step 3: Nginx site -> proxy to the socket"
sudo tee "$NGINX_SITE" >/dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 50m;

    location /static/ {
        alias /home/thermo/Thermo/static/;
    }
    location /media/ {
        alias /home/thermo/Thermo/media/;
    }

    location / {
        proxy_pass http://unix:/run/fleet/fleet.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }
}
EOF

sudo ln -sf "$NGINX_SITE" "$NGINX_LINK"

echo "🧩 Step 4: Ensure permissions for static/media and project"
sudo chown -R thermo:www-data "$PROJECT_DIR"
sudo find "$PROJECT_DIR" -type d -exec chmod 750 {} \; 2>/dev/null || true
sudo find "$PROJECT_DIR" -type f -exec chmod 640 {} \; 2>/dev/null || true
sudo chmod -R 755 "$PROJECT_DIR/venv" || true
sudo mkdir -p /run/$SERVICE_NAME
sudo chown -R thermo:www-data /run/$SERVICE_NAME

echo "🌀 Step 5: Reload services and start"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "🧪 Step 6: Test Nginx config and reload"
sudo nginx -t
sudo systemctl reload nginx

echo "🔍 Step 7: Health checks"
echo "Systemd status:"
systemctl status "$SERVICE_NAME" --no-pager -l | sed -n '1,25p'
echo "Socket exists?"
sudo ls -l /run/$SERVICE_NAME/$SERVICE_NAME.sock || true
echo "Nginx is serving? (expect 302 to /login)"
curl -I http://127.0.0.1/ || true

echo "⛔ Verify nothing is listening on :8000 (we moved to socket):"
sudo lsof -i :8000 || true

echo "🛡️ Step 8: Prevent the machine from sleeping (keeps server up even if VS Code is closed)"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true

echo "✅ Done. From now on, deploy with: sudo systemctl restart $SERVICE_NAME"
