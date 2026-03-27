#!/usr/bin/env bash
# blue_green_switch.sh — switch live traffic between the blue and green deployment slots.
#
# Usage:
#   scripts/blue_green_switch.sh <blue|green> [--namespace <ns>] [--dry-run]
#
# Prerequisites:
#   - kubectl is installed and configured for the target cluster.
#   - The blue/green manifests in k8s/blue-green/ have already been applied.
#   - The target slot's deployment is healthy (all pods ready).
#
# What it does:
#   1. Verifies the target slot deployment is fully ready.
#   2. Patches the claim-agent-active Service selector to point at the new slot.
#   3. Updates the service annotation to record the active slot.
#   4. Optionally scales down the inactive slot to zero replicas (--scale-down-inactive).
#
# Exit codes:
#   0  success
#   1  usage / validation error
#   2  target deployment not healthy
#   3  kubectl command failed
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
NAMESPACE="claim-agent"
SERVICE_NAME="claim-agent-active"
DRY_RUN=false
SCALE_DOWN_INACTIVE=false
WAIT_TIMEOUT=120  # seconds to wait for the target slot to become ready

# ── Parse arguments ────────────────────────────────────────────────────────────
TARGET_SLOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    blue|green)
      TARGET_SLOT="$1"
      shift
      ;;
    --namespace|-n)
      NAMESPACE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --scale-down-inactive)
      SCALE_DOWN_INACTIVE=true
      shift
      ;;
    --timeout)
      WAIT_TIMEOUT="$2"
      shift 2
      ;;
    --help|-h)
      sed -n '2,30p' "$0" | grep '^#' | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      echo "Usage: $0 <blue|green> [--namespace <ns>] [--dry-run] [--scale-down-inactive]" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$TARGET_SLOT" ]]; then
  echo "ERROR: target slot is required (blue or green)." >&2
  echo "Usage: $0 <blue|green> [--namespace <ns>] [--dry-run]" >&2
  exit 1
fi

# ── Helper ─────────────────────────────────────────────────────────────────────
log()  { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
warn() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] WARN: $*" >&2; }
fail() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: $*" >&2; exit "${2:-1}"; }

run_kubectl() {
  if $DRY_RUN; then
    log "[DRY-RUN] kubectl $*"
  else
    kubectl "$@"
  fi
}

# ── Determine inactive slot ────────────────────────────────────────────────────
if [[ "$TARGET_SLOT" == "blue" ]]; then
  INACTIVE_SLOT="green"
else
  INACTIVE_SLOT="blue"
fi

TARGET_DEPLOY="claim-agent-${TARGET_SLOT}"
INACTIVE_DEPLOY="claim-agent-${INACTIVE_SLOT}"

log "Target slot   : $TARGET_SLOT  (deployment/$TARGET_DEPLOY)"
log "Inactive slot : $INACTIVE_SLOT (deployment/$INACTIVE_DEPLOY)"
log "Namespace     : $NAMESPACE"
log "Service       : $SERVICE_NAME"
log "Dry-run       : $DRY_RUN"

# ── Step 1: Verify the target deployment exists and is healthy ─────────────────
log "Waiting up to ${WAIT_TIMEOUT}s for deployment/$TARGET_DEPLOY to be ready …"
if ! kubectl rollout status deployment/"$TARGET_DEPLOY" \
      -n "$NAMESPACE" --timeout="${WAIT_TIMEOUT}s" 2>&1; then
  fail "Deployment $TARGET_DEPLOY is not ready. Aborting switch." 2
fi

DESIRED=$(kubectl get deployment "$TARGET_DEPLOY" -n "$NAMESPACE" \
            -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
READY=$(kubectl get deployment "$TARGET_DEPLOY" -n "$NAMESPACE" \
          -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")

log "deployment/$TARGET_DEPLOY: $READY/$DESIRED replicas ready."

if [[ "$READY" -lt "$DESIRED" || "$DESIRED" -eq 0 ]]; then
  fail "deployment/$TARGET_DEPLOY is not fully ready ($READY/$DESIRED). Aborting." 2
fi

# ── Step 2: Detect current active slot ────────────────────────────────────────
CURRENT_SLOT=$(kubectl get service "$SERVICE_NAME" -n "$NAMESPACE" \
                 -o jsonpath='{.spec.selector.deployment-slot}' 2>/dev/null || echo "unknown")
log "Current active slot: $CURRENT_SLOT"

if [[ "$CURRENT_SLOT" == "$TARGET_SLOT" ]]; then
  log "Service is already pointing at slot '$TARGET_SLOT'. Nothing to do."
  exit 0
fi

# ── Step 3: Switch service selector ───────────────────────────────────────────
log "Patching $SERVICE_NAME selector → deployment-slot=$TARGET_SLOT …"
run_kubectl patch service "$SERVICE_NAME" -n "$NAMESPACE" \
  --type=json \
      # ~1 encodes "/" in JSON Pointer (RFC 6901) — annotation key is deployment.claim-agent/active-slot
      -p "[
    {\"op\":\"replace\",\"path\":\"/spec/selector/deployment-slot\",\"value\":\"${TARGET_SLOT}\"},
    {\"op\":\"replace\",\"path\":\"/metadata/annotations/deployment.claim-agent~1active-slot\",\"value\":\"${TARGET_SLOT}\"}
  ]"

if ! $DRY_RUN; then
  # Confirm the patch took effect
  ACTIVE_NOW=$(kubectl get service "$SERVICE_NAME" -n "$NAMESPACE" \
                 -o jsonpath='{.spec.selector.deployment-slot}')
  if [[ "$ACTIVE_NOW" != "$TARGET_SLOT" ]]; then
    fail "Patch did not take effect — service selector is still '$ACTIVE_NOW'." 3
  fi
  log "✓ Service now routes to slot: $ACTIVE_NOW"
fi

# ── Step 4: Optionally scale down the inactive slot ───────────────────────────
if $SCALE_DOWN_INACTIVE; then
  log "Scaling down inactive deployment/$INACTIVE_DEPLOY to 0 replicas …"
  run_kubectl scale deployment "$INACTIVE_DEPLOY" -n "$NAMESPACE" --replicas=0
  log "✓ deployment/$INACTIVE_DEPLOY scaled to 0."
else
  log "Leaving deployment/$INACTIVE_DEPLOY running (use --scale-down-inactive to stop it)."
fi

log "✓ Blue/green switch complete. Active slot: $TARGET_SLOT"
