#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

metadata_file="${1:-${DEPLOYMENT_STATE_DIR}/previous.env}"

require_command git
require_command docker
require_command curl
(( EUID == 0 )) || die "production rollback must run as root"
acquire_global_operation_lock
load_production_env
cd "${REPOSITORY_ROOT}"
git diff --quiet && git diff --cached --quiet \
  || die "tracked files are modified; rollback refuses to overwrite server-side edits"
current_source_commit="$(git rev-parse HEAD)"
unset ATC_COMPOSE_COMMIT_SHA
load_release_metadata "${metadata_file}"

rollback_app_commit="${ATC_COMMIT_SHA}"
recorded_compose_commit="${ATC_COMPOSE_COMMIT_SHA:-${rollback_app_commit}}"

database_migration_head() {
  compose exec -T postgres \
    psql --username=postgres --dbname=ai_trade_cloud \
    --no-align --tuples-only \
    --command 'SELECT version_num FROM alembic_version ORDER BY version_num' \
    2>/dev/null \
    | tr -d '\r' \
    | awk 'NF { if (value != "") value = value ","; value = value $0 } END { print value }'
}

migration_head_for_commit() {
  local commit="$1"
  git show "${commit}:apps/api/Dockerfile" 2>/dev/null \
    | awk -F= '$1 == "ARG ATC_MIGRATION_HEAD" { print $2; exit }'
}

[[ "${rollback_app_commit}" =~ ^[0-9a-f]{40}$ ]] || die "rollback metadata has an invalid commit"
[[ "${recorded_compose_commit}" =~ ^[0-9a-f]{40}$ ]] || die "rollback metadata has an invalid compose commit"
docker image inspect "atc-api:${rollback_app_commit}" >/dev/null 2>&1 \
  || die "rollback API image is no longer present; rebuild commit ${rollback_app_commit} first"
docker image inspect "atc-web:${rollback_app_commit}" >/dev/null 2>&1 \
  || die "rollback web image is no longer present; rebuild commit ${rollback_app_commit} first"

compose up --detach --wait postgres
actual_migration_head="$(database_migration_head)"
[[ "${actual_migration_head}" =~ ^[A-Za-z0-9_]+$ ]] \
  || die "could not resolve the single current database migration head"

selected_compose_commit=""
for candidate in \
  "${recorded_compose_commit}" \
  "${rollback_app_commit}" \
  "${current_source_commit}"; do
  if [[ "$(migration_head_for_commit "${candidate}")" == "${actual_migration_head}" ]]; then
    selected_compose_commit="${candidate}"
    break
  fi
done
[[ -n "${selected_compose_commit}" ]] \
  || die "no available compose contract matches database head ${actual_migration_head}"

export ATC_COMMIT_SHA="${rollback_app_commit}"
export ATC_COMPOSE_COMMIT_SHA="${selected_compose_commit}"
export ATC_MIGRATION_HEAD="${actual_migration_head}"
git checkout --detach "${selected_compose_commit}"
info "using compose contract ${selected_compose_commit:0:12} for database head ${actual_migration_head}"
render_keycloak_realm
render_caddy_sites

compose up --detach --no-deps --wait keycloak
"${SCRIPT_DIR}/keycloak-reconcile.sh"
info "restoring application containers from ${ATC_RELEASE}; persistent volumes are untouched"
compose up --detach --no-deps --wait api web caddy
if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
  compose_with_workers up --detach --no-deps --wait \
    tenant-worker product-event-consumer
fi
wait_for_public_health 60 5
verify_api_oidc_connectivity

if [[ -f "${DEPLOYMENT_STATE_DIR}/current.env" && "${metadata_file}" != "${DEPLOYMENT_STATE_DIR}/current.env" ]]; then
  cp "${DEPLOYMENT_STATE_DIR}/current.env" "${DEPLOYMENT_STATE_DIR}/rolled-back-from.env"
fi
write_release_metadata "${DEPLOYMENT_STATE_DIR}/current.env"
info "rollback completed; database migrations were not downgraded"
