#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if (( EUID != 0 )); then
  printf 'ERROR: run this installer as root\n' >&2
  exit 1
fi
escaped_root="${REPOSITORY_ROOT//\//\\/}"
if command -v systemctl >/dev/null 2>&1 \
  && [[ "$(ps -p 1 -o comm= | tr -d '[:space:]')" == "systemd" ]]; then
  sed "s/__ATC_INSTALL_DIR__/${escaped_root}/g" \
    "${SCRIPT_DIR}/systemd/atc-backup.service.in" \
    >/etc/systemd/system/atc-backup.service
  install -o root -g root -m 0644 \
    "${SCRIPT_DIR}/systemd/atc-backup.timer" \
    /etc/systemd/system/atc-backup.timer
  systemctl daemon-reload
  systemctl enable --now atc-backup.timer
  systemctl list-timers atc-backup.timer --no-pager
  exit 0
fi

command -v cron >/dev/null 2>&1 || {
  printf 'ERROR: systemd is unavailable and cron is not installed\n' >&2
  exit 1
}
command -v pgrep >/dev/null 2>&1 || {
  printf 'ERROR: pgrep is required to manage cron without systemd\n' >&2
  exit 1
}

sed "s/__ATC_INSTALL_DIR__/${escaped_root}/g" \
  "${SCRIPT_DIR}/cron/atc-backup.in" \
  >/etc/cron.d/atc-backup
chown root:root /etc/cron.d/atc-backup
chmod 0644 /etc/cron.d/atc-backup
if ! pgrep -x cron >/dev/null 2>&1; then
  cron
fi
printf '[atc] installed daily backup schedule in /etc/cron.d/atc-backup\n'
