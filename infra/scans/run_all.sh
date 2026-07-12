#!/usr/bin/env bash
# Security scan harness (SPEC section 11, Milestone 7).
#
# Runs every scanner that is actually installed and records the ones
# that are not as {"status": "not_installed"} -- absence is reported,
# never papered over. Each tool writes its raw JSON artifact to
# infra/scans/out/<tool>.json; the summarizer then writes
# infra/scans/out/summary.json shaped as
#   {"generated_at": ..., "summary": {<tool>: {status, critical, high,
#     medium, low, findings_total, ran_at, ...}}}
# which is what `jq .summary infra/scans/out/summary.json` (SPEC 17
# step 6) and GET /api/security/posture read.
#
# Severity honesty notes (also encoded in summarize.py):
# - pip-audit emits no severity field; its findings count only toward
#   findings_total and the entry carries an explanatory note.
# - gitleaks findings are all counted as critical: a leaked secret has
#   no lesser grade. Reports are redacted (--redact).
# - npm audit "moderate" maps to "medium"; trivy/grype "UNKNOWN"
#   severity is reported as "unknown", not silently dropped.
#
# Tools that need the network (pip-audit advisory DB, npm registry,
# semgrep --config auto, trivy/grype DB updates) record status "error"
# with the exit code when offline; the venue bundle pre-fetches the
# trivy/grype DBs (SPEC 11) so those two run offline.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/infra/scans/out"
mkdir -p "$OUT"
META="$OUT/_meta.tsv"
: > "$META"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# record <tool> <status> <exit_code>
record() {
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$(now_utc)" >> "$META"
}

not_installed() {
    local tool="$1"
    printf '{"status": "not_installed"}\n' > "$OUT/$tool.json"
    record "$tool" "not_installed" "-"
    echo "-- $tool: not installed (recorded honestly)"
}

# run_tool <tool> <ok_codes_regex> <logfile> -- <command...>
# Scanners exit nonzero when they FIND things; those codes are in
# ok_codes. Anything else is a real error and is recorded as such.
run_tool() {
    local tool="$1" ok_codes="$2" log="$3"; shift 4
    local rc=0
    "$@" > "$log" 2>&1 || rc=$?
    if [[ "$rc" =~ ^($ok_codes)$ ]]; then
        record "$tool" "ran" "$rc"
        echo "-- $tool: ran (exit $rc)"
    else
        record "$tool" "error" "$rc"
        echo "-- $tool: ERROR (exit $rc); see $log" >&2
    fi
}

echo "== Paritran security scans -> $OUT"

# 1. pip-audit over the pinned backend runtime requirements.
if command -v pip-audit > /dev/null; then
    run_tool pip-audit '0|1' "$OUT/pip-audit.log" -- \
        pip-audit -r "$ROOT/backend/requirements.txt" \
        -f json -o "$OUT/pip-audit.json"
else
    not_installed pip-audit
fi

# 2. npm audit over the frontend lockfile (JSON goes to stdout).
if command -v npm > /dev/null; then
    rc=0
    (cd "$ROOT/frontend" && npm audit --json) \
        > "$OUT/npm-audit.json" 2> "$OUT/npm-audit.log" || rc=$?
    if [[ "$rc" == 0 || "$rc" == 1 ]]; then
        record npm-audit "ran" "$rc"
        echo "-- npm-audit: ran (exit $rc)"
    else
        record npm-audit "error" "$rc"
        echo "-- npm-audit: ERROR (exit $rc); see $OUT/npm-audit.log" >&2
    fi
else
    not_installed npm-audit
fi

# 3. Bandit over the backend package.
if command -v bandit > /dev/null; then
    run_tool bandit '0|1' "$OUT/bandit.log" -- \
        bandit -r "$ROOT/backend/paritran" -q -f json -o "$OUT/bandit.json"
else
    not_installed bandit
fi

# 4. Semgrep (--config auto needs the registry AND metrics enabled --
#    semgrep refuses auto with metrics off; offline -> honest error).
if command -v semgrep > /dev/null; then
    run_tool semgrep '0|1' "$OUT/semgrep.log" -- \
        semgrep scan --config auto --json \
        --output "$OUT/semgrep.json" \
        "$ROOT/backend/paritran" "$ROOT/frontend/src" "$ROOT/src"
else
    not_installed semgrep
fi

# 5. Gitleaks filesystem scan (redacted report; allowlist documented in
#    infra/scans/gitleaks.toml and docs/SECURITY.md).
if command -v gitleaks > /dev/null; then
    run_tool gitleaks '0|1' "$OUT/gitleaks.log" -- \
        gitleaks dir "$ROOT" --redact --exit-code 1 \
        --config "$ROOT/infra/scans/gitleaks.toml" \
        --report-format json --report-path "$OUT/gitleaks.json"
else
    not_installed gitleaks
fi

# 6 + 7. Trivy: repo filesystem, then the built api image if present.
if command -v trivy > /dev/null; then
    run_tool trivy-fs '0|1' "$OUT/trivy-fs.log" -- \
        trivy fs --exit-code 1 --format json -o "$OUT/trivy-fs.json" "$ROOT"
    if docker image inspect paritran_repo-api:latest > /dev/null 2>&1; then
        run_tool trivy-image '0|1' "$OUT/trivy-image.log" -- \
            trivy image --exit-code 1 --format json \
            -o "$OUT/trivy-image.json" paritran_repo-api:latest
    else
        printf '{"status": "not_installed", "note": "image paritran_repo-api:latest not present on this host"}\n' \
            > "$OUT/trivy-image.json"
        record trivy-image "not_installed" "-"
        echo "-- trivy-image: api image not built on this host (recorded honestly)"
    fi
else
    not_installed trivy-fs
    not_installed trivy-image
fi

# 8. Grype over the repo directory. No --fail-on: the severity gate is
#    the summary (and CI), not grype's exit code, which is 2 both for
#    threshold hits and for real errors -- indistinguishable.
if command -v grype > /dev/null; then
    run_tool grype '0' "$OUT/grype.log" -- \
        grype "dir:$ROOT" -o "json=$OUT/grype.json"
else
    not_installed grype
fi

# Summarize everything into summary.json (python3 ships on the demo Mac
# and in CI; jq stays available for consumers per SPEC 17 step 6).
python3 "$ROOT/infra/scans/summarize.py" "$OUT"

echo "== summary:"
if command -v jq > /dev/null; then
    jq .summary "$OUT/summary.json"
else
    python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["summary"], indent=2))' "$OUT/summary.json"
fi
