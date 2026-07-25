#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "restore must run as root"
backup_name="${1:-}"
[[ "${backup_name}" =~ ^20[0-9]{6}T[0-9]{6}Z$ ]] \
  || die "usage: ATC_RESTORE_CONFIRM=RESTORE-<timestamp> $0 <timestamp>"

require_command docker
require_command sha256sum
acquire_global_operation_lock
load_production_env
load_release_metadata

backup="${ATC_BACKUP_ROOT}/${backup_name}"
[[ -d "${backup}" ]] || die "backup does not exist: ${backup}"
[[ "${ATC_RESTORE_CONFIRM:-}" == "RESTORE-${backup_name}" ]] \
  || die "set ATC_RESTORE_CONFIRM=RESTORE-${backup_name} to confirm"

info "verifying every backup file before stopping services"
(
  cd "${backup}"
  sha256sum --check SHA256SUMS
)

info "creating a fresh safety backup of the current state"
ATC_OPERATION_LOCK_HELD=true "${SCRIPT_DIR}/backup.sh"
safety_backup="$(<"${DEPLOYMENT_STATE_DIR}/last-backup-path")"
[[ -d "${safety_backup}" ]] || die "pre-restore safety backup path is invalid"

restore_suffix="$(date -u +%Y%m%dT%H%M%SZ | tr -d 'TZ')"
application_restore_db="ai_trade_cloud_restore"
application_previous_db="ai_trade_cloud_pre_${restore_suffix}"
application_failed_db="ai_trade_cloud_failed_${restore_suffix}"
keycloak_restore_db="keycloak_restore"
keycloak_previous_db="keycloak_pre_${restore_suffix}"
keycloak_failed_db="keycloak_failed_${restore_suffix}"

database_exists() {
  local service="$1"
  local user="$2"
  local database="$3"
  compose exec -T "${service}" psql \
    --username="${user}" --dbname=postgres --tuples-only --no-align \
    --command="SELECT 1 FROM pg_database WHERE datname = '${database}'" \
    2>/dev/null | grep -qx 1
}

recover_pre_restore_state() {
  status="$?"
  trap - ERR INT TERM
  printf '[atc] restore failed; attempting to recover the pre-restore snapshot\n' >&2

  if database_exists postgres postgres "${application_previous_db}"; then
    compose exec -T postgres psql --username=postgres --dbname=postgres \
      --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'ai_trade_cloud' AND pid <> pg_backend_pid()" \
      >/dev/null 2>&1 || true
    if database_exists postgres postgres ai_trade_cloud; then
      compose exec -T postgres psql --username=postgres --dbname=postgres \
        --command="ALTER DATABASE ai_trade_cloud RENAME TO ${application_failed_db}" \
        >/dev/null 2>&1 || true
    fi
    compose exec -T postgres psql --username=postgres --dbname=postgres \
      --command="ALTER DATABASE ${application_previous_db} RENAME TO ai_trade_cloud" \
      >/dev/null 2>&1 || true
  fi

  if database_exists keycloak-postgres keycloak "${keycloak_previous_db}"; then
    compose exec -T keycloak-postgres psql --username=keycloak --dbname=postgres \
      --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'keycloak' AND pid <> pg_backend_pid()" \
      >/dev/null 2>&1 || true
    if database_exists keycloak-postgres keycloak keycloak; then
      compose exec -T keycloak-postgres psql --username=keycloak --dbname=postgres \
        --command="ALTER DATABASE keycloak RENAME TO ${keycloak_failed_db}" \
        >/dev/null 2>&1 || true
    fi
    compose exec -T keycloak-postgres psql --username=keycloak --dbname=postgres \
      --command="ALTER DATABASE ${keycloak_previous_db} RENAME TO keycloak" \
      >/dev/null 2>&1 || true
  fi

  if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
    ATC_BACKUP_STAGING_DIR="${safety_backup}" \
      compose_with_ops run --rm --no-deps restore-local-objects \
      >/dev/null 2>&1 || true
    compose up --detach --no-deps keycloak api web caddy \
      >/dev/null 2>&1 || true
  else
    compose stop rabbitmq >/dev/null 2>&1 || true
    ATC_BACKUP_STAGING_DIR="${safety_backup}" \
      compose_with_ops run --rm --no-deps restore-rabbitmq >/dev/null 2>&1 || true
    ATC_BACKUP_STAGING_DIR="${safety_backup}/object-storage" \
      compose_with_ops run --rm --no-deps restore-minio /backup/minio \
      >/dev/null 2>&1 || true
    compose up --detach --no-deps rabbitmq keycloak api web caddy \
      >/dev/null 2>&1 || true
    if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
      compose_with_workers up --detach --no-deps \
        tenant-worker product-event-consumer >/dev/null 2>&1 || true
    fi
  fi
  printf '[atc] pre-restore data was retained/reapplied; inspect health before retrying\n' >&2
  exit "${status}"
}
trap recover_pre_restore_state ERR INT TERM

info "stopping public and stateful application writers; volumes remain attached"
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  compose stop caddy web api keycloak
else
  compose stop caddy web api keycloak rabbitmq
  if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
    compose_with_workers stop tenant-worker product-event-consumer
  fi
fi

info "restoring the application dump into an isolated database"
compose exec -T postgres dropdb --username=postgres --if-exists "${application_restore_db}"
compose exec -T postgres createdb --username=postgres \
  --owner=atc_migration "${application_restore_db}"
compose exec -T postgres psql --username=postgres --dbname="${application_restore_db}" \
  --set=ON_ERROR_STOP=1 --command="CREATE EXTENSION IF NOT EXISTS vector"
compose exec -T postgres pg_restore --username=postgres \
  --dbname="${application_restore_db}" --role=atc_migration \
  --no-owner --no-privileges --exit-on-error \
  <"${backup}/application.postgresql.dump"
compose exec -T postgres psql --username=postgres --dbname="${application_restore_db}" \
  --tuples-only --no-align --command="SELECT version_num FROM alembic_version" \
  | grep -Eq '^[0-9]{8}_[0-9]{4}$'

info "restoring the Keycloak dump into an isolated database"
compose exec -T keycloak-postgres dropdb --username=keycloak --if-exists "${keycloak_restore_db}"
compose exec -T keycloak-postgres createdb --username=keycloak \
  --owner=keycloak "${keycloak_restore_db}"
compose exec -T keycloak-postgres pg_restore --username=keycloak \
  --dbname="${keycloak_restore_db}" --no-owner --no-privileges --exit-on-error \
  <"${backup}/keycloak.postgresql.dump"

info "atomically swapping both verified restore databases into service"
compose exec -T postgres psql --username=postgres --dbname=postgres \
  --set=ON_ERROR_STOP=1 \
  --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'ai_trade_cloud' AND pid <> pg_backend_pid()" \
  --command="ALTER DATABASE ai_trade_cloud RENAME TO ${application_previous_db}" \
  --command="ALTER DATABASE ${application_restore_db} RENAME TO ai_trade_cloud"
compose exec -T keycloak-postgres psql --username=keycloak --dbname=postgres \
  --set=ON_ERROR_STOP=1 \
  --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'keycloak' AND pid <> pg_backend_pid()" \
  --command="ALTER DATABASE keycloak RENAME TO ${keycloak_previous_db}" \
  --command="ALTER DATABASE ${keycloak_restore_db} RENAME TO keycloak"

if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  info "restoring the compact local object volume"
  export ATC_BACKUP_STAGING_DIR="${backup}"
  compose_with_ops run --rm --no-deps restore-local-objects
else
  info "restoring MinIO objects; versioning preserves any newer objects"
  export ATC_BACKUP_STAGING_DIR="${backup}/object-storage"
  compose_with_ops run --rm --no-deps restore-minio /backup/minio

  info "restoring RabbitMQ durable state from the same stopped-writer snapshot"
  export ATC_BACKUP_STAGING_DIR="${backup}"
  compose_with_ops run --rm --no-deps restore-rabbitmq
  compose up --detach --no-deps --wait rabbitmq
fi

info "migrating the restored application DB forward and reapplying grants"
compose_with_ops run --rm --no-deps db-migrate
compose_with_ops run --rm --no-deps db-grants
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  compose_with_ops run --rm --no-deps dependency-bootstrap
fi

compose up --detach --no-deps --wait keycloak
"${SCRIPT_DIR}/keycloak-reconcile.sh"
compose up --detach --no-deps --wait api web caddy
if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
  compose_with_workers up --detach --no-deps --wait \
    tenant-worker product-event-consumer
fi
wait_for_public_health 60 5
verify_api_oidc_hairpin
trap - ERR INT TERM

info "restore completed from ${backup_name}"
info "pre-restore databases were retained as ${application_previous_db} and ${keycloak_previous_db}"
