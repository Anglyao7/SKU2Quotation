#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "backup must run as root"
require_command docker
require_command flock
require_command sha256sum
acquire_global_operation_lock
load_production_env
if [[ -z "${ATC_COMMIT_SHA:-}" ]]; then
  load_release_metadata
fi
"${SCRIPT_DIR}/scripts/validate_env.sh"

backup_root="${ATC_BACKUP_ROOT}"
retention_days="${ATC_BACKUP_RETENTION_DAYS:-14}"
mkdir -p "${backup_root}"
chmod 700 "${backup_root}"

exec 9>"${backup_root}/.backup.lock"
flock -n 9 || die "another backup is already running"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="${backup_root}/.partial-${timestamp}"
final="${backup_root}/${timestamp}"
[[ ! -e "${partial}" && ! -e "${final}" ]] || die "backup destination already exists"
mkdir -p "${partial}"
chmod 700 "${partial}"

writers_stopped=false

resume_writers() {
  if [[ "${writers_stopped}" != "true" ]]; then
    return
  fi
  info "resuming identity and application services"
  # Preserve the exact pre-backup images and environment. This is important
  # when a pre-deploy backup runs after checking out newer source.
  if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
    compose start keycloak api web caddy
  else
    compose start rabbitmq keycloak api web caddy
    if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
      compose_with_workers start tenant-worker product-event-consumer
    fi
  fi
  writers_stopped=false
  wait_for_public_health 60 5
  verify_api_oidc_connectivity
}

cleanup_partial() {
  status="$?"
  trap - ERR INT TERM
  resume_writers || true
  if (( status != 0 )); then
    printf '[atc] incomplete backup retained for diagnosis: %s\n' "${partial}" >&2
  fi
  exit "${status}"
}
trap cleanup_partial ERR INT TERM

info "entering a bounded backup window so DB and object snapshots cannot diverge"
# Mark the window before the first stop so an error halfway through stopping
# services still triggers a best-effort resume in the trap.
writers_stopped=true
compose stop caddy web api keycloak
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
    compose_with_workers stop tenant-worker product-event-consumer
  fi
  compose stop rabbitmq
fi

info "dumping application PostgreSQL"
compose exec -T postgres \
  pg_dump --username=postgres --dbname=ai_trade_cloud \
  --format=custom --compress=9 --no-owner --no-privileges \
  >"${partial}/application.postgresql.dump"

info "dumping Keycloak PostgreSQL"
compose exec -T keycloak-postgres \
  pg_dump --username=keycloak --dbname=keycloak \
  --format=custom --compress=9 --no-owner --no-privileges \
  >"${partial}/keycloak.postgresql.dump"

if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  info "snapshotting the compact local object volume"
  export ATC_BACKUP_STAGING_DIR="${partial}"
  compose_with_ops run --rm --no-deps backup-local-objects
else
  info "snapshotting RabbitMQ durable definitions and queued messages"
  export ATC_BACKUP_STAGING_DIR="${partial}"
  compose_with_ops run --rm --no-deps backup-rabbitmq

  info "copying and checksumming current MinIO objects"
  mkdir -p "${partial}/object-storage"
  chown 10001:10001 "${partial}/object-storage"
  export ATC_BACKUP_STAGING_DIR="${partial}/object-storage"
  compose_with_ops run --rm --no-deps backup-minio /backup/minio
  chown -R 0:0 "${partial}/object-storage"
  chmod -R go-rwx "${partial}/object-storage"
fi

{
  printf 'created_at=%s\n' "${timestamp}"
  printf 'release=%s\n' "${ATC_RELEASE}"
  printf 'commit=%s\n' "${ATC_COMMIT_SHA}"
  printf 'migration_head=%s\n' "${ATC_MIGRATION_HEAD}"
  printf 'config_version=%s\n' "${ATC_CONFIG_VERSION}"
} >"${partial}/release.txt"

(
  cd "${partial}"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum >SHA256SUMS
)
chmod -R go-rwx "${partial}"
mv "${partial}" "${final}"
resume_writers
trap - ERR INT TERM

# Delete only timestamped completed backups under the validated backup root.
find "${backup_root}" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????T??????Z' -mtime "+${retention_days}" -exec rm -rf -- {} +
find "${backup_root}" -mindepth 1 -maxdepth 1 -type d \
  -name '.partial-*' -mtime +2 -exec rm -rf -- {} +

if [[ "${ATC_ENABLE_REMOTE_BACKUP}" == "true" ]]; then
  require_command restic
  info "sending the completed snapshot to encrypted off-server restic storage"
  restic backup "${final}"
  restic forget --keep-daily "${retention_days}" --keep-weekly 8 --keep-monthly 12 --prune
else
  info "remote backup is disabled; the verified local backup remains at ${final}"
fi

printf '%s\n' "${final}" >"${DEPLOYMENT_STATE_DIR}/last-backup-path"
chmod 600 "${DEPLOYMENT_STATE_DIR}/last-backup-path"
info "backup completed: ${final}"
