#!/usr/bin/env bash
# tests/test_canary_deploy.sh — lightweight smoke tests for scripts/canary_deploy.sh.
#
# Runs every subcommand in --dry-run mode with a mock kubectl so no real cluster
# is needed.  Each test asserts exit-code and that expected deployment names
# appear in the logged output.
#
# Usage:
#   bash tests/test_canary_deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CANARY_SCRIPT="$SCRIPT_DIR/../scripts/canary_deploy.sh"

# ── Mock kubectl ──────────────────────────────────────────────────────────────
MOCK_DIR="$(mktemp -d)"
trap 'rm -rf "$MOCK_DIR"' EXIT

cat > "$MOCK_DIR/kubectl" <<'EOF'
#!/usr/bin/env bash
echo "[mock-kubectl] $@"
exit 0
EOF
chmod +x "$MOCK_DIR/kubectl"
export PATH="$MOCK_DIR:$PATH"

# ── Test helpers ──────────────────────────────────────────────────────────────
FAILURES=0
PASSES=0

pass() { echo "PASS: $1"; PASSES=$(( PASSES + 1 )); }
fail() { echo "FAIL: $1"; FAILURES=$(( FAILURES + 1 )); }

# run_ok NAME [args…]  — expect exit 0
run_ok() {
  local name="$1"; shift
  local output exit_code
  output=$(bash "$CANARY_SCRIPT" "$@" 2>&1)
  exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    pass "$name"
  else
    fail "$name (exit $exit_code)"
    echo "$output"
  fi
}

# run_fail NAME [args…]  — expect non-zero exit
run_fail() {
  local name="$1"; shift
  local exit_code=0
  bash "$CANARY_SCRIPT" "$@" >/dev/null 2>&1 || exit_code=$?
  if [[ $exit_code -ne 0 ]]; then
    pass "$name"
  else
    fail "$name (expected non-zero exit, got 0)"
  fi
}

# assert_contains NAME output needle
assert_contains() {
  local name="$1" output="$2" needle="$3"
  if echo "$output" | grep -qF "$needle"; then
    pass "$name"
  else
    fail "$name (expected to find '$needle' in output)"
    echo "  Output: $output"
  fi
}

# ── Tests ─────────────────────────────────────────────────────────────────────

# start: happy path
run_ok "start --dry-run" \
  start --image ghcr.io/test/img:1.0 --canary-replicas 1 --stable-replicas 9 --dry-run

# start: --image required
run_fail "start requires --image" \
  start --dry-run

# promote: happy path — both deployments must appear in scaled output
promote_out=$(bash "$CANARY_SCRIPT" promote \
  --canary-replicas 5 --stable-replicas 5 --dry-run 2>&1)
assert_contains "promote references stable deployment" "$promote_out" "claim-agent"
assert_contains "promote references canary deployment" "$promote_out" "claim-agent-canary"
run_ok "promote --dry-run" \
  promote --canary-replicas 5 --stable-replicas 5 --dry-run

# finish: happy path (pass --final-replicas to avoid a live kubectl read)
run_ok "finish --dry-run" \
  finish --final-replicas 3 --dry-run

# rollback: happy path
run_ok "rollback --dry-run" \
  rollback --stable-replicas 9 --dry-run

# unknown subcommand should fail
run_fail "unknown subcommand exits non-zero" \
  foobar --dry-run

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASSES passed, $FAILURES failed."
if [[ $FAILURES -gt 0 ]]; then
  exit 1
fi
