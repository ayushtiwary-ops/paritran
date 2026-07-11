#!/usr/bin/env bash
# Creates .env from .env.example with random secrets (SPEC section 4).
# Idempotent: an existing .env is never touched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
EXAMPLE_FILE="$REPO_ROOT/.env.example"

if [ -f "$ENV_FILE" ]; then
  # Existing values are never modified, but keys that .env.example has and
  # .env lacks are appended with generated secrets. Without this, an .env
  # created before a milestone added new keys would feed empty strings into
  # compose, and the api now refuses to start on placeholder/empty secrets.
  added=0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      \#*|"") continue ;;
    esac
    key="${line%%=*}"
    if ! grep -qE "^${key}=" "$ENV_FILE"; then
      value="${line#*=}"
      while [[ "$value" == *CHANGE_ME* ]]; do
        value="${value/CHANGE_ME/$(openssl rand -hex 24)}"
      done
      printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
      echo "added missing key: $key"
      added=1
    fi
  done < "$EXAMPLE_FILE"
  if [ "$added" -eq 1 ]; then
    # Re-derive the two DSNs only if they were among the appended keys,
    # so they embed the real role passwords rather than fresh randoms.
    admin_password="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"
    app_password="$(grep -E '^APP_DB_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"
    sed -e "s|^ADMIN_DATABASE_URL=postgresql://paritran_admin:[a-f0-9]*@|ADMIN_DATABASE_URL=postgresql://paritran_admin:${admin_password}@|" \
        "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo "updated $ENV_FILE with missing keys (existing values untouched)."
  else
    echo ".env already exists and has every key, leaving it untouched."
  fi
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

# Keep the two DSNs consistent with their generated role passwords
# (SPEC section 4 role split: paritran_admin owns, paritran_app runs).
# docker-compose.yml derives both URLs the same way, so they can never diverge.
admin_password="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"
app_password="$(grep -E '^APP_DB_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2-)"
sed -e "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://paritran_app:${app_password}@db:5432/paritran|" \
    -e "s|^ADMIN_DATABASE_URL=.*|ADMIN_DATABASE_URL=postgresql://paritran_admin:${admin_password}@db:5432/paritran|" \
    "$ENV_FILE" > "$ENV_FILE.tmp"
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
