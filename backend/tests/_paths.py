"""Repo-artifact locations for tests, container-safe.

On the host, backend/tests/ sits two levels below the repo root, so the
walk works. In the api container only backend/ is present, so compose
mounts the repo's results.json and dataset/samples read-only and points
these env vars at them. One source of truth either way; no copies.
"""

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

ORACLE_RESULTS = Path(
    os.environ.get("PARITRAN_RESULTS_JSON", _REPO_ROOT / "results.json")
)
SAMPLES_DIR = Path(
    os.environ.get("PARITRAN_SAMPLES_DIR", _REPO_ROOT / "dataset" / "samples")
)
