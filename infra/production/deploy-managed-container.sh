#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

target_ref="${1:-}"
[[ -n "${target_ref}" ]] || die "usage: $0 <git-commit-or-tag>"
(( EUID == 0 )) || die "managed-container deployment must run as root"

load_production_env
[[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]] \
  || die "managed-container deployment requires ATC_DEPLOYMENT_PROFILE=compact"
[[ "${ATC_EDGE_PROXY}" == "nginx" ]] \
  || die "managed-container deployment requires ATC_EDGE_PROXY=nginx"

"${SCRIPT_DIR}/scripts/validate_env.sh"
"${SCRIPT_DIR}/configure-nginx-edge.sh"
exec "${SCRIPT_DIR}/deploy.sh" "${target_ref}"
