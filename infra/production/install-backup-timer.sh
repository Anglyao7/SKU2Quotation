#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if (( EUID != 0 )); then
  printf 'ERROR: run this installer as root\n' >&2
  exit 1
fi
command -v systemctl >/dev/null 2>&1 || {
  printf 'ERROR: systemd is required\n' >&2
  exit 1
}

escaped_root="${REPOSITORY_ROOT//\//\\/}"
sed "s/__ATC_INSTALL_DIR__/${escaped_root}/g" \
  "${SCRIPT_DIR}/systemd/atc-backup.service.in" \
  >/etc/systemd/system/atc-backup.service
install -o root -g root -m 0644 \
  "${SCRIPT_DIR}/systemd/atc-backup.timer" \
  /etc/systemd/system/atc-backup.timer
systemctl daemon-reload
systemctl enable --now atc-backup.timer
systemctl list-timers atc-backup.timer --no-pager
