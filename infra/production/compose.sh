#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

load_production_env
load_release_metadata
compose_file_arguments

profiles=(--profile identity)
if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
  profiles+=(--profile workers)
fi

exec docker compose \
  --env-file "${ENV_FILE}" \
  "${COMPOSE_FILE_ARGUMENTS[@]}" \
  "${profiles[@]}" \
  "$@"
