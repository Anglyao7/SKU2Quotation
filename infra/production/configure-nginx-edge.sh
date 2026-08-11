#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${SCRIPT_DIR}/scripts/lib.sh"

(( EUID == 0 )) || die "outer Nginx configuration must run as root"
require_command nginx
require_command sed
load_production_env

[[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]] \
  || die "the outer Nginx topology requires compact production"
[[ "${ATC_EDGE_PROXY}" == "nginx" ]] \
  || die "set ATC_EDGE_PROXY=nginx before configuring the outer Nginx"
[[ "${ATC_DOMAIN}" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$ ]] \
  || die "ATC_DOMAIN must be a DNS hostname"
[[ "${ATC_NGINX_EDGE_PORT}" =~ ^[0-9]+$ ]] \
  || die "ATC_NGINX_EDGE_PORT must be an integer"
(( ATC_NGINX_EDGE_PORT >= 1024 && ATC_NGINX_EDGE_PORT <= 65535 )) \
  || die "ATC_NGINX_EDGE_PORT must be between 1024 and 65535"

template="${SCRIPT_DIR}/nginx/ai-trade-cloud.conf.in"
available_dir="/etc/nginx/sites-available"
enabled_dir="/etc/nginx/sites-enabled"
destination="${available_dir}/ai-trade-cloud.conf"
enabled_link="${enabled_dir}/ai-trade-cloud.conf"
default_link="${enabled_dir}/default"
temporary="$(mktemp)"
backup="$(mktemp)"
had_previous=false
default_was_enabled=false

cleanup() {
  rm -f "${temporary}" "${backup}"
}
trap cleanup EXIT

sed \
  -e "s/__ATC_DOMAIN__/${ATC_DOMAIN}/g" \
  -e "s/__ATC_NGINX_EDGE_PORT__/${ATC_NGINX_EDGE_PORT}/g" \
  "${template}" >"${temporary}"

mkdir -p "${available_dir}" "${enabled_dir}"
if [[ -f "${destination}" ]]; then
  cp -a "${destination}" "${backup}"
  had_previous=true
fi
if [[ -L "${default_link}" ]]; then
  default_was_enabled=true
fi

install -o root -g root -m 0644 "${temporary}" "${destination}"
ln -sfn "${destination}" "${enabled_link}"
if [[ "${default_was_enabled}" == "true" ]]; then
  unlink "${default_link}"
fi

if ! nginx -t; then
  if [[ "${had_previous}" == "true" ]]; then
    install -o root -g root -m 0644 "${backup}" "${destination}"
  else
    rm -f "${destination}" "${enabled_link}"
  fi
  if [[ "${default_was_enabled}" == "true" ]]; then
    ln -sfn /etc/nginx/sites-available/default "${default_link}"
  fi
  nginx -t >/dev/null 2>&1 || true
  die "outer Nginx configuration validation failed; the previous configuration was restored"
fi

if pgrep -x nginx >/dev/null 2>&1; then
  nginx -s reload
else
  nginx
fi
info "outer Nginx now proxies ${ATC_DOMAIN}, www, and auth to 127.0.0.1:${ATC_NGINX_EDGE_PORT}"
