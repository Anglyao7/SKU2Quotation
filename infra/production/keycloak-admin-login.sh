#!/usr/bin/env bash

set -Eeuo pipefail
set +x

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "Keycloak administration login must run as root"
require_command docker
load_production_env
load_release_metadata

info "opening a private Keycloak administrator session"
compose exec keycloak \
  /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://127.0.0.1:8080 \
  --realm master \
  --user "${KEYCLOAK_ADMIN_USERNAME}"
