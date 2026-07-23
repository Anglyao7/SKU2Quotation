#!/usr/bin/env bash

set -Eeuo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "Keycloak user provisioning must run as root"
email="${1:-}"
display_name="${2:-}"
login_identifier="${3:-${email}}"
verification_mode="${4:-email}"
[[ "${email}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
  || die "usage: $0 <invited-email> <display-name> [email-or-e164-phone] [--email-verified]"
[[ -n "${display_name}" && ${#display_name} -le 120 ]] \
  || die "display name must contain 1 to 120 characters"
(( $# >= 2 && $# <= 4 )) \
  || die "usage: $0 <invited-email> <display-name> [email-or-e164-phone] [--email-verified]"
[[ "${verification_mode}" == "email" || "${verification_mode}" == "--email-verified" ]] \
  || die "the fourth argument may only be --email-verified"

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
  --username "${login_identifier}"
  --display-name "${display_name}"
)
if [[ "${verification_mode}" == "--email-verified" ]]; then
  arguments+=(--email-verified)
else
  arguments+=(
    --send-actions-email
    --login-client-id "${OIDC_CLIENT_ID}"
    --redirect-uri "https://${ATC_DOMAIN}/login"
  )
fi

info "starting isolated interactive Keycloak provisioning"
compose_with_ops run --rm --no-deps keycloak-user-provisioner "${arguments[@]}"
info "Keycloak provisioning command completed"
