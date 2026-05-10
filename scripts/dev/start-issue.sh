#!/usr/bin/env bash
# Usage: scripts/dev/start-issue.sh [issue-number]
# Reads latest (or specified) open issue, pulls main, creates branch fix/<slug>.
set -e

if [ -n "$1" ]; then
  ISSUE_NUMBER="$1"
else
  ISSUE_NUMBER=$(gh issue list --state open --limit 1 --json number --jq '.[0].number')
fi

echo "=== Issue #${ISSUE_NUMBER} ==="
gh issue view "$ISSUE_NUMBER"

TITLE=$(gh issue view "$ISSUE_NUMBER" --json title --jq '.title')
SLUG=$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-zа-яё0-9]/-/g' | sed 's/-\+/-/g' | sed 's/^-\|-$//g' | cut -c1-40)
BRANCH="fix/${SLUG}-${ISSUE_NUMBER}"

echo ""
echo "=== Переключаюсь на main и создаю ветку: ${BRANCH} ==="
git checkout main
git pull
git checkout -b "$BRANCH"

echo ""
echo "Ветка готова: ${BRANCH}"
