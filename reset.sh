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
#   ./reset.sh

# Resolve project root as the directory containing this script
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
if [ "${SKIP_PIP:-false}" != "true" ]; then
  echo "📦 Installing requirements… (set SKIP_PIP=true to skip)"
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt >/dev/null
else
  echo "📦 Skipping requirements install (SKIP_PIP=true)"
fi

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

# --- 4) Drop & recreate database --------------------------------------------
echo "🗑  Dropping and recreating database…"
mysql \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --user="$DB_ADMIN_USER" \
  --password="$DB_ADMIN_PASSWORD" \
  -e "DROP DATABASE IF EXISTS \`$DB_NAME\`; CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Optionally ensure the app user has privileges on the DB (best-effort)
if [ "${GRANT_PRIVILEGES:-false}" = "true" ]; then
  echo "🔑 Granting privileges to '$DB_USER' on '$DB_NAME'…"
  DB_GRANT_HOST=${DB_GRANT_HOST:-localhost}
  mysql \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_ADMIN_USER" \
    --password="$DB_ADMIN_PASSWORD" \
    -e "CREATE USER IF NOT EXISTS '$DB_USER'@'$DB_GRANT_HOST' IDENTIFIED BY '$DB_PASSWORD'; GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'$DB_GRANT_HOST'; FLUSH PRIVILEGES;"
fi

# --- 5) Run migrations -------------------------------------------------------
echo "📑 Making and applying migrations…"
python manage.py makemigrations
python manage.py migrate --noinput

# --- 6) Create superuser -----------------------------------------------------
echo "🔐 Creating superuser…"
: "${DJANGO_SUPERUSER_USERNAME:?Set DJANGO_SUPERUSER_USERNAME}"
: "${DJANGO_SUPERUSER_EMAIL:?Set DJANGO_SUPERUSER_EMAIL}"
: "${DJANGO_SUPERUSER_PASSWORD:?Set DJANGO_SUPERUSER_PASSWORD}"

DJANGO_SUPERUSER_USERNAME="$DJANGO_SUPERUSER_USERNAME" \
DJANGO_SUPERUSER_EMAIL="$DJANGO_SUPERUSER_EMAIL" \
DJANGO_SUPERUSER_PASSWORD="$DJANGO_SUPERUSER_PASSWORD" \
python manage.py createsuperuser --no-input || true

echo "✅ Done: database reset, migrations applied, superuser ensured."
