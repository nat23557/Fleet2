#!/usr/bin/env bash
set -euo pipefail

# reset_csh.sh — Purge cash tables and repopulate from CASH BALANCE ledger
#
# What it does:
#   - Ensures virtualenv and deps (installs openpyxl if needed)
#   - Applies migrations
#   - Purges cash_management data (BankAccount, Transaction, AuditLog)
#   - Imports banks + transactions from the Excel ledger in this repo
#
# Usage:
#   ./reset_csh.sh [--yes] [--excel "CASH BALANCE 2025_2026.xlsx"] [--sheet SHEET_NAME] [--preview]
#
# Tips:
#   - To force local SQLite instead of MySQL, run: USE_SQLITE=1 ./reset_csh.sh --yes
#   - Pass --preview to see detected mappings without writing any data

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

EXCEL_FILE="CASH BALANCE 2025_2026.xlsx"
SHEET_NAME=""
ASSUME_YES=false
PREVIEW=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=true
      shift
      ;;
    --excel)
      EXCEL_FILE=${2:-"$EXCEL_FILE"}
      shift 2
      ;;
    --sheet)
      SHEET_NAME=${2:-""}
      shift 2
      ;;
    --preview)
      PREVIEW=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [ ! -f "$EXCEL_FILE" ]; then
  echo "❌ Excel file not found: $EXCEL_FILE" >&2
  echo "   Provide it with --excel path/to/file.xlsx" >&2
  exit 1
fi

# 0) Ensure and activate virtualenv
if [ ! -d "venv" ]; then
  echo "🛠 Creating virtualenv…"
  python3 -m venv venv
fi
echo "⚡ Activating virtualenv…"
# shellcheck disable=SC1091
source venv/bin/activate

# 1) Install requirements (quiet) and ensure openpyxl present
echo "📦 Installing requirements…"
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null
python - <<'PY' >/dev/null 2>&1 || pip install openpyxl >/dev/null
try:
    import openpyxl  # noqa: F401
    print("ok")
except Exception:
    raise SystemExit(1)
PY

# 1.5) Load env vars from .env if present (DB settings, etc.)
if [ -f .env ]; then
  echo "🔧 Loading .env variables…"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "🧭 Using settings from transport_mgmt/settings.py (USE_SQLITE=${USE_SQLITE:-0})"

# 2) Make sure schema is up-to-date
echo "📑 Applying migrations…"
python manage.py migrate --noinput

# 3) Confirm destructive action unless --yes
if [ "$ASSUME_YES" != true ]; then
  echo "⚠️  This will DELETE all cash accounts, transactions, and related audit logs."
  read -r -p "Proceed? [y/N] " reply
  case "$reply" in
    [yY][eE][sS]|[yY]) ;;
    *) echo "Cancelled."; exit 1 ;;
  esac
fi

# 4) Purge cash data
echo "🧹 Clearing cash data (accounts, transactions, audit logs)…"
python manage.py clear_cash_data --yes --also-audit || {
  echo "❌ Failed to clear cash data" >&2
  exit 1
}

# Also clear exchange rates as requested (cash_management_exchangerate)
echo "🧽 Clearing exchange rates…"
python manage.py shell <<'PY'
from cash_management.models import ExchangeRate
deleted, _ = ExchangeRate.objects.all().delete()
print(f"Deleted ExchangeRate rows: {deleted}")
PY

# 5) Import banks + transactions from the CASH BALANCE ledger
echo "📥 Importing cash ledger from: $EXCEL_FILE"
IMPORT_ARGS=("$EXCEL_FILE")
if [ -n "$SHEET_NAME" ]; then
  IMPORT_ARGS+=("--sheet" "$SHEET_NAME")
fi
if [ "$PREVIEW" = true ]; then
  IMPORT_ARGS+=("--preview")
fi

python manage.py import_cash_ledger "${IMPORT_ARGS[@]}" || {
  echo "❌ Import failed" >&2
  exit 1
}

# 6) Repopulate today's exchange rates (from CBE API) so ETB equivalents work
if [ "$PREVIEW" != true ]; then
  echo "💱 Fetching today's CBE exchange rates…"
  python manage.py shell <<'PY'
from cash_management.exchange import get_or_update_today_rates
rates = get_or_update_today_rates()
print({k: float(v) for k, v in rates.items()})
PY
fi

echo "✅ Done: cash tables reset and populated from ledger."
echo "   - File: $EXCEL_FILE"
if [ -n "$SHEET_NAME" ]; then
  echo "   - Sheet: $SHEET_NAME"
fi
if [ "$PREVIEW" = true ]; then
  echo "   (Preview mode: no data written.)"
fi
