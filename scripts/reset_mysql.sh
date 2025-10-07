#!/usr/bin/env bash
set -euo pipefail

# Reset MySQL database, rebuild migrations, and create a Django superuser.
# Configuration via env vars (sensible defaults for this repo):
#   DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
#   DB_ADMIN_USER, DB_ADMIN_PASSWORD  (optional: privileged user to drop/create DB)
#   DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_PASSWORD
#
# Example usage:
#   DB_ADMIN_USER=root DB_ADMIN_PASSWORD=secret \
#   DB_NAME=fleet DB_USER=admin DB_PASSWORD=Admin_thermo \
#   DJANGO_SUPERUSER_USERNAME=Admin DJANGO_SUPERUSER_EMAIL=admin@example.com DJANGO_SUPERUSER_PASSWORD='StrongP@ss' \
#   bash scripts/reset_mysql.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT_DIR"

echo "🔎 Working directory: $PWD"

# --- 0) Ensure virtualenv ----------------------------------------------------
if [ ! -d "venv" ]; then
  echo "🛠 Creating virtualenv…"
  python3 -m venv venv
fi
echo "⚡ Activating virtualenv…"
# shellcheck disable=SC1091
source venv/bin/activate

# --- 1) Install dependencies -------------------------------------------------
echo "📦 Installing requirements…"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

# --- 2) Check mysql client ---------------------------------------------------
if ! command -v mysql >/dev/null 2>&1; then
  echo "❌ 'mysql' client not found. Please install MySQL client tools." >&2
  exit 1
fi

# --- 3) Resolve DB vars ------------------------------------------------------
DB_NAME=${DB_NAME:-fleet}
DB_USER=${DB_USER:-admin}
DB_PASSWORD=${DB_PASSWORD:-Admin_thermo}
DB_HOST=${DB_HOST:-127.0.0.1}
DB_PORT=${DB_PORT:-3306}

# Export so Django sees the same config during manage.py calls
export DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT

# Admin user for dropping/creating DB; falls back to app user
DB_ADMIN_USER=${DB_ADMIN_USER:-$DB_USER}
DB_ADMIN_PASSWORD=${DB_ADMIN_PASSWORD:-$DB_PASSWORD}

echo "🗄  DB host=$DB_HOST port=$DB_PORT name=$DB_NAME user=$DB_USER (admin=$DB_ADMIN_USER)"

# --- Optional: reinstall MySQL server/client (DANGEROUS) ---------------------
# Set REINSTALL_MYSQL=true to purge and reinstall MySQL cleanly.
reinstall_mysql_if_requested() {
  if [ "${REINSTALL_MYSQL:-false}" != "true" ]; then
    return
  fi
  echo "⚠️  Reinstalling MySQL server/client (purge + fresh install)…"
  # Try to stop service if present
  sudo systemctl stop mysql 2>/dev/null || true
  sudo service mysql stop 2>/dev/null || true

  # Purge packages and remove data/config directories
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y mysql-server mysql-client mysql-common || true
  sudo rm -rf /etc/mysql /var/lib/mysql /var/log/mysql ~/.mysql || true
  sudo apt-get autoremove -y || true
  sudo apt-get autoclean -y || true

  # Fresh install
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server mysql-client

  # Start MySQL service
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable mysql || true
    sudo systemctl start mysql || true
  fi
  sudo service mysql start || true

  # Wait for server to accept connections via socket
  echo "⏳ Waiting for MySQL to become ready…"
  for i in {1..30}; do
    if sudo mysql -e "SELECT 1" >/dev/null 2>&1; then
      echo "✅ MySQL is up."
      break
    fi
    sleep 1
  done
}

reinstall_mysql_if_requested

# Admin exec helper: prefer sudo socket access to avoid auth plugin issues
MYSQL_USE_SUDO=${MYSQL_USE_SUDO:-true}

mysql_admin_exec() {
  if [ "$MYSQL_USE_SUDO" = "true" ]; then
    sudo mysql -e "$1"
  else
    mysql \
      --protocol=TCP \
      --host="$DB_HOST" \
      --port="$DB_PORT" \
      --user="$DB_ADMIN_USER" \
      --password="$DB_ADMIN_PASSWORD" \
      -e "$1"
  fi
}

# Sanity: verify admin connectivity early
if [ "$MYSQL_USE_SUDO" = "true" ]; then
  if ! sudo mysql -e "SELECT 1" >/dev/null 2>&1; then
    echo "❌ Cannot run 'sudo mysql'. Ensure you have sudo access and MySQL is installed." >&2
    echo "   Tip: Set REINSTALL_MYSQL=true to install MySQL automatically." >&2
    exit 1
  fi
else
  if ! mysql_admin_exec "SELECT 1" >/dev/null 2>&1; then
    cat >&2 <<EOF
❌ Cannot connect to MySQL as admin user '$DB_ADMIN_USER' on $DB_HOST:$DB_PORT.
   Provide valid admin creds via DB_ADMIN_USER/DB_ADMIN_PASSWORD, or set MYSQL_USE_SUDO=true.
EOF
    exit 1
  fi
fi

# --- 4) Drop & recreate database --------------------------------------------
echo "🗑  Dropping and recreating database…"
mysql_admin_exec "DROP DATABASE IF EXISTS \`$DB_NAME\`; CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Optionally ensure the app user has privileges on the DB (best-effort)
if [ "${GRANT_PRIVILEGES:-true}" = "true" ]; then
  echo "🔑 Granting privileges to '$DB_USER' on '$DB_NAME'…"
  # Ensure user exists for common host patterns and has DB privileges
  mysql_admin_exec "CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';"
  mysql_admin_exec "CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';"
  mysql_admin_exec "CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$DB_PASSWORD';"
  mysql_admin_exec "GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';"
  mysql_admin_exec "GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';"
  mysql_admin_exec "GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'%';"
  mysql_admin_exec "FLUSH PRIVILEGES;"
fi

# --- 5) Run migrations -------------------------------------------------------
echo "📑 Making and applying migrations…"
python manage.py makemigrations
python manage.py migrate --noinput

# --- 6) Create superuser -----------------------------------------------------
echo "🔐 Creating superuser…"
# Defaults requested by user; can be overridden via env vars
DJANGO_SUPERUSER_USERNAME=${DJANGO_SUPERUSER_USERNAME:-Admin}
DJANGO_SUPERUSER_EMAIL=${DJANGO_SUPERUSER_EMAIL:natnaelwolde3@gmail.com}
DJANGO_SUPERUSER_PASSWORD=${DJANGO_SUPERUSER_PASSWORD:-'9381Der@1996'}

DJANGO_SUPERUSER_USERNAME="$DJANGO_SUPERUSER_USERNAME" \
DJANGO_SUPERUSER_EMAIL="$DJANGO_SUPERUSER_EMAIL" \
DJANGO_SUPERUSER_PASSWORD="$DJANGO_SUPERUSER_PASSWORD" \
python manage.py createsuperuser --no-input || true

echo "✅ Done: database reset, migrations applied, superuser ensured."
