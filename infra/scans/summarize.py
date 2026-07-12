#!/usr/bin/env python3
"""Summarize scanner artifacts into infra/scans/out/summary.json.

Invoked by run_all.sh with the output directory as argv[1]. Reads the
per-tool JSON artifacts plus the _meta.tsv run log (tool, status,
exit_code, ran_at) and writes summary.json:

    {"generated_at": "...Z",
     "summary": {<tool>: {"status": ..., "critical": n, "high": n,
                          "medium": n, "low": n, "unknown": n,
                          "findings_total": n, "ran_at": ...,
                          "note": ...?, "error_detail": ...?}}}

Status values: "ok" (ran, zero findings), "findings" (ran, nonzero),
"not_installed", "error" (tool present but failed to run; counts are
null because nothing was measured). Honesty mappings are documented in
run_all.sh; stdlib only, no dependencies.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SEVERITIES = ("critical", "high", "medium", "low", "unknown")


def empty_counts() -> dict:
    return {s: 0 for s in SEVERITIES}


def load(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def parse_pip_audit(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    total = 0
    for dep in doc.get("dependencies", []):
        total += len(dep.get("vulns", []))
    note = (
        "pip-audit reports no severity field; findings_total only"
        if total
        else None
    )
    return counts, total, note


def parse_npm_audit(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    meta = doc.get("metadata", {}).get("vulnerabilities", {})
    counts["critical"] = meta.get("critical", 0)
    counts["high"] = meta.get("high", 0)
    counts["medium"] = meta.get("moderate", 0)
    counts["low"] = meta.get("low", 0) + meta.get("info", 0)
    total = meta.get("total", sum(counts.values()))
    return counts, total, "npm 'moderate' counted as medium; 'info' as low"


def parse_bandit(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    results = doc.get("results", [])
    for item in results:
        sev = item.get("issue_severity", "UNDEFINED").lower()
        counts[sev if sev in SEVERITIES else "unknown"] += 1
    return counts, len(results), "bandit has no 'critical' grade; high is its maximum"


def parse_semgrep(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    mapping = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
    results = doc.get("results", [])
    for item in results:
        sev = item.get("extra", {}).get("severity", "")
        counts[mapping.get(sev, "unknown")] += 1
    return counts, len(results), "semgrep ERROR->high, WARNING->medium, INFO->low"


def parse_gitleaks(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    findings = doc if isinstance(doc, list) else []
    counts["critical"] = len(findings)
    return counts, len(findings), "every detected secret counted as critical"


def parse_trivy(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    total = 0
    for result in doc.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            sev = vuln.get("Severity", "UNKNOWN").lower()
            counts[sev if sev in SEVERITIES else "unknown"] += 1
            total += 1
        for secret in result.get("Secrets", []) or []:
            sev = secret.get("Severity", "UNKNOWN").lower()
            counts[sev if sev in SEVERITIES else "unknown"] += 1
            total += 1
        for misconf in result.get("Misconfigurations", []) or []:
            sev = misconf.get("Severity", "UNKNOWN").lower()
            counts[sev if sev in SEVERITIES else "unknown"] += 1
            total += 1
    return counts, total, None


def parse_grype(doc) -> tuple[dict, int, str | None]:
    counts = empty_counts()
    matches = doc.get("matches", []) or []
    for match in matches:
        sev = (match.get("vulnerability", {}).get("severity") or "unknown").lower()
        counts[sev if sev in SEVERITIES else "unknown"] += 1
    return counts, len(matches), None


PARSERS = {
    "pip-audit": parse_pip_audit,
    "npm-audit": parse_npm_audit,
    "bandit": parse_bandit,
    "semgrep": parse_semgrep,
    "gitleaks": parse_gitleaks,
    "trivy-fs": parse_trivy,
    "trivy-image": parse_trivy,
    "grype": parse_grype,
}


def main() -> int:
    out = Path(sys.argv[1])
    meta: dict[str, tuple[str, str, str]] = {}
    for line in (out / "_meta.tsv").read_text().splitlines():
        tool, status, exit_code, ran_at = line.split("\t")
        meta[tool] = (status, exit_code, ran_at)

    summary: dict[str, dict] = {}
    for tool, parser in PARSERS.items():
        status, exit_code, ran_at = meta.get(tool, ("not_installed", "-", None))
        entry: dict = {"status": status, "ran_at": ran_at}
        if status == "ran":
            doc = load(out / f"{tool}.json")
            if doc is None:
                entry["status"] = "error"
                entry["error_detail"] = f"{tool}.json missing or unparseable"
                entry.update({s: None for s in SEVERITIES})
                entry["findings_total"] = None
            else:
                counts, total, note = parser(doc)
                entry["status"] = "findings" if total else "ok"
                entry.update(counts)
                entry["findings_total"] = total
                if note:
                    entry["note"] = note
        elif status == "error":
            entry["error_detail"] = f"scanner exited {exit_code}; see {tool}.log"
            entry.update({s: None for s in SEVERITIES})
            entry["findings_total"] = None
        else:  # not_installed
            entry.update({s: None for s in SEVERITIES})
            entry["findings_total"] = None
        summary[tool] = entry

    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary,
    }
    (out / "summary.json").write_text(json.dumps(doc, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
