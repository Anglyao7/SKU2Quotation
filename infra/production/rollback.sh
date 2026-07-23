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
load_release_metadata "${metadata_file}"

[[ "${ATC_COMMIT_SHA}" =~ ^[0-9a-f]{40}$ ]] || die "rollback metadata has an invalid commit"
docker image inspect "atc-api:${ATC_COMMIT_SHA}" >/dev/null 2>&1 \
  || die "rollback API image is no longer present; rebuild commit ${ATC_COMMIT_SHA} first"
docker image inspect "atc-web:${ATC_COMMIT_SHA}" >/dev/null 2>&1 \
  || die "rollback web image is no longer present; rebuild commit ${ATC_COMMIT_SHA} first"

cd "${REPOSITORY_ROOT}"
git diff --quiet && git diff --cached --quiet \
  || die "tracked files are modified; rollback refuses to overwrite server-side edits"
git checkout --detach "${ATC_COMMIT_SHA}"
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
verify_api_oidc_hairpin

if [[ -f "${DEPLOYMENT_STATE_DIR}/current.env" && "${metadata_file}" != "${DEPLOYMENT_STATE_DIR}/current.env" ]]; then
  cp "${DEPLOYMENT_STATE_DIR}/current.env" "${DEPLOYMENT_STATE_DIR}/rolled-back-from.env"
fi
write_release_metadata "${DEPLOYMENT_STATE_DIR}/current.env"
info "rollback completed; database migrations were not downgraded"
