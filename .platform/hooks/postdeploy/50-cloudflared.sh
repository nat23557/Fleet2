#!/usr/bin/env bash
set -euo pipefail

# Install and start Cloudflare Tunnel on EB instance when CF_TUNNEL_TOKEN is set.
# Expected env vars (set via `eb setenv`):
#   CF_TUNNEL_TOKEN  - Token copied from Cloudflare when creating the tunnel
#   CF_TUNNEL_RUN    - Optional flag; if "0" or empty, skip installing

if [[ "${CF_TUNNEL_RUN:-1}" == "0" || -z "${CF_TUNNEL_TOKEN:-}" ]]; then
  echo "[cloudflared] Skipping: CF_TUNNEL_TOKEN not set or CF_TUNNEL_RUN=0"
  exit 0
fi

echo "[cloudflared] Installing cloudflared connector..."

PKG=dnf
if ! command -v dnf >/dev/null 2>&1; then PKG=yum; fi

sudo ${PKG} install -y cloudflared || {
  # Fallback: install via rpm if repo not present
  echo "[cloudflared] Package not found via ${PKG}; trying RPM install";
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.rpm -o /tmp/cloudflared.rpm
  sudo rpm -Uvh --force /tmp/cloudflared.rpm || true
}

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "[cloudflared] cloudflared not installed; aborting"
  exit 0
fi

echo "[cloudflared] Installing systemd service using provided token"
sudo cloudflared service install "${CF_TUNNEL_TOKEN}" || true

echo "[cloudflared] Enabling and starting service"
sudo systemctl enable cloudflared || true
sudo systemctl restart cloudflared || true

echo "[cloudflared] Done"

