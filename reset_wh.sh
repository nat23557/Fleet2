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

# ─── 2) Prepare DB (no full reset) ────────────────────────────────────────────
echo "🗄 Skipping full DB reset; targeting WareDGT tables only…"

# ─── 3) Keep migrations; ensure schema is applied ─────────────────────────────
echo "🔄 Applying WareDGT migrations (schema up-to-date)…"
python manage.py migrate WareDGT --noinput || true

# ─── 4) Truncate only WareDGT tables ──────────────────────────────────────────
echo "🧽 Truncating WareDGT tables…"

# Use same defaults as Django settings.py
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-wh_user}"
DB_PASSWORD="${DB_PASSWORD:-strong_password}"
DB_NAME="${DB_NAME:-warehouse_db}"

SQL=$(cat << 'EOSQL'
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE `WareDGT_authevent`;
TRUNCATE TABLE `WareDGT_bincard`;
TRUNCATE TABLE `WareDGT_bincardattachment`;
TRUNCATE TABLE `WareDGT_bincardentry`;
TRUNCATE TABLE `WareDGT_bincardentryrequest`;
TRUNCATE TABLE `WareDGT_bincardtransaction`;
TRUNCATE TABLE `WareDGT_cleanedstockout`;
TRUNCATE TABLE `WareDGT_commodity`;
TRUNCATE TABLE `WareDGT_company`;
TRUNCATE TABLE `WareDGT_contractmovement`;
TRUNCATE TABLE `WareDGT_contractmovementrequest`;
TRUNCATE TABLE `WareDGT_dailyrecord`;
TRUNCATE TABLE `WareDGT_dailyrecord_workers`;
TRUNCATE TABLE `WareDGT_dailyrecordassessment`;
TRUNCATE TABLE `WareDGT_dashboardconfig`;
TRUNCATE TABLE `WareDGT_ecxload`;
TRUNCATE TABLE `WareDGT_ecxload_trades`;
TRUNCATE TABLE `WareDGT_ecxloadrequest`;
TRUNCATE TABLE `WareDGT_ecxloadrequest_trades`;
TRUNCATE TABLE `WareDGT_ecxloadrequestreceiptfile`;
TRUNCATE TABLE `WareDGT_ecxmovement`;
TRUNCATE TABLE `WareDGT_ecxmovementreceiptfile`;
TRUNCATE TABLE `WareDGT_ecxshipment`;
TRUNCATE TABLE `WareDGT_ecxtrade`;
TRUNCATE TABLE `WareDGT_ecxtradereceiptfile`;
TRUNCATE TABLE `WareDGT_ecxtraderequest`;
TRUNCATE TABLE `WareDGT_ecxtraderequestfile`;
TRUNCATE TABLE `WareDGT_laborpayment`;
TRUNCATE TABLE `WareDGT_purchaseditemtype`;
TRUNCATE TABLE `WareDGT_purchaseorder`;
TRUNCATE TABLE `WareDGT_qualityanalysis`;
TRUNCATE TABLE `WareDGT_qualitycheck`;
TRUNCATE TABLE `WareDGT_seedgradeparameter`;
TRUNCATE TABLE `WareDGT_seedtype`;
TRUNCATE TABLE `WareDGT_seedtypebalance`;
TRUNCATE TABLE `WareDGT_seedtypedetail`;
TRUNCATE TABLE `WareDGT_stockmovement`;
TRUNCATE TABLE `WareDGT_stockout`;
TRUNCATE TABLE `WareDGT_stockoutrequest`;
TRUNCATE TABLE `WareDGT_userevent`;
TRUNCATE TABLE `WareDGT_userprofile`;
TRUNCATE TABLE `WareDGT_userprofile_warehouses`;
TRUNCATE TABLE `WareDGT_warehouse`;
TRUNCATE TABLE `WareDGT_weighbridgeslipimage`;
SET FOREIGN_KEY_CHECKS = 1;
EOSQL
)

mysql -f --host="${DB_HOST}" \
      --port="${DB_PORT}" \
      --user="${DB_USER}" \
      --password="${DB_PASSWORD}" \
      "${DB_NAME}" \
      -e "$SQL"

# ─── 5) Preload WareDGT data only ─────────────────────────────────────────────
echo "🚚 Importing default DGT warehouses & seeds…"
python manage.py create_companies
python manage.py import_warehouses
mysql -f --host="${DB_HOST}" \
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

echo "✅ Done: targeted WareDGT tables truncated, migrations ensured, WareDGT data re-seeded, and optional ECX imports completed."
