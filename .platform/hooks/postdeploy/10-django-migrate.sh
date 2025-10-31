#!/usr/bin/env bash
set -euo pipefail

echo "[postdeploy] Running Django migrations + collectstatic"

if [[ -d /var/app/current ]]; then
  cd /var/app/current
fi

# Activate the EB-provided virtualenv if present
if [[ -d /var/app/venv ]]; then
  # shellcheck disable=SC1091
  source /var/app/venv/*/bin/activate || true
fi

# Run migrate and collectstatic. Do not fail the whole deploy if they error; log instead.
python manage.py migrate --noinput || echo "[postdeploy] migrate failed (non-fatal)"
python manage.py collectstatic --noinput || echo "[postdeploy] collectstatic failed (non-fatal)"

echo "[postdeploy] Done"

