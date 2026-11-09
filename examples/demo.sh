#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"
python -m envguard_ci --version
python -m envguard_ci diff --baseline tests/fixtures/baseline.json --current tests/fixtures/package_missing.json
python -m envguard_ci graph --snapshot tests/fixtures/baseline.json
