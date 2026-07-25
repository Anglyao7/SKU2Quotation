#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

load_production_env

if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  ATC_ENABLE_SMTP="${ATC_ENABLE_SMTP:-true}"
  ATC_ENABLE_REMOTE_BACKUP="${ATC_ENABLE_REMOTE_BACKUP:-true}"
  ATC_ENABLE_LEGACY_WWW="${ATC_ENABLE_LEGACY_WWW:-false}"
  ATC_ENABLE_WORKERS="${ATC_ENABLE_WORKERS:-false}"
  ATC_CONFIRMED_EXPAND_CONTRACT="${ATC_CONFIRMED_EXPAND_CONTRACT:-false}"
fi

boolean_values=(
  ATC_ENABLE_SMTP
  ATC_ENABLE_REMOTE_BACKUP
  ATC_ENABLE_LEGACY_WWW
  ATC_ENABLE_WORKERS
  ATC_CONFIRMED_EXPAND_CONTRACT
)
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]]; then
  boolean_values+=(ATC_COMPACT_MANAGE_SWAP)
fi
for name in "${boolean_values[@]}"; do
  [[ -n "${!name:-}" ]] || die "${name} must be set explicitly to true or false"
  [[ "${!name}" =~ ^(true|false)$ ]] || die "${name} must be true or false"
done

if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  [[ "${ATC_ENABLE_SMTP}" == "true" ]] \
    || die "standard production requires ATC_ENABLE_SMTP=true"
  [[ "${ATC_ENABLE_REMOTE_BACKUP}" == "true" ]] \
    || die "standard production requires ATC_ENABLE_REMOTE_BACKUP=true"
else
  [[ "${ATC_ENABLE_WORKERS}" == "false" ]] \
    || die "compact production runs inline work only; set ATC_ENABLE_WORKERS=false"
  ATC_COMPACT_SWAP_GIB="${ATC_COMPACT_SWAP_GIB:-2}"
  [[ "${ATC_COMPACT_SWAP_GIB}" =~ ^[0-9]+$ ]] \
    || die "ATC_COMPACT_SWAP_GIB must be an integer"
  (( ATC_COMPACT_SWAP_GIB >= 1 && ATC_COMPACT_SWAP_GIB <= 8 )) \
    || die "ATC_COMPACT_SWAP_GIB must be between 1 and 8"
fi

required_values=(
  ATC_DOMAIN
  CADDY_ACME_EMAIL
  POSTGRES_ADMIN_PASSWORD
  ATC_MIGRATION_DB_PASSWORD
  ATC_APP_DB_PASSWORD
  ATC_AUTH_DB_PASSWORD
  ATC_WORKER_DB_PASSWORD
  ATC_SCHEDULER_DB_PASSWORD
  REDIS_PASSWORD
  AUTH_JWT_SECRET
  AUTH_TOKEN_PEPPER
  OIDC_CLIENT_ID
  OIDC_CLIENT_SECRET
  OIDC_BOOTSTRAP_ADMIN_EMAIL
  KEYCLOAK_DB_PASSWORD
  KEYCLOAK_ADMIN_USERNAME
  KEYCLOAK_ADMIN_PASSWORD
  KEYCLOAK_INITIAL_USER_PASSWORD
  BOOTSTRAP_ORGANIZATION_CODE
  BOOTSTRAP_ORGANIZATION_NAME
  BOOTSTRAP_TENANT_SLUG
  BOOTSTRAP_TENANT_NAME
  BOOTSTRAP_OWNER_NAME
  LEGAL_OPERATOR_NAME
  PRIVACY_CONTACT_EMAIL
  ATC_BACKUP_ROOT
)

if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  required_values+=(
    RABBITMQ_USER
    RABBITMQ_PASSWORD
    MINIO_ROOT_USER
    MINIO_ROOT_PASSWORD
    OBJECT_STORAGE_BUCKET
  )
fi
if [[ "${ATC_ENABLE_SMTP}" == "true" ]]; then
  required_values+=(
    KEYCLOAK_SMTP_HOST
    KEYCLOAK_SMTP_PORT
    KEYCLOAK_SMTP_FROM
    KEYCLOAK_SMTP_REPLY_TO
    KEYCLOAK_SMTP_USERNAME
    KEYCLOAK_SMTP_PASSWORD
  )
fi
if [[ "${ATC_ENABLE_REMOTE_BACKUP}" == "true" ]]; then
  required_values+=(RESTIC_REPOSITORY RESTIC_PASSWORD)
fi
if [[ "${ATC_ENABLE_LEGACY_WWW}" == "true" ]]; then
  [[ "${ATC_DEPLOYMENT_PROFILE}" == "compact" ]] \
    || die "the optional legacy www bridge is supported only by compact production"
  required_values+=(ATC_LEGACY_WWW_UPSTREAM ATC_LEGACY_WWW_NETWORK)
fi

for name in "${required_values[@]}"; do
  [[ -n "${!name:-}" ]] || die "${name} is required"
  value="${!name}"
  [[ "${value}" != *REPLACE_WITH* ]] || die "${name} still contains a template placeholder"
done

[[ "${ATC_DOMAIN}" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$ ]] \
  || die "ATC_DOMAIN must be a DNS hostname, not an IP address or URL"
[[ "${ATC_DOMAIN}" != "example.com" && "${ATC_DOMAIN}" != *.example.com ]] \
  || die "ATC_DOMAIN must be your real domain"
[[ "${CADDY_ACME_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
  || die "CADDY_ACME_EMAIL is invalid"
[[ "${OIDC_BOOTSTRAP_ADMIN_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
  || die "OIDC_BOOTSTRAP_ADMIN_EMAIL is invalid"
[[ "${OIDC_BOOTSTRAP_ADMIN_EMAIL}" != *@example.com ]] \
  || die "OIDC_BOOTSTRAP_ADMIN_EMAIL must be a real mailbox"
[[ "${PRIVACY_CONTACT_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
  || die "PRIVACY_CONTACT_EMAIL is invalid"
[[ "${PRIVACY_CONTACT_EMAIL}" != *@example.com ]] \
  || die "PRIVACY_CONTACT_EMAIL must be a real mailbox"
[[ "${PRIVACY_EFFECTIVE_DATE:-2026-07-23}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] \
  || die "PRIVACY_EFFECTIVE_DATE must use YYYY-MM-DD"

if [[ "${ATC_ENABLE_SMTP}" == "true" ]]; then
  [[ "${KEYCLOAK_SMTP_HOST}" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$ ]] \
    || die "KEYCLOAK_SMTP_HOST must be a DNS hostname"
  [[ "${KEYCLOAK_SMTP_PORT}" =~ ^[0-9]+$ ]] \
    || die "KEYCLOAK_SMTP_PORT must be an integer"
  (( KEYCLOAK_SMTP_PORT >= 1 && KEYCLOAK_SMTP_PORT <= 65535 )) \
    || die "KEYCLOAK_SMTP_PORT is outside the valid TCP port range"
  for email_name in KEYCLOAK_SMTP_FROM KEYCLOAK_SMTP_REPLY_TO; do
    email_value="${!email_name}"
    [[ "${email_value}" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
      || die "${email_name} is invalid"
    [[ "${email_value}" != *@example.com ]] \
      || die "${email_name} must be a real mailbox"
  done
  (( ${#KEYCLOAK_SMTP_USERNAME} >= 3 )) \
    || die "KEYCLOAK_SMTP_USERNAME is invalid"
  (( ${#KEYCLOAK_SMTP_PASSWORD} >= 16 )) \
    || die "KEYCLOAK_SMTP_PASSWORD must contain at least 16 characters"
fi

identifier_values=(OIDC_CLIENT_ID KEYCLOAK_ADMIN_USERNAME)
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  identifier_values+=(RABBITMQ_USER MINIO_ROOT_USER OBJECT_STORAGE_BUCKET)
fi
for name in "${identifier_values[@]}"; do
  value="${!name}"
  [[ "${value}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,62}$ ]] \
    || die "${name} must contain only URL-safe identifier characters"
done

secret_values=(
  POSTGRES_ADMIN_PASSWORD
  ATC_MIGRATION_DB_PASSWORD
  ATC_APP_DB_PASSWORD
  ATC_AUTH_DB_PASSWORD
  ATC_WORKER_DB_PASSWORD
  ATC_SCHEDULER_DB_PASSWORD
  REDIS_PASSWORD
  AUTH_JWT_SECRET
  AUTH_TOKEN_PEPPER
  OIDC_CLIENT_SECRET
  KEYCLOAK_DB_PASSWORD
  KEYCLOAK_ADMIN_PASSWORD
)
if [[ "${ATC_DEPLOYMENT_PROFILE}" == "standard" ]]; then
  secret_values+=(RABBITMQ_PASSWORD MINIO_ROOT_PASSWORD)
fi
for name in "${secret_values[@]}"; do
  value="${!name}"
  [[ "${value}" =~ ^[0-9A-Fa-f]{64,}$ ]] \
    || die "${name} must be at least 32 random bytes encoded as hexadecimal"
done

initial_user_password="${KEYCLOAK_INITIAL_USER_PASSWORD}"
(( ${#initial_user_password} >= 8 && ${#initial_user_password} <= 128 )) \
  || die "KEYCLOAK_INITIAL_USER_PASSWORD must contain 8-128 characters"
[[ "${initial_user_password}" =~ [A-Za-z] ]] \
  || die "KEYCLOAK_INITIAL_USER_PASSWORD must contain a letter"
[[ "${initial_user_password}" =~ [[:digit:]] ]] \
  || die "KEYCLOAK_INITIAL_USER_PASSWORD must contain a digit"
[[ ! "${initial_user_password}" =~ [[:space:]] ]] \
  || die "KEYCLOAK_INITIAL_USER_PASSWORD must not contain whitespace"
normalized_initial_password="${initial_user_password,,}"
normalized_bootstrap_email="${OIDC_BOOTSTRAP_ADMIN_EMAIL,,}"
[[ "${normalized_initial_password}" != "${normalized_bootstrap_email}" ]] \
  || die "KEYCLOAK_INITIAL_USER_PASSWORD must differ from the account identifier"
[[ "${normalized_initial_password}" != "${normalized_bootstrap_email%%@*}" ]] \
  || die "KEYCLOAK_INITIAL_USER_PASSWORD must differ from the account identifier"

[[ "${ATC_BACKUP_ROOT}" == /* && "${ATC_BACKUP_ROOT}" != "/" ]] \
  || die "ATC_BACKUP_ROOT must be a dedicated absolute directory"
[[ "${ATC_BACKUP_ROOT}" != "${REPOSITORY_ROOT}"* ]] \
  || die "ATC_BACKUP_ROOT must be outside the Git checkout"
ATC_BACKUP_RETENTION_DAYS="${ATC_BACKUP_RETENTION_DAYS:-14}"
[[ "${ATC_BACKUP_RETENTION_DAYS}" =~ ^[0-9]+$ ]] \
  || die "ATC_BACKUP_RETENTION_DAYS must be an integer"
(( ATC_BACKUP_RETENTION_DAYS >= 7 )) \
  || die "ATC_BACKUP_RETENTION_DAYS must be at least 7"

if [[ "${ATC_ENABLE_REMOTE_BACKUP}" == "true" ]]; then
  [[ "${RESTIC_REPOSITORY}" =~ ^(s3|rest|sftp|azure|gs|rclone): ]] \
    || die "RESTIC_REPOSITORY must be an initialized off-server repository"
  (( ${#RESTIC_PASSWORD} >= 24 )) \
    || die "RESTIC_PASSWORD must contain at least 24 characters"
  require_command restic
  restic snapshots --no-lock --json >/dev/null \
    || die "the off-server restic repository is unavailable or not initialized"
fi

if [[ "${ATC_ENABLE_LEGACY_WWW}" == "true" ]]; then
  [[ "${ATC_LEGACY_WWW_UPSTREAM}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*:[0-9]{1,5}$ ]] \
    || die "ATC_LEGACY_WWW_UPSTREAM must use container-or-host:port"
  [[ "${ATC_LEGACY_WWW_NETWORK}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{1,62}$ ]] \
    || die "ATC_LEGACY_WWW_NETWORK is invalid"
fi

[[ "${IMAGE_INTELLIGENCE_PROFILE:-disabled}" != "deterministic" ]] \
  || die "deterministic image intelligence is forbidden in production"

if [[ -n "${ATC_EXPECTED_PUBLIC_IP:-}" ]]; then
  [[ "${ATC_EXPECTED_PUBLIC_IP}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] \
    || die "ATC_EXPECTED_PUBLIC_IP must be an IPv4 address"
  [[ "${ATC_EXPECTED_PUBLIC_IP}" != "203.0.113.10" ]] \
    || die "ATC_EXPECTED_PUBLIC_IP still contains the documentation address"
fi

info "${ATC_DEPLOYMENT_PROFILE} production environment validation passed"
