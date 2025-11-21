#!/usr/bin/env bash
set -euo pipefail

# reser_csh.sh — Purge cash tables and seed bank accounts only (no transactions)
#
# What it does:
#   - Ensures virtualenv and deps (installs openpyxl if needed)
#   - Applies migrations
#   - Purges cash_management accounts/transactions/audit logs
#   - Seeds BankAccount rows only (no Transaction) using seed_banks
#   - Optionally assigns a simple purpose to each account based on type
#
# Usage:
#   ./reser_csh.sh [--yes] [--source ledger|default|csv] [--file PATH] \
#                  [--types "main,usd,ecx,current"] [--preview] [--no-purpose]
#
# Defaults:
#   --source ledger --file "CASH BALANCE 2025_2026.xlsx" --types "main,usd,ecx,current"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ASSUME_YES=false
SOURCE="ledger"
EXCEL_OR_CSV_FILE="CASH BALANCE 2025_2026.xlsx"
TYPES="main,usd,ecx,current"
PREVIEW=false
SET_PURPOSE=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=true; shift ;;
    --source)
      SOURCE=${2:-$SOURCE}; shift 2 ;;
    --file)
      EXCEL_OR_CSV_FILE=${2:-$EXCEL_OR_CSV_FILE}; shift 2 ;;
    --types)
      TYPES=${2:-$TYPES}; shift 2 ;;
    --preview)
      PREVIEW=true; shift ;;
    --no-purpose)
      SET_PURPOSE=false; shift ;;
    *)
      echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

if [[ "$SOURCE" == "ledger" ]]; then
  if [ ! -f "$EXCEL_OR_CSV_FILE" ]; then
    echo "❌ Excel file not found: $EXCEL_OR_CSV_FILE" >&2
    echo "   Provide it with --file path/to/file.xlsx or use --source default/csv" >&2
    exit 1
  fi
fi

# 0) Ensure and activate virtualenv
if [ ! -d "venv" ]; then
  echo "🛠 Creating virtualenv…"
  python3 -m venv venv
fi
echo "⚡ Activating virtualenv…"
# shellcheck disable=SC1091
source venv/bin/activate

# 1) Install requirements (quiet) and ensure openpyxl present for ledger parsing
echo "📦 Installing requirements…"
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null
if [[ "$SOURCE" == "ledger" ]]; then
  python - <<'PY' >/dev/null 2>&1 || pip install openpyxl >/dev/null
try:
    import openpyxl  # noqa: F401
    print("ok")
except Exception:
    raise SystemExit(1)
PY
fi

# 1.5) Load env vars from .env if present (DB settings, etc.)
if [ -f .env ]; then
  echo "🔧 Loading .env variables…"
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "🧭 Using settings from transport_mgmt/settings.py (USE_SQLITE=${USE_SQLITE:-0})"

# 2) Ensure schema
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

# 4) Purge cash data (BankAccount, Transaction, AuditLog). Keep exchange rates intact.
echo "🧹 Clearing cash data (accounts, transactions, audit logs)…"
python manage.py clear_cash_data --yes --also-audit || {
  echo "❌ Failed to clear cash data" >&2
  exit 1
}

# 5) Seed banks only (no transactions)
echo "🌱 Seeding bank accounts only…"
ARGS=(--source "$SOURCE" --types "$TYPES")
if [[ "$SOURCE" == "ledger" || "$SOURCE" == "csv" ]]; then
  ARGS+=(--file "$EXCEL_OR_CSV_FILE")
fi
if [ "$PREVIEW" = true ]; then
  ARGS+=(--preview)
fi
python manage.py seed_banks "${ARGS[@]}" || {
  echo "❌ Bank seeding failed" >&2
  exit 1
}

# 6) Optionally set simple purpose values based on account type
if [ "$SET_PURPOSE" = true ] && [ "$PREVIEW" != true ]; then
  echo "🏷  Setting account purposes based on type…"
  python manage.py shell <<'PY'
from cash_management.models import BankAccount

def infer_purpose(name: str) -> str:
    n = (name or '').upper()
    if '/ECX' in n:
        return 'ECX'
    if 'CURRENT' in n:
        return 'CURRENT'
    if 'DOLLAR' in n or '/USD' in n or 'FOREX' in n or 'RETENTION' in n or 'RETANTION' in n:
        return 'FOREX'
    return 'OPERATIONS'

updated = 0
for acc in BankAccount.objects.all():
    p = infer_purpose(acc.name)
    if acc.purpose != p:
        acc.purpose = p
        acc.save(update_fields=['purpose'])
        updated += 1
print(f"Purposes updated: {updated}")
PY
fi

echo "✅ Done: cash tables purged and bank accounts seeded (no transactions)."
echo "   - Source: $SOURCE"
if [[ "$SOURCE" == "ledger" || "$SOURCE" == "csv" ]]; then
  echo "   - File: $EXCEL_OR_CSV_FILE"
fi
echo "   - Types: $TYPES"
if [ "$PREVIEW" = true ]; then
  echo "   (Preview mode: no data written.)"
fi

