#!/usr/bin/env bash
# Usage: scripts/dev/check-ci.sh <pr-number> [wait-seconds]
# Waits N seconds then prints CI check results — one approval.
set -e

PR="$1"
WAIT="${2:-90}"

if [ -z "$PR" ]; then
  echo "Usage: $0 <pr-number> [wait-seconds]"
  exit 1
fi

echo "Waiting ${WAIT}s before checking CI for PR #${PR}..."
sleep "$WAIT"
gh pr checks "$PR"
