#!/usr/bin/env bash
# Daily backup: one compressed dump per database + the roles (globals).
# Run by cron on the VPS. Keeps KEEP_DAYS days (default 14) under infra/backups/.
# Copy the newest folder OFF the server regularly: a backup on the same disk is not enough.
set -euo pipefail
cd "$(dirname "$0")/.."

read -r -a EXEC <<< "${PG_EXEC:-docker compose exec -T postgres}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OUT="./backups/$(date +%F)"
umask 077
mkdir -p "$OUT"

mapfile -t DBS < <("${EXEC[@]}" psql -U postgres -At -c \
  "SELECT datname FROM pg_database WHERE datistemplate=false AND datname<>'postgres' ORDER BY 1")

for db in "${DBS[@]}"; do
  "${EXEC[@]}" pg_dump -U postgres -Fc "$db" > "$OUT/$db.dump.tmp"
  [[ -s "$OUT/$db.dump.tmp" ]] || { echo "empty dump for $db" >&2; exit 1; }
  mv "$OUT/$db.dump.tmp" "$OUT/$db.dump"
done
"${EXEC[@]}" pg_dumpall -U postgres --globals-only > "$OUT/globals.sql"

find ./backups -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "backup ok: $OUT (${#DBS[@]} databases)"
