#!/usr/bin/env bash
# Usage: scripts/dev/create-pr.sh <branch> <commit-msg> <pr-title> <pr-body>
# Creates branch, commits all staged files, pushes, opens PR — one approval.
set -e

BRANCH="$1"
COMMIT_MSG="$2"
PR_TITLE="$3"
PR_BODY="$4"

if [ -z "$BRANCH" ] || [ -z "$COMMIT_MSG" ] || [ -z "$PR_TITLE" ]; then
  echo "Usage: $0 <branch> <commit-msg> <pr-title> [pr-body]"
  exit 1
fi

git checkout -b "$BRANCH"
git commit -m "$COMMIT_MSG"
git push -u origin "$BRANCH"
gh pr create --title "$PR_TITLE" --body "${PR_BODY:-}"
