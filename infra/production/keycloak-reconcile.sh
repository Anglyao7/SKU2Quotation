#!/usr/bin/env bash

set -Eeuo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "Keycloak reconciliation must run as root"
require_command docker
require_command python3
load_production_env
if [[ -z "${ATC_COMMIT_SHA:-}" ]]; then
  load_release_metadata
fi
acquire_global_operation_lock
render_keycloak_realm

info "reconciling managed Keycloak settings through the private identity network"
printf '%s\n%s\n' "${KEYCLOAK_ADMIN_USERNAME}" "${KEYCLOAK_ADMIN_PASSWORD}" \
  | compose_with_ops run -T --rm --no-deps keycloak-reconciler \
      --server-url http://keycloak:8080 \
      --allow-internal-keycloak-http \
      --realm-config /run/atc/atc-realm.json
KEYCLOAK_ADMIN_PASSWORD=""
info "Keycloak managed configuration verified"
