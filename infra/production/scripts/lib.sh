#!/usr/bin/env bash

set -Eeuo pipefail

PRODUCTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY_ROOT="$(cd "${PRODUCTION_DIR}/../.." && pwd)"
ENV_FILE="${ATC_ENV_FILE:-${REPOSITORY_ROOT}/.env.production}"
STANDARD_COMPOSE_FILE="${PRODUCTION_DIR}/compose.yaml"
COMPACT_COMPOSE_FILE="${PRODUCTION_DIR}/compose.compact.yaml"
COMPACT_LEGACY_WWW_COMPOSE_FILE="${PRODUCTION_DIR}/compose.compact.legacy-www.yaml"
COMPOSE_FILE="${STANDARD_COMPOSE_FILE}"
DEPLOYMENT_STATE_DIR="${REPOSITORY_ROOT}/.deployments"
RUNTIME_DIR="${REPOSITORY_ROOT}/.runtime"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '[atc] %s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

acquire_global_operation_lock() {
  if [[ "${ATC_OPERATION_LOCK_HELD:-false}" == "true" ]]; then
    return
  fi
  require_command flock
  exec 8>/var/lock/ai-trade-cloud-operation.lock
  flock -n 8 || die "another deploy, backup, restore, or rollback operation is running"
  export ATC_OPERATION_LOCK_HELD=true
}

load_production_env() {
  [[ -f "${ENV_FILE}" ]] || die "missing ${ENV_FILE}; copy .env.production.example first"
  if [[ "$(uname -s)" == "Linux" ]]; then
    local mode
    mode="$(stat -c '%a' "${ENV_FILE}")"
    (( (8#${mode} & 8#077) == 0 )) || die "${ENV_FILE} must not be group/world accessible (run chmod 600)"
  fi
  set -a
  # The production environment file is root/operator managed and must contain
  # simple KEY=VALUE entries. It is intentionally never sourced from Git.
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  configure_deployment_profile
}

load_release_metadata() {
  local metadata_file="${1:-${DEPLOYMENT_STATE_DIR}/current.env}"
  [[ -f "${metadata_file}" ]] || die "release metadata is missing: ${metadata_file}"
  set -a
  # shellcheck disable=SC1090
  source "${metadata_file}"
  set +a
  configure_deployment_profile
}

configure_deployment_profile() {
  ATC_DEPLOYMENT_PROFILE="${ATC_DEPLOYMENT_PROFILE:-standard}"
  case "${ATC_DEPLOYMENT_PROFILE}" in
    standard)
      COMPOSE_FILE="${STANDARD_COMPOSE_FILE}"
      ATC_ENABLE_SMTP="${ATC_ENABLE_SMTP:-true}"
      ATC_ENABLE_REMOTE_BACKUP="${ATC_ENABLE_REMOTE_BACKUP:-true}"
      ATC_ENABLE_LEGACY_WWW="${ATC_ENABLE_LEGACY_WWW:-false}"
      ATC_ENABLE_WORKERS="${ATC_ENABLE_WORKERS:-false}"
      ATC_CONFIRMED_EXPAND_CONTRACT="${ATC_CONFIRMED_EXPAND_CONTRACT:-false}"
      ;;
    compact)
      COMPOSE_FILE="${COMPACT_COMPOSE_FILE}"
      ;;
    *)
      die "ATC_DEPLOYMENT_PROFILE must be standard or compact"
      ;;
  esac
  export ATC_DEPLOYMENT_PROFILE ATC_ENABLE_SMTP ATC_ENABLE_REMOTE_BACKUP
  export ATC_ENABLE_LEGACY_WWW ATC_ENABLE_WORKERS
  export ATC_CONFIRMED_EXPAND_CONTRACT
}

compose_file_arguments() {
  COMPOSE_FILE_ARGUMENTS=(--file "${COMPOSE_FILE}")
  if [[ "${ATC_DEPLOYMENT_PROFILE:-standard}" == "compact" \
    && "${ATC_ENABLE_LEGACY_WWW:-false}" == "true" ]]; then
    COMPOSE_FILE_ARGUMENTS+=(--file "${COMPACT_LEGACY_WWW_COMPOSE_FILE}")
  fi
}

render_caddy_sites() {
  local sites_dir="${RUNTIME_DIR}/caddy/sites-enabled"
  local legacy_site="${sites_dir}/legacy-www.caddy"
  local www_site="${sites_dir}/www.caddy"
  mkdir -p "${sites_dir}"
  chown 0:0 "${RUNTIME_DIR}" "${RUNTIME_DIR}/caddy" "${sites_dir}"
  chmod 750 "${RUNTIME_DIR}" "${RUNTIME_DIR}/caddy" "${sites_dir}"
  rm -f "${legacy_site}"

  if [[ "${ATC_DEPLOYMENT_PROFILE:-standard}" == "compact" \
    && "${ATC_ENABLE_LEGACY_WWW:-false}" == "true" ]]; then
    install -o root -g root -m 0640 \
      "${PRODUCTION_DIR}/Caddyfile.legacy-www" "${www_site}"
  elif [[ "${ATC_DEPLOYMENT_PROFILE:-standard}" == "compact" ]]; then
    install -o root -g root -m 0640 \
      "${PRODUCTION_DIR}/Caddyfile.www-redirect" "${www_site}"
  else
    rm -f "${www_site}"
  fi
}

compose() {
  compose_file_arguments
  docker compose \
    --env-file "${ENV_FILE}" \
    "${COMPOSE_FILE_ARGUMENTS[@]}" \
    --profile identity \
    "$@"
}

compose_with_ops() {
  compose_file_arguments
  docker compose \
    --env-file "${ENV_FILE}" \
    "${COMPOSE_FILE_ARGUMENTS[@]}" \
    --profile identity \
    --profile ops \
    "$@"
}

compose_with_workers() {
  compose_file_arguments
  docker compose \
    --env-file "${ENV_FILE}" \
    "${COMPOSE_FILE_ARGUMENTS[@]}" \
    --profile identity \
    --profile workers \
    "$@"
}

render_keycloak_realm() {
  local template="${PRODUCTION_DIR}/keycloak/atc-realm.json.template"
  local output_dir="${RUNTIME_DIR}/keycloak"
  local output="${output_dir}/atc-realm.json"

  require_command python3
  mkdir -p "${output_dir}"
  chown 0:0 "${RUNTIME_DIR}" "${output_dir}"
  chmod 750 "${RUNTIME_DIR}" "${output_dir}"
  python3 "${PRODUCTION_DIR}/scripts/render_keycloak_realm.py" \
    "${template}" "${output}"
  chown 0:0 "${output}"
  # The pinned Keycloak container runs as uid 1000, gid 0. Group-read makes
  # the bind-mounted import readable without exposing it to other host users.
  chmod 640 "${output}"
}

wait_for_public_health() {
  local attempts="${1:-60}"
  local delay="${2:-5}"
  local api_url="https://${ATC_DOMAIN}/api/v1/health/ready"
  local oidc_url="https://auth.${ATC_DOMAIN}/realms/atc/.well-known/openid-configuration"

  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if curl --fail --silent --show-error --max-time 10 "${api_url}" >/dev/null \
      && curl --fail --silent --show-error --max-time 10 "${oidc_url}" >/dev/null; then
      info "public API and OIDC health checks passed"
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

verify_api_oidc_hairpin() {
  compose exec -T api python -c "
import json, os, urllib.error, urllib.parse, urllib.request
issuer = os.environ['OIDC_ISSUER'].rstrip('/')
discovery = json.load(urllib.request.urlopen(
    issuer + '/.well-known/openid-configuration', timeout=10
))
assert discovery['issuer'] == issuer
payload = urllib.parse.urlencode({
    'grant_type': 'authorization_code',
    'code': 'connectivity-smoke-only',
    'redirect_uri': os.environ['OIDC_REDIRECT_URIS'].split(',')[0],
    'client_id': os.environ['OIDC_CLIENT_ID'],
}).encode()
request = urllib.request.Request(discovery['token_endpoint'], data=payload)
try:
    urllib.request.urlopen(request, timeout=10)
except urllib.error.HTTPError as error:
    assert error.code in (400, 401)
else:
    raise AssertionError('invalid OIDC code was unexpectedly accepted')
"
  info "API-container OIDC discovery/token hairpin smoke passed"
}

write_release_metadata() {
  local destination="$1"
  umask 077
  mkdir -p "${DEPLOYMENT_STATE_DIR}"
  {
    printf 'ATC_RELEASE=%q\n' "${ATC_RELEASE}"
    printf 'ATC_COMMIT_SHA=%q\n' "${ATC_COMMIT_SHA}"
    printf 'ATC_MIGRATION_HEAD=%q\n' "${ATC_MIGRATION_HEAD}"
    printf 'ATC_IMAGE_DIGEST=%q\n' "${ATC_IMAGE_DIGEST}"
    printf 'ATC_CONFIG_VERSION=%q\n' "${ATC_CONFIG_VERSION}"
    printf 'ATC_DEPLOYMENT_PROFILE=%q\n' "${ATC_DEPLOYMENT_PROFILE:-standard}"
    printf 'ATC_ENABLE_WORKERS=%q\n' "${ATC_ENABLE_WORKERS:-false}"
  } >"${destination}"
  chmod 600 "${destination}"
}
