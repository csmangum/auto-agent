#!/usr/bin/env bash
# Idempotent bootstrap for claim-agent Python test environment.
# Used by Cursor Cloud agents and local dev. Safe to run multiple times.
set -euo pipefail
cd "$(dirname "$0")/.."

# Create .venv if missing or incomplete
if [[ ! -d .venv ]] || [[ ! -f .venv/bin/pip ]]; then
  rm -rf .venv
  if python3 -m venv .venv 2>/dev/null; then
    : # venv with pip created successfully
  else
    # ensurepip not available (e.g. minimal Ubuntu without python3-venv)
    python3 -m venv .venv --without-pip
    if ! curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python3 -; then
      rm -rf .venv
      exit 1
    fi
  fi
fi

# Install claim-agent with dev deps (pytest, pytest-cov, PyJWT)
.venv/bin/pip install -e ".[dev]" -q

echo "claim-agent test env ready: .venv + pytest"
