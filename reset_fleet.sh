# ===== reset_fleet.sh =====
set -euo pipefail

# Resolve dynamic paths based on current checkout
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$SCRIPT_DIR}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
WSGI_MODULE="${WSGI_MODULE:-transport_mgmt.wsgi:application}"
SERVICE_NAME="${SERVICE_NAME:-fleet}"
OS_USER="${OS_USER:-$(whoami)}"
ENV_FILE="${ENV_FILE:-/etc/${SERVICE_NAME}.env}"
NGINX_SITE="/etc/nginx/sites-available/$SERVICE_NAME.conf"
NGINX_LINK="/etc/nginx/sites-enabled/$SERVICE_NAME.conf"
SYSTEMD_UNIT="/etc/systemd/system/$SERVICE_NAME.service"

# Prefer venv gunicorn, otherwise fall back to PATH if available
if [ -x "$VENV_DIR/bin/gunicorn" ]; then
  GUNICORN_BIN="$VENV_DIR/bin/gunicorn"
elif command -v gunicorn >/dev/null 2>&1; then
  GUNICORN_BIN="$(command -v gunicorn)"
else
  GUNICORN_BIN=""
fi

echo "🔎 Running as: $OS_USER"
echo "📍 Project root: $PROJECT_DIR"
if [ -n "$GUNICORN_BIN" ]; then
  echo "📦 Gunicorn: $GUNICORN_BIN"
else
  echo "⚠️ Gunicorn not found in $VENV_DIR or PATH"
fi
echo "🌐 Nginx site name: $SERVICE_NAME"

# 0) Sanity checks (project dir only; gunicorn/systemd guarded later)
[ -d "$PROJECT_DIR" ] || { echo "❌ $PROJECT_DIR not found"; exit 1; }

echo "🧹 Step 1: Stop and remove any auto-spawners"

# A) Stop our managed service (if exists)
if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
fi

# B) Kill ALL gunicorns (twice, just to be sure)
sudo pkill -f 'gunicorn' || true
sleep 1
sudo pkill -9 -f 'gunicorn' || true

"${HAS_SYSTEMD:=false}"
if command -v systemctl >/dev/null 2>&1; then HAS_SYSTEMD=true; fi

# C) Disable and MASK any leftover systemd services that mention gunicorn (except our target name—we'll rewrite it)
if [ "$HAS_SYSTEMD" = true ]; then
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
if [ "$HAS_SYSTEMD" = true ] && [ -n "$GUNICORN_BIN" ]; then
  sudo tee "$SYSTEMD_UNIT" >/dev/null <<EOF
[Unit]
Description=Fleet (Gunicorn via Unix socket)
Wants=network-online.target
After=network-online.target mariadb.service mysql.service

[Service]
User=$OS_USER
Group=www-data
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=-$ENV_FILE

# Socket to /run/$SERVICE_NAME/$SERVICE_NAME.sock with secure perms for www-data
ExecStart=$GUNICORN_BIN \\
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
else
  echo "ℹ️ Skipping systemd unit creation (systemd/gunicorn not available)"
fi

echo "🌐 Step 3: Nginx site -> proxy to the socket"
if command -v nginx >/dev/null 2>&1; then
  sudo tee "$NGINX_SITE" >/dev/null <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 50m;

    location /static/ {
        alias $PROJECT_DIR/staticfiles/;
    }
    location /media/ {
        alias $PROJECT_DIR/media/;
    }

    location / {
        proxy_pass http://unix:/run/$SERVICE_NAME/$SERVICE_NAME.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
    }
}
EOF

  sudo ln -sf "$NGINX_SITE" "$NGINX_LINK"
else
  echo "ℹ️ Skipping Nginx config (nginx not installed)"
fi

echo "🧩 Step 4: Ensure permissions for static/media and project"
if command -v id >/dev/null 2>&1; then
  sudo chown -R "$OS_USER":www-data "$PROJECT_DIR" || true
fi
sudo find "$PROJECT_DIR" -type d -exec chmod 750 {} \; 2>/dev/null || true
sudo find "$PROJECT_DIR" -type f -exec chmod 640 {} \; 2>/dev/null || true
sudo chmod -R 755 "$PROJECT_DIR/venv" 2>/dev/null || true
sudo mkdir -p /run/$SERVICE_NAME
if command -v id >/dev/null 2>&1; then
  sudo chown -R "$OS_USER":www-data /run/$SERVICE_NAME || true
fi

echo "🌀 Step 5: Reload services and start"
if [ "$HAS_SYSTEMD" = true ] && [ -f "$SYSTEMD_UNIT" ]; then
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME" || true
  sudo systemctl restart "$SERVICE_NAME" || true
fi

echo "🧪 Step 6: Test Nginx config and reload"
if command -v nginx >/dev/null 2>&1; then
  sudo nginx -t && { [ "$HAS_SYSTEMD" = true ] && sudo systemctl reload nginx || sudo nginx -s reload; } || true
fi

echo "🔍 Step 7: Health checks"
if [ "$HAS_SYSTEMD" = true ]; then
  echo "Systemd status:"
  systemctl status "$SERVICE_NAME" --no-pager -l | sed -n '1,25p'
fi
echo "Socket exists?"
sudo ls -l /run/$SERVICE_NAME/$SERVICE_NAME.sock || true
echo "Nginx is serving? (expect 302 to /login)"
curl -I http://127.0.0.1/ || true

echo "⛔ Verify nothing is listening on :8000 (we moved to socket):"
sudo lsof -i :8000 || true

echo "🛡️ Step 8: Prevent the machine from sleeping (keeps server up even if VS Code is closed)"
if [ "$HAS_SYSTEMD" = true ]; then
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target || true
fi

echo "✅ Done. From now on, deploy with: sudo systemctl restart $SERVICE_NAME"
