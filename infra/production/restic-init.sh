#!/usr/bin/env bash

set -Eeuo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "restic repository initialization must run as root"
require_command restic
load_production_env
acquire_global_operation_lock

[[ "${ATC_ENABLE_REMOTE_BACKUP}" == "true" ]] \
  || die "set ATC_ENABLE_REMOTE_BACKUP=true before initializing restic"
[[ -n "${RESTIC_REPOSITORY:-}" && "${RESTIC_REPOSITORY}" != *REPLACE_WITH* ]] \
  || die "set the remote RESTIC_REPOSITORY in .env.production first"
[[ "${RESTIC_REPOSITORY}" =~ ^(s3|rest|sftp|azure|gs|rclone): ]] \
  || die "RESTIC_REPOSITORY must be an off-server repository"
[[ -n "${RESTIC_PASSWORD:-}" && "${RESTIC_PASSWORD}" != *REPLACE_WITH* ]] \
  || die "set RESTIC_PASSWORD in .env.production first"
(( ${#RESTIC_PASSWORD} >= 24 )) \
  || die "RESTIC_PASSWORD must contain at least 24 characters"

if restic snapshots --no-lock --json >/dev/null 2>&1; then
  info "off-server restic repository is already initialized and readable"
  exit 0
fi

info "initializing the configured encrypted off-server restic repository"
restic init
restic snapshots --no-lock --json >/dev/null
info "off-server restic repository initialized and verified"
