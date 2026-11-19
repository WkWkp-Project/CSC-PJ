#!/usr/bin/env bash
# Create one database + one login role for an app, with a random password.
#   ./scripts/new-app-db.sh myapp
# Prints the DATABASE_URL to put in that app's .env. Refuses if the app already exists.
# The role can open only its own database (CONNECT is revoked from everyone else).
set -euo pipefail
cd "$(dirname "$0")/.."

APP="${1:-}"
if ! [[ "$APP" =~ ^[a-z][a-z0-9_]{1,30}$ ]]; then
  echo "usage: $0 <app_name>   (lowercase letters, digits, _ ; starts with a letter; 2-31 chars)" >&2
  exit 2
fi

# PSQL_CMD can be overridden (used by tests); default talks to the compose container.
read -r -a PSQL <<< "${PSQL_CMD:-docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -At}"
HOST_IN_URL="${PG_HOST_IN_URL:-postgres}"

# By default every role may connect to the "postgres" and "template1" databases and read the list of
# databases/roles. Close that (idempotent); the superuser is not affected.
"${PSQL[@]}" <<SQL
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
SQL

exists="$("${PSQL[@]}" -c "SELECT 1 FROM pg_roles WHERE rolname='${APP}' UNION ALL SELECT 1 FROM pg_database WHERE datname='${APP}'")"
if [[ -n "$exists" ]]; then
  echo "'${APP}' already has a role or database. Nothing changed." >&2
  exit 1
fi

if command -v openssl >/dev/null 2>&1; then
  PASS="$(openssl rand -hex 16)"
else
  PASS="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
fi

# Sent on stdin so each statement runs on its own (CREATE DATABASE cannot run in a transaction).
"${PSQL[@]}" <<SQL
CREATE ROLE ${APP} LOGIN PASSWORD '${PASS}';
CREATE DATABASE ${APP} OWNER ${APP};
REVOKE ALL ON DATABASE ${APP} FROM PUBLIC;
SQL

echo "created database and role '${APP}'"
echo "DATABASE_URL=postgresql://${APP}:${PASS}@${HOST_IN_URL}:5432/${APP}"
echo "(copy it into the app's .env now; the password is not stored anywhere else)" >&2
