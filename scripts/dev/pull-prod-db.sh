#!/bin/bash
# pull-prod-db.sh — Скопировать прод БД на локальную debug БД.
#
# Что делает:
#   1. pg_dump на сервере (meta_the_gathering_prod)
#   2. Стримит дамп по SSH на локальную машину
#   3. Восстанавливает в meta_the_gathering_debug
#
# Использование:
#   bash scripts/dev/pull-prod-db.sh

set -euo pipefail

REMOTE_HOST="158.160.9.28"
REMOTE_USER="mbabaev"
REMOTE_SSH_KEY="${SSH_KEY:-$HOME/.ssh/ssh-key-kara}"

REMOTE_DB="meta_the_gathering_prod"
REMOTE_DB_USER="mbabaev"
REMOTE_DB_PASS="${REMOTE_DB_PASS:?Set REMOTE_DB_PASS in the environment}"

LOCAL_DB="meta_the_gathering_debug"
LOCAL_DB_USER="mbabaev"
LOCAL_DB_PASS="${LOCAL_DB_PASS:?Set LOCAL_DB_PASS in the environment}"

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[pull-prod-db]${NC} $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# Проверяем SSH ключ
[ ! -f "$REMOTE_SSH_KEY" ] && error "SSH ключ не найден: $REMOTE_SSH_KEY"

info "Подключаемся к $REMOTE_HOST и делаем дамп $REMOTE_DB..."

# Дамп на сервере → стрим → восстановление локально
# PGPASSWORD на сервере передаём через ssh env
ssh -i "$REMOTE_SSH_KEY" "$REMOTE_USER@$REMOTE_HOST" \
    "PGPASSWORD=$REMOTE_DB_PASS pg_dump -U $REMOTE_DB_USER -Fc $REMOTE_DB" \
  | PGPASSWORD="$LOCAL_DB_PASS" pg_restore \
      -U "$LOCAL_DB_USER" \
      --clean \
      --if-exists \
      --no-owner \
      --no-privileges \
      -d "$LOCAL_DB" 2>&1 | grep -v "^pg_restore: warning" || true

info "Готово. Локальная БД '$LOCAL_DB' обновлена."
