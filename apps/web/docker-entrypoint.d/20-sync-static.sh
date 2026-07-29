#!/bin/sh

set -eu

static_root="/usr/share/nginx/html"
asset_root="${static_root}/assets"
retention_days="${ATC_STATIC_ASSET_RETENTION_DAYS:-14}"

mkdir -p "${static_root}"
cp -a /opt/atc-dist/. "${static_root}/"

if [ -d "${asset_root}" ]; then
  find "${asset_root}" -type f -mtime "+${retention_days}" -exec rm -f -- '{}' ';'
fi
