#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

metadata_file="${1:-${DEPLOYMENT_STATE_DIR}/previous.env}"
keep_current_compose="${ATC_ROLLBACK_KEEP_CURRENT_COMPOSE:-false}"
migration_head_override="${ATC_ROLLBACK_MIGRATION_HEAD:-}"

require_command git
require_command docker
require_command curl
(( EUID == 0 )) || die "production rollback must run as root"
acquire_global_operation_lock
load_production_env
load_release_metadata "${metadata_file}"

case "${keep_current_compose}" in
  true)
    [[ "${migration_head_override}" =~ ^[0-9]{8}_[0-9]{4}$ ]] \
      || die "ATC_ROLLBACK_MIGRATION_HEAD must be an Alembic revision when retaining the current compose contract"
    export ATC_MIGRATION_HEAD="${migration_head_override}"
    ;;
  false)
    [[ -z "${migration_head_override}" ]] \
      || die "ATC_ROLLBACK_MIGRATION_HEAD requires ATC_ROLLBACK_KEEP_CURRENT_COMPOSE=true"
    ;;
  *)
    die "ATC_ROLLBACK_KEEP_CURRENT_COMPOSE must be true or false"
    ;;
esac

[[ "${ATC_COMMIT_SHA}" =~ ^[0-9a-f]{40}$ ]] || die "rollback metadata has an invalid commit"
docker image inspect "atc-api:${ATC_COMMIT_SHA}" >/dev/null 2>&1 \
  || die "rollback API image is no longer present; rebuild commit ${ATC_COMMIT_SHA} first"
docker image inspect "atc-web:${ATC_COMMIT_SHA}" >/dev/null 2>&1 \
  || die "rollback web image is no longer present; rebuild commit ${ATC_COMMIT_SHA} first"

cd "${REPOSITORY_ROOT}"
git diff --quiet && git diff --cached --quiet \
  || die "tracked files are modified; rollback refuses to overwrite server-side edits"
if [[ "${keep_current_compose}" == "true" ]]; then
  info "retaining the current expand-compatible compose contract at database head ${ATC_MIGRATION_HEAD}"
else
  git checkout --detach "${ATC_COMMIT_SHA}"
fi
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
