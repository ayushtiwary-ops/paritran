#!/usr/bin/env bash
# Creates .env from .env.example with random secrets (SPEC section 4).
# Idempotent: an existing .env is never touched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
EXAMPLE_FILE="$REPO_ROOT/.env.example"

if [ -f "$ENV_FILE" ]; then
  echo ".env already exists, leaving it untouched."
  exit 0
fi

if [ ! -f "$EXAMPLE_FILE" ]; then
  echo "error: $EXAMPLE_FILE not found" >&2
  exit 1
fi

# Replace every CHANGE_ME with its own unique random value.
# JWT_SECRET gets 64 hex chars per the SPEC section 4 comment; everything else gets 48.
while IFS= read -r line || [ -n "$line" ]; do
  while [[ "$line" == *CHANGE_ME* ]]; do
    if [[ "$line" == JWT_SECRET=* ]]; then
      secret="$(openssl rand -hex 32)"
    else
      secret="$(openssl rand -hex 24)"
    fi
    line="${line/CHANGE_ME/$secret}"
  done
  printf '%s\n' "$line"
done < "$EXAMPLE_FILE" > "$ENV_FILE"

# Keep DATABASE_URL consistent with the generated POSTGRES_PASSWORD.
# docker-compose.yml also derives DATABASE_URL from POSTGRES_PASSWORD, so the two can never diverge.
pg_password="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"
db_url="postgresql://paritran_app:${pg_password}@db:5432/paritran"
sed -e "s|^DATABASE_URL=.*|DATABASE_URL=${db_url}|" "$ENV_FILE" > "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"

chmod 600 "$ENV_FILE"

get_value() { grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2-; }

echo "Wrote $ENV_FILE (chmod 600)."
echo ""
echo "WARNING: the credentials below are shown only this once. Record them now."
echo "  officer1    : $(get_value OFFICER1_PASSWORD)"
echo "  supervisor1 : $(get_value SUPERVISOR1_PASSWORD)"
echo "  auditor1    : $(get_value AUDITOR1_PASSWORD)"
echo "  grafana     : admin / $(get_value GRAFANA_ADMIN_PASSWORD)"
