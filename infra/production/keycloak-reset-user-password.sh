#!/usr/bin/env bash

set -Eeuo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "Keycloak password reset must run as root"
username="${1:-}"
[[ "${username}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
  || die "usage: $0 <user-email>"
require_command docker
require_command python3
load_production_env
load_release_metadata

user_id="$(
  compose exec -T keycloak \
    /opt/keycloak/bin/kcadm.sh get users \
    -r atc \
    -q exact=true \
    -q "username=${username}" \
    --fields id \
    --format csv \
    --noquotes \
    | tr -d '\r'
)"
[[ "${user_id}" =~ ^[0-9a-fA-F-]{36}$ ]] \
  || die "exactly one Keycloak user was not found; authenticate kcadm first"

IFS= read -r -s -p "New temporary password: " new_password
printf '\n'
IFS= read -r -s -p "Repeat temporary password: " confirmation
printf '\n'
[[ "${new_password}" == "${confirmation}" ]] || die "passwords do not match"
(( ${#new_password} >= 12 )) || die "password must contain at least 12 characters"
[[ "${new_password}" =~ [A-Z] && "${new_password}" =~ [a-z] ]] \
  || die "password must contain upper- and lower-case letters"
[[ "${new_password}" =~ [0-9] && "${new_password}" =~ [^A-Za-z0-9] ]] \
  || die "password must contain a digit and a special character"

payload="$(
  printf '%s' "${new_password}" \
    | python3 -c \
      'import json,sys; print(json.dumps({"type":"password","temporary":True,"value":sys.stdin.read()}))'
)"
new_password=""
confirmation=""

# The password travels only through stdin into a mode-600 file inside the
# container. It never appears in shell history, argv, Docker inspect, or logs.
printf '%s' "${payload}" \
  | compose exec -T keycloak /bin/sh -ec '
      temporary_file="$(mktemp)"
      trap "rm -f -- \"${temporary_file}\"" EXIT
      chmod 600 "${temporary_file}"
      cat >"${temporary_file}"
      /opt/keycloak/bin/kcadm.sh update \
        "users/$1/reset-password" \
        -r atc \
        -f "${temporary_file}"
    ' reset-password "${user_id}"
payload=""

info "temporary password updated; the user must change it at next login"
