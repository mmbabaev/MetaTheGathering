#!/bin/bash
# push-env.sh — Upload local env files to GitHub secrets.
# Run this locally whenever bot/.env or bot/.env.debug changes.
# Usage: bash scripts/push-env.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[push-env]${NC} $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

ENV_PROD="$REPO_ROOT/bot/.env"
ENV_DEBUG="$REPO_ROOT/bot/.env.debug"

[ ! -f "$ENV_PROD" ]  && error "$ENV_PROD не найден"
[ ! -f "$ENV_DEBUG" ] && error "$ENV_DEBUG не найден"
command -v gh >/dev/null || error "gh CLI не установлен (brew install gh)"

gh secret set ENV_FILE       --body "$(cat "$ENV_PROD")"
info "ENV_FILE обновлён"

gh secret set ENV_FILE_DEBUG --body "$(cat "$ENV_DEBUG")"
info "ENV_FILE_DEBUG обновлён"
