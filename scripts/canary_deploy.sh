#!/usr/bin/env bash
# canary_deploy.sh — progressive canary rollout for claim-agent on Kubernetes.
#
# Strategy (plain Kubernetes, no service mesh required):
#   - A stable Deployment (claim-agent) handles the majority of traffic.
#   - A canary Deployment (claim-agent-canary) runs the new image on a small
#     number of replicas that share the same Service selector, so the canary
#     receives proportional traffic based on replica count.
#   - Traffic weight ≈ canary_replicas / (stable_replicas + canary_replicas).
#
# Usage:
#   # Start a canary at 10 % (1 canary / 9 stable = ~10 %)
#   scripts/canary_deploy.sh start --image ghcr.io/csmangum/auto-agent:1.2.0 \
#       --canary-replicas 1 --stable-replicas 9
#
#   # Promote to 50 %
#   scripts/canary_deploy.sh promote --canary-replicas 5 --stable-replicas 5
#
#   # Fully promote (retire stable, scale canary to full capacity)
#   scripts/canary_deploy.sh finish --final-replicas 2
#
#   # Roll back (delete canary, restore stable replicas)
#   scripts/canary_deploy.sh rollback --stable-replicas 2
#
# Prerequisites:
#   - kubectl is installed and configured.
#   - k8s/blue-green/deployment-canary.yaml has been applied at least once.
#   - The claim-agent Service (k8s/service.yaml) selects on
#     app.kubernetes.io/name=claim-agent without a track label so it picks
#     up pods from both the stable and canary deployments.
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
NAMESPACE="claim-agent"
STABLE_DEPLOY="claim-agent"
CANARY_DEPLOY="claim-agent-canary"
CANARY_IMAGE=""
CANARY_REPLICAS=1
STABLE_REPLICAS=9
FINAL_REPLICAS=2
DRY_RUN=false
WAIT_TIMEOUT=120

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
fail() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: $*" >&2; exit "${2:-1}"; }

run_kubectl() {
  if $DRY_RUN; then
    log "[DRY-RUN] kubectl $*"
  else
    kubectl "$@"
  fi
}

wait_for_deployment() {
  local deploy="$1"
  log "Waiting up to ${WAIT_TIMEOUT}s for deployment/$deploy …"
  if ! kubectl rollout status deployment/"$deploy" \
        -n "$NAMESPACE" --timeout="${WAIT_TIMEOUT}s"; then
    fail "deployment/$deploy did not become ready in time." 2
  fi
}

usage() {
  sed -n '2,35p' "$0" | grep '^#' | sed 's/^# \?//'
  exit 0
}

# ── Parse subcommand and flags ─────────────────────────────────────────────────
[[ $# -eq 0 ]] && usage

SUBCOMMAND="$1"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image)            CANARY_IMAGE="$2";         shift 2 ;;
    --canary-replicas)  CANARY_REPLICAS="$2";       shift 2 ;;
    --stable-replicas)  STABLE_REPLICAS="$2";       shift 2 ;;
    --final-replicas)   FINAL_REPLICAS="$2";        shift 2 ;;
    --namespace|-n)     NAMESPACE="$2";             shift 2 ;;
    --timeout)          WAIT_TIMEOUT="$2";          shift 2 ;;
    --dry-run)          DRY_RUN=true;               shift   ;;
    --help|-h)          usage ;;
    *) fail "Unknown argument: $1" 1 ;;
  esac
done

log "Namespace : $NAMESPACE"
log "Dry-run   : $DRY_RUN"

case "$SUBCOMMAND" in

  # ── start: deploy a new canary image alongside stable ─────────────────────
  start)
    [[ -z "$CANARY_IMAGE" ]] && fail "--image is required for 'start'" 1

    CANARY_WEIGHT_PCT=$(( CANARY_REPLICAS * 100 / (CANARY_REPLICAS + STABLE_REPLICAS) ))
    log "Starting canary: image=$CANARY_IMAGE"
    log "Stable replicas : $STABLE_REPLICAS | Canary replicas: $CANARY_REPLICAS (~${CANARY_WEIGHT_PCT}% traffic)"

    # Scale stable down if needed
    run_kubectl scale deployment "$STABLE_DEPLOY" -n "$NAMESPACE" \
      --replicas="$STABLE_REPLICAS"

    # Apply the canary deployment image and replica count
    run_kubectl set image deployment/"$CANARY_DEPLOY" \
      claim-agent="$CANARY_IMAGE" -n "$NAMESPACE"
    run_kubectl scale deployment "$CANARY_DEPLOY" -n "$NAMESPACE" \
      --replicas="$CANARY_REPLICAS"

    if ! $DRY_RUN; then
      wait_for_deployment "$CANARY_DEPLOY"
      READY=$(kubectl get deployment "$CANARY_DEPLOY" -n "$NAMESPACE" \
                -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
      log "✓ Canary ready: $READY/$CANARY_REPLICAS replicas"
    fi

    log "Monitor error rates and latency before promoting."
    log "  Promote : $0 promote --canary-replicas <n> --stable-replicas <n>"
    log "  Roll back: $0 rollback --stable-replicas $STABLE_REPLICAS"
    ;;

  # ── promote: adjust canary/stable ratio ───────────────────────────────────
  promote)
    CANARY_WEIGHT_PCT=$(( CANARY_REPLICAS * 100 / (CANARY_REPLICAS + STABLE_REPLICAS) ))
    log "Promoting canary to ~${CANARY_WEIGHT_PCT}% traffic"
    log "Stable replicas: $STABLE_REPLICAS | Canary replicas: $CANARY_REPLICAS"

    run_kubectl scale deployment "$STABLE_DEPLOY" -n "$NAMESPACE" \
      --replicas="$STABLE_REPLICAS"
    run_kubectl scale deployment "$CANARY_DEPLOY" -n "$NAMESPACE" \
      --replicas="$CANARY_REPLICAS"

    if ! $DRY_RUN; then
      wait_for_deployment "$CANARY_DEPLOY"
      log "✓ Canary at ~${CANARY_WEIGHT_PCT}% traffic"
    fi
    ;;

  # ── finish: promote canary to stable, retire the old stable ───────────────
  finish)
    log "Finishing canary rollout → promoting to stable"

    # Copy canary image to the stable deployment
    if ! $DRY_RUN; then
      CANARY_IMG=$(kubectl get deployment "$CANARY_DEPLOY" -n "$NAMESPACE" \
                     -o jsonpath='{.spec.template.spec.containers[0].image}')
      log "Canary image: $CANARY_IMG"
      run_kubectl set image deployment/"$STABLE_DEPLOY" \
        claim-agent="$CANARY_IMG" -n "$NAMESPACE"
    fi

    run_kubectl scale deployment "$STABLE_DEPLOY" -n "$NAMESPACE" \
      --replicas="$FINAL_REPLICAS"
    run_kubectl scale deployment "$CANARY_DEPLOY" -n "$NAMESPACE" \
      --replicas=0

    if ! $DRY_RUN; then
      wait_for_deployment "$STABLE_DEPLOY"
      log "✓ Canary promoted. Stable deployment now runs the new image."
    fi

    log "Remove the canary deployment when no longer needed:"
    log "  kubectl delete deployment $CANARY_DEPLOY -n $NAMESPACE"
    ;;

  # ── rollback: delete canary, restore stable ───────────────────────────────
  rollback)
    log "Rolling back: scaling canary to 0, restoring stable to $STABLE_REPLICAS replicas"

    run_kubectl scale deployment "$CANARY_DEPLOY" -n "$NAMESPACE" --replicas=0
    run_kubectl scale deployment "$STABLE_DEPLOY" -n "$NAMESPACE" \
      --replicas="$STABLE_REPLICAS"

    if ! $DRY_RUN; then
      wait_for_deployment "$STABLE_DEPLOY"
      log "✓ Rollback complete. Canary is at 0 replicas; stable is at $STABLE_REPLICAS."
    fi
    ;;

  *)
    fail "Unknown subcommand: $SUBCOMMAND. Use start|promote|finish|rollback." 1
    ;;
esac
