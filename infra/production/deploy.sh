#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

TARGET_REF="${1:-}"
[[ -n "${TARGET_REF}" ]] || die "usage: $0 <git-commit-or-tag>"
(( EUID == 0 )) || die "production deployment must run as root"

require_command git
require_command docker
require_command curl
require_command openssl
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
acquire_global_operation_lock

"${SCRIPT_DIR}/scripts/validate_env.sh"
load_production_env

ensure_compact_swap() {
  [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]] || return 0
  [[ "${ATC_COMPACT_MANAGE_SWAP}" == "true" ]] || return 0

  local desired_gib="${ATC_COMPACT_SWAP_GIB:-2}"
  local desired_kib=$((desired_gib * 1024 * 1024))
  local current_kib
  current_kib="$(awk '/SwapTotal/ {print $2}' /proc/meminfo)"
  if (( current_kib >= desired_kib )); then
    info "existing swap already satisfies the compact ${desired_gib} GiB target"
    return 0
  fi

  local swap_file="/var/lib/ai-trade-cloud/swapfile"
  require_command mkswap
  require_command swapon
  mkdir -p "$(dirname "${swap_file}")"
  if [[ ! -e "${swap_file}" ]]; then
    info "allocating the compact deployment ${desired_gib} GiB swap file"
    if command -v fallocate >/dev/null 2>&1; then
      fallocate -l "${desired_gib}G" "${swap_file}"
    else
      dd if=/dev/zero of="${swap_file}" bs=1M count="$((desired_gib * 1024))" status=progress
    fi
  fi
  [[ -f "${swap_file}" ]] || die "compact swap path is not a regular file: ${swap_file}"
  chmod 600 "${swap_file}"
  if ! swapon --show=NAME --noheadings | grep -Fxq "${swap_file}"; then
    mkswap "${swap_file}" >/dev/null
    swapon "${swap_file}"
  fi
  if ! grep -Eq "^${swap_file//\//\\/}[[:space:]]+none[[:space:]]+swap([[:space:]]|$)" /etc/fstab; then
    printf '%s\n' "${swap_file} none swap sw 0 0" >>/etc/fstab
  fi
}

prepare_web_static_store() {
  local static_dir="${RUNTIME_DIR}/web-static"
  local adoption_marker="${static_dir}/.atc-persistent-static"
  local current_web_id=""
  local archive_container=""
  local image=""

  mkdir -p "${static_dir}"
  if [[ ! -f "${adoption_marker}" ]]; then
    current_web_id="$(compose ps -q web 2>/dev/null || true)"
    if [[ -n "${current_web_id}" ]] \
      && [[ "$(docker inspect --format '{{.State.Running}}' "${current_web_id}" 2>/dev/null || true)" == "true" ]]; then
      info "preserving the currently served frontend assets for open browser sessions"
      docker cp "${current_web_id}:/usr/share/nginx/html/." "${static_dir}"
    fi
    mkdir -p "${static_dir}/assets"
    info "adopting recent immutable frontend assets into the persistent store"
    while IFS= read -r image; do
      [[ -n "${image}" && "${image}" != *":<none>" ]] || continue
      archive_container="$(docker create --entrypoint /bin/true "${image}")"
      docker cp \
        "${archive_container}:/usr/share/nginx/html/assets/." \
        "${static_dir}/assets" \
        || true
      docker rm "${archive_container}" >/dev/null
    done < <(
      docker images --format '{{.Repository}}:{{.Tag}}' atc-web \
        | head -n 12
    )
    touch "${adoption_marker}"
  fi
  chown -R 101:101 "${static_dir}"
}

if [[ "$(uname -s)" == "Linux" ]]; then
  available_kib="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
  if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
    (( available_kib >= 3 * 1024 * 1024 )) \
      || die "compact production requires at least 3 GiB RAM"
    ensure_compact_swap
    required_disk_kib=$((8 * 1024 * 1024))
  else
    if (( available_kib < 6 * 1024 * 1024 )) && [[ "${ATC_ALLOW_LOW_MEMORY:-false}" != "true" ]]; then
      die "less than 6 GiB RAM detected; use an 8 GiB server or explicitly set ATC_ALLOW_LOW_MEMORY=true"
    fi
    required_disk_kib=$((15 * 1024 * 1024))
  fi
  available_disk_kib="$(df -Pk "${REPOSITORY_ROOT}" | awk 'NR == 2 {print $4}')"
  (( available_disk_kib >= required_disk_kib )) \
    || die "insufficient free disk space before a production build"
fi

if [[ -n "${ATC_EXPECTED_PUBLIC_IP:-}" ]]; then
  require_command getent
  mapfile -t dns_addresses < <(getent ahostsv4 "${ATC_DOMAIN}" | awk '{print $1}' | sort -u)
  printf '%s\n' "${dns_addresses[@]}" | grep -Fxq "${ATC_EXPECTED_PUBLIC_IP}" \
    || die "${ATC_DOMAIN} does not resolve to ATC_EXPECTED_PUBLIC_IP"
  mapfile -t auth_dns_addresses < <(getent ahostsv4 "auth.${ATC_DOMAIN}" | awk '{print $1}' | sort -u)
  printf '%s\n' "${auth_dns_addresses[@]}" | grep -Fxq "${ATC_EXPECTED_PUBLIC_IP}" \
    || die "auth.${ATC_DOMAIN} does not resolve to ATC_EXPECTED_PUBLIC_IP"
fi

cd "${REPOSITORY_ROOT}"
git diff --quiet && git diff --cached --quiet \
  || die "tracked files are modified; deployment refuses to overwrite server-side edits"

previous_git_commit="$(git rev-parse HEAD)"
mkdir -p "${DEPLOYMENT_STATE_DIR}"
had_previous_release=false
if [[ -f "${DEPLOYMENT_STATE_DIR}/current.env" ]]; then
  had_previous_release=true
  cp "${DEPLOYMENT_STATE_DIR}/current.env" "${DEPLOYMENT_STATE_DIR}/previous.env"
else
  compose_project="ai-trade-cloud"
  if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
    compose_project="ai-trade-cloud-compact"
  fi
  for managed_service in api web caddy tenant-worker product-event-consumer; do
    if docker ps --all --quiet \
      --filter "label=com.docker.compose.project=${compose_project}" \
      --filter "label=com.docker.compose.service=${managed_service}" \
      | grep -q .; then
      die "${DEPLOYMENT_STATE_DIR}/current.env is missing while managed application workloads exist"
    fi
  done
fi

if [[ "${TARGET_REF}" =~ ^[0-9a-f]{40}$ ]] \
  && resolved_commit="$(git rev-parse --verify "${TARGET_REF}^{commit}" 2>/dev/null)"; then
  info "using the requested immutable release already present in the local object store"
else
  info "fetching the requested immutable release"
  git fetch --tags --prune origin
fi
if [[ -n "${resolved_commit:-}" ]]; then
  :
elif resolved_commit="$(git rev-parse --verify "${TARGET_REF}^{commit}" 2>/dev/null)"; then
  :
elif resolved_commit="$(git rev-parse --verify "origin/${TARGET_REF}^{commit}" 2>/dev/null)"; then
  :
else
  die "cannot resolve ${TARGET_REF} to a fetched commit"
fi
[[ "${resolved_commit}" =~ ^[0-9a-f]{40}$ ]] || die "resolved deployment target is not a full commit"
git checkout --detach "${resolved_commit}"

export ATC_COMMIT_SHA="${resolved_commit}"
export ATC_COMPOSE_COMMIT_SHA="${resolved_commit}"
export ATC_RELEASE="production-$(date -u +%Y%m%dT%H%M%SZ)-${resolved_commit:0:12}"
export ATC_MIGRATION_HEAD="20260820_0102"
export ATC_CONFIG_VERSION="production-v1-${resolved_commit:0:12}"
export ATC_IMAGE_DIGEST="sha256:$(printf '%064d' 0)"
export ATC_ENABLE_WORKERS="${ATC_ENABLE_WORKERS:-false}"
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  export ATC_ENABLE_WORKERS=false
fi

render_keycloak_realm
render_caddy_sites
compose_with_ops config --quiet
prepare_web_static_store

rollback_started=false

rollback_on_failure() {
  local status="${1:-1}"
  if [[ "${rollback_started}" == "true" ]]; then
    exit "${status}"
  fi
  rollback_started=true
  trap - ERR INT TERM HUP
  set +e
  printf '\n[atc] deployment failed with status %s\n' "${status}" >&2
  if [[ -f "${DEPLOYMENT_STATE_DIR}/previous.env" ]]; then
    printf '[atc] restoring the previously recorded application release\n' >&2
    ATC_OPERATION_LOCK_HELD=true \
      "${SCRIPT_DIR}/rollback.sh" "${DEPLOYMENT_STATE_DIR}/previous.env" || true
  else
    printf '[atc] stopping the unrecorded first-release public workloads\n' >&2
    compose stop caddy web api keycloak >/dev/null 2>&1 || true
    if [[ "${ATC_ENABLE_WORKERS:-false}" == "true" ]]; then
      compose_with_workers stop tenant-worker product-event-consumer \
        >/dev/null 2>&1 || true
    fi
    git checkout --detach "${previous_git_commit}" || true
    printf '[atc] no previous production release metadata exists; dependency containers and volumes were left intact\n' >&2
  fi
  exit "${status}"
}
trap 'rollback_on_failure $?' ERR
trap 'rollback_on_failure 130' INT
trap 'rollback_on_failure 143' TERM
trap 'rollback_on_failure 129' HUP

info "pulling pinned dependency images"
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  compose pull caddy postgres redis keycloak-postgres keycloak object-storage-bootstrap
  compose_with_ops pull backup-local-objects restore-local-objects
else
  compose pull caddy postgres redis rabbitmq keycloak-postgres keycloak
  compose_with_ops pull backup-rabbitmq restore-rabbitmq
fi

info "building immutable application images before touching running workloads"
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  export COMPOSE_PARALLEL_LIMIT=1
  info "compact build 1/3: API"
  compose_with_ops build --pull api
  info "compact build 2/3: migration and bootstrap image"
  compose_with_ops build --pull db-bootstrap
  info "compact build 3/3: web"
  compose_with_ops build --pull web
else
  compose_with_ops build --pull api tenant-worker product-event-consumer web db-bootstrap minio
fi
export ATC_IMAGE_DIGEST
ATC_IMAGE_DIGEST="$(docker image inspect "atc-api:${ATC_COMMIT_SHA}" --format '{{.Id}}')"
[[ "${ATC_IMAGE_DIGEST}" == sha256:* ]] || die "could not determine the API image digest"

if [[ "${had_previous_release}" == "true" ]]; then
  [[ "${ATC_CONFIRMED_EXPAND_CONTRACT:-false}" == "true" ]] \
    || die "set ATC_CONFIRMED_EXPAND_CONTRACT=true only after confirming this migration is backward compatible"
  info "creating a verified backup and retaining the stopped-writer migration window"
  ATC_BACKUP_LEAVE_WRITERS_STOPPED=true \
    ATC_OPERATION_LOCK_HELD=true "${SCRIPT_DIR}/backup.sh"
fi

info "starting or retaining durable dependencies"
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  compose up --detach --wait postgres redis keycloak-postgres keycloak
  info "initializing the compact local object volume"
  compose run --rm --no-deps object-storage-bootstrap
else
  compose up --detach --wait postgres redis rabbitmq minio keycloak-postgres keycloak
fi

info "bootstrapping roles, migrating, applying grants, and preparing dependencies"
compose_with_ops run --rm --no-deps db-bootstrap
compose_with_ops run --rm --no-deps db-migrate
compose_with_ops run --rm --no-deps db-grants
compose_with_ops run --rm --no-deps production-bootstrap
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  compose_with_ops run --rm --no-deps dependency-bootstrap
fi

info "reconciling Keycloak realm and confidential OIDC client"
"${SCRIPT_DIR}/keycloak-reconcile.sh"

info "rolling out API, web, and TLS edge without taking data services down"
compose up --detach --no-deps --wait --remove-orphans api web caddy
if [[ "${ATC_ENABLE_WORKERS}" == "true" ]]; then
  compose_with_workers up --detach --no-deps --wait \
    tenant-worker product-event-consumer
fi

wait_for_public_health 60 5
verify_api_oidc_connectivity

if [[ "${had_previous_release}" == "false" ]]; then
  info "creating the mandatory initial local backup"
  ATC_OPERATION_LOCK_HELD=true "${SCRIPT_DIR}/backup.sh"
fi
"${SCRIPT_DIR}/install-backup-timer.sh"

write_release_metadata "${DEPLOYMENT_STATE_DIR}/next.env"
mv "${DEPLOYMENT_STATE_DIR}/next.env" "${DEPLOYMENT_STATE_DIR}/current.env"
trap - ERR INT TERM HUP

info "deployment completed: ${ATC_RELEASE}"
info "release metadata: ${DEPLOYMENT_STATE_DIR}/current.env"
info "rollback command: ${SCRIPT_DIR}/rollback.sh ${DEPLOYMENT_STATE_DIR}/previous.env"
