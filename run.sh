#!/usr/bin/env bash
# Reproduce every Section 08 metric with a fixed seed.
set -e
python3 src/paritran_prototype.py
echo
echo "Results written to results.json (seed 42, synthetic data, zero real PII)."
