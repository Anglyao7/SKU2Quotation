#!/usr/bin/env bash

set -Eeuo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "Keycloak user provisioning must run as root"
email="${1:-}"
display_name="${2:-}"
[[ "${email}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
  || die "usage: $0 <invited-email> <display-name>"
[[ -n "${display_name}" && ${#display_name} -le 120 ]] \
  || die "display name must contain 1 to 120 characters"
(( $# == 2 )) || die "usage: $0 <invited-email> <display-name>"

require_command docker
load_production_env
load_release_metadata
acquire_global_operation_lock

arguments=(
  --server-url http://keycloak:8080
  --allow-internal-keycloak-http
  --realm atc
  --admin-realm master
  --admin-username "${KEYCLOAK_ADMIN_USERNAME}"
  --email "${email}"
  --display-name "${display_name}"
  --send-actions-email
  --login-client-id "${OIDC_CLIENT_ID}"
  --redirect-uri "https://${ATC_DOMAIN}/login"
)

info "starting isolated interactive Keycloak provisioning"
compose_with_ops run --rm --no-deps keycloak-user-provisioner "${arguments[@]}"
info "Keycloak provisioning command completed"
