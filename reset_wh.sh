#!/usr/bin/env bash
set -euo pipefail

# ─── 0) Create & activate virtualenv ─────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "🛠 Creating virtualenv…"
  python3 -m venv venv
fi
echo "⚡ Activating virtualenv…"
# shellcheck disable=SC1091
source venv/bin/activate

# ─── 1) Install dependencies ─────────────────────────────────────────────────
echo "📦 Installing requirements…"
pip install --upgrade pip
pip install -r requirements.txt

# ─── 1.5) Load DB env vars (or defaults) ─────────────────────────────────────
# If a .env file exists, load it. Then export sane defaults if not provided.
if [ -f .env ]; then
  echo "🔧 Loading .env variables…"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Defaults aligned with warehouse_project/settings.py
: "${DB_ENGINE:=django.db.backends.mysql}"
: "${DB_NAME:=warehouse_db}"
: "${DB_USER:=wh_user}"
: "${DB_PASSWORD:=strong_password}"
: "${DB_HOST:=127.0.0.1}"
: "${DB_PORT:=3306}"
export DB_ENGINE DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT

# ─── 2) Drop & recreate DB ────────────────────────────────────────────────────
echo "🗑 Dropping & recreating database…"
python manage.py reset_db

# ─── 3) Clean old app files ───────────────────────────────────────────────────
echo "🧹 Removing old migrations & caches…"
cd WareDGT
rm -rf __init__.py __pycache__ migrations
cd ..

# ─── 4) Rebuild migrations & apply ────────────────────────────────────────────
echo "📑 Making & applying migrations…"
python manage.py makemigrations WareDGT
python manage.py migrate

# ─── 5) Preload default data ──────────────────────────────────────────────────
echo "🚚 Importing default DGT warehouses & seeds…"
python manage.py create_companies

python manage.py import_warehouses

# Seed finance bank accounts from the CASH BALANCE mapping
python manage.py seed_bank_types --file \
  "/mnt/c/Users/natma/Downloads/ethiopian_banks_with_types.csv" || true

# Use same defaults as Django settings.py
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-wh_user}"
DB_PASSWORD="${DB_PASSWORD:-strong_password}"
DB_NAME="${DB_NAME:-warehouse_db}"

mysql --host="${DB_HOST}" \
      --port="${DB_PORT}" \
      --user="${DB_USER}" \
      --password="${DB_PASSWORD}" \
      "${DB_NAME}" \
      -e "UPDATE WareDGT_warehouse \
          SET code = 'ADDIS-ABABA-SARIS' \
          WHERE code = 'ADDIS-ABABASARIS';"
python manage.py import_seed_types
python manage.py import_coffee_seed_types
python manage.py import_pea_bean_seed_types

# ─── 6) Fix that typo in the DB ───────────────────────────────────────────────
echo "✏️  Correcting warehouse code typo…"


# ─── 7) Create superuser non-interactively ────────────────────────────────────
echo "🔐 Creating superuser…"
DJANGO_SUPERUSER_USERNAME="Admin" \
DJANGO_SUPERUSER_EMAIL="natnaelwolde3@gmail.com" \
DJANGO_SUPERUSER_PASSWORD="9381Der@1996" \
python manage.py createsuperuser --no-input || true
python manage.py import_ecx_trades ECX.xlsx --user admin

python manage.py import_ecx_movements --user admin --image Image.png
python manage.py import_ecx_movements_to_bincard

python manage.py import_cleaning_schedule \
    --user Admin \
    --start-date 2025-01-01 \
    --rate 50 \
    --hours 10
python manage.py import_draft_qc_records --user Admin
# ─── 8) (Optional) Import historical ECX trades ──────────────────────────────
#    Usage: ./reset_and_setup.sh path/to/ECX.xlsx
if [ $# -ge 1 ]; then
  EXCEL_FILE="$1"
  echo "📈 Importing ECX trades from ${EXCEL_FILE}…"
  python manage.py import_ecx_trades "${EXCEL_FILE}" --user Admin
fi

echo "✅ Done: env set up, DB reset, migrations applied, data imported, typo fixed, superuser created, and ECX import (if provided)."
