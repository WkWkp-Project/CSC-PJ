#!/usr/bin/env bash
# Restore one app's database from a dump made by backup.sh. REPLACES that database's contents.
#   ./scripts/restore.sh myapp backups/2026-11-18/myapp.dump
set -euo pipefail
cd "$(dirname "$0")/.."

APP="${1:-}"; FILE="${2:-}"
if ! [[ "$APP" =~ ^[a-z][a-z0-9_]{1,30}$ ]] || [[ ! -f "$FILE" ]]; then
  echo "usage: $0 <app_name> <dump file>" >&2; exit 2
fi
read -r -a EXEC <<< "${PG_EXEC:-docker compose exec -T postgres}"

read -r -p "This REPLACES everything in database '${APP}'. Type the app name to continue: " ANS
[[ "$ANS" == "$APP" ]] || { echo "cancelled" >&2; exit 1; }

"${EXEC[@]}" pg_restore -U postgres -d "$APP" --clean --if-exists --no-owner --role="$APP" < "$FILE"
echo "restored '${APP}' from ${FILE}"
