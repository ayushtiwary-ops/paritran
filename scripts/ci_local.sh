#!/usr/bin/env bash
# Offline CI equivalent (SPEC section 11). The demo-day source of truth.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/3] backend tests"
(cd "$REPO_ROOT/backend" && python3 -m pytest -q)

echo "==> [2/3] frontend build"
(cd "$REPO_ROOT/frontend" && npm ci && npm run build)

echo "==> [3/3] truth-rule spot-check (SPEC section 17 step 5)"
cd "$REPO_ROOT"
# Last command on purpose: its exit code is the script's verdict.
# A match means a hardcoded metric leaked into the frontend and the check fails.
! grep -rInE "0\.957|0\.966|0\.962|90\.8|52\.4|\b297\b|40 ?/ ?10|tamper_detected" frontend/src
