#!/usr/bin/env bash
# Idempotent bootstrap for claim-agent Python test environment.
# Used by Cursor Cloud agents and local dev. Safe to run multiple times.
set -euo pipefail
cd "$(dirname "$0")/.."

# Create .venv if missing
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# Install claim-agent with dev deps (pytest, pytest-cov, PyJWT)
.venv/bin/pip install -e ".[dev]" -q

echo "claim-agent test env ready: .venv + pytest"
