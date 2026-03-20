#!/usr/bin/env bash
# Oldest open GitHub issue in the current repo that does not have BACKLOG_LABEL (default: backlog).
# Requires: gh (authenticated), jq.
# Usage:
#   ./scripts/gh-oldest-open-issue-not-backlog.sh          # JSON object on stdout
#   ./scripts/gh-oldest-open-issue-not-backlog.sh --url    # issue URL only
#   BACKLOG_LABEL=triage ./scripts/gh-oldest-open-issue-not-backlog.sh
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL="${BACKLOG_LABEL:-backlog}"
want_url=false
if [[ "${1:-}" == "--url" ]]; then
  want_url=true
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: gh is not installed" >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is not installed" >&2
  exit 2
fi

raw="$(gh issue list --state open --limit 500 --json number,title,createdAt,url,labels)"
pick="$(echo "$raw" | jq --arg lbl "$LABEL" '[.[] | select([.labels[]?.name] | all(. != $lbl))] | sort_by(.createdAt) | .[0]')"

if [[ "$pick" == "null" ]]; then
  exit 1
fi

if $want_url; then
  echo "$pick" | jq -r .url
else
  echo "$pick" | jq .
fi
