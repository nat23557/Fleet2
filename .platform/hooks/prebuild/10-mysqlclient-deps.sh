#!/usr/bin/env bash
set -euo pipefail

# Install build tools and MariaDB client development headers so mysqlclient can build.
# Handles both Amazon Linux 2 (yum) and Amazon Linux 2023 (dnf).

echo "[prebuild] Installing system deps for mysqlclient..."

PKG="dnf"
if ! command -v dnf >/dev/null 2>&1; then
  PKG="yum"
fi

# Ensure basic toolchain and pkg-config are present
sudo ${PKG} install -y gcc gcc-c++ python3-devel pkgconf-pkg-config || true

# Try several package names that provide MariaDB/MySQL client runtime + headers on AL2/AL2023.
install_one() {
  local name="$1"
  echo "[prebuild] Trying to install: ${name}"
  sudo ${PKG} install -y "${name}" && return 0 || return 1
}

install_one mariadb-connector-c || true  # runtime libs
if ! install_one mariadb-devel; then
  install_one mariadb-connector-c-devel ||
  install_one mariadb105-devel ||
  install_one mysql-devel || true
fi

# Print diagnostic info for troubleshooting in eb-engine.log
echo "[prebuild] pkg-config search for mariadb/libmariadb:"
command -v pkg-config >/dev/null 2>&1 && pkg-config --list-all | grep -E "(mariadb|mysql|libmariadb)" || true

echo "[prebuild] System deps installation step finished."
