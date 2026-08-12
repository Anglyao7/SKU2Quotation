#!/usr/bin/env bash

set -Eeuo pipefail

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '[atc-host] %s\n' "$*"
}

(( EUID == 0 )) || die "managed-container host preparation must run as root"
command -v apt-get >/dev/null 2>&1 \
  || die "this host preparation script currently supports Ubuntu/Debian only"

export DEBIAN_FRONTEND=noninteractive
packages=(ca-certificates cron curl git nginx openssl procps python3)
if ! command -v docker >/dev/null 2>&1; then
  packages+=(docker.io)
fi
if ! docker compose version >/dev/null 2>&1; then
  packages+=(docker-compose-v2)
fi

info "installing required host packages"
apt-get update
apt-get install -y --no-install-recommends "${packages[@]}"

if [[ "$(ps -p 1 -o comm= | tr -d '[:space:]')" == "systemd" ]]; then
  systemctl enable --now docker cron nginx
else
  # Provider-managed containers do not have systemd. Their entrypoint must own
  # dockerd and the foreground Nginx process so both survive a container reboot.
  docker info >/dev/null 2>&1 \
    || die "Docker is installed but its daemon is not running; configure the provider entrypoint to start dockerd"
  if [[ -f /start.sh ]] && ! grep -Eq '(^|[[:space:]])dockerd([[:space:]]|$)' /start.sh; then
    die "/start.sh does not start dockerd; ask the provider to retain nested-Docker startup before continuing"
  fi

  if ! pgrep -x cron >/dev/null 2>&1; then
    cron
  fi
  if [[ -f /start.sh ]] && ! grep -Fq '# atc-managed: start cron' /start.sh; then
    grep -Fq 'exec nginx -g "daemon off;"' /start.sh \
      || die "cannot safely add cron startup because /start.sh has an unknown foreground command"
    entrypoint_backup="/start.sh.atc-backup-$(date -u +%Y%m%dT%H%M%SZ)"
    entrypoint_temp="$(mktemp)"
    cp -a /start.sh "${entrypoint_backup}"
    awk '
      /exec nginx -g "daemon off;"/ && !inserted {
        print "# atc-managed: start cron"
        print "if command -v cron >/dev/null 2>&1 && ! pgrep -x cron >/dev/null 2>&1; then"
        print "  cron"
        print "fi"
        inserted = 1
      }
      { print }
      END { if (!inserted) exit 42 }
    ' /start.sh >"${entrypoint_temp}"
    # Provider entrypoints are commonly bind-mounted files. `install` tries to
    # replace the inode and fails with EBUSY on a mount point, while `cp`
    # updates the existing file contents safely and preserves the mount.
    cp "${entrypoint_temp}" /start.sh
    chown root:root /start.sh
    chmod 0755 /start.sh
    rm -f "${entrypoint_temp}"
    info "added persistent cron startup to /start.sh (backup: ${entrypoint_backup})"
  fi

  if ! pgrep -x nginx >/dev/null 2>&1; then
    nginx -t
    nginx
  fi
fi

docker info >/dev/null
docker compose version >/dev/null
info "running a real nested-Docker smoke test"
docker run --rm hello-world >/dev/null
info "Docker Engine, Compose, cron, Nginx, Git, curl, OpenSSL, and Python are ready"
