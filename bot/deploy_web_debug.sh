#!/bin/bash
# deploy_web_debug.sh — Deploy MetaGatherer Web UI to server (prod or debug)
# Usage:
#   bash deploy_web_debug.sh           → DEBUG deploy (port 8081)
#   bash deploy_web_debug.sh --release → PROD deploy  (port 8080)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[web-deploy]${NC} $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

SSH_KEY="${SSH_KEY:-~/.ssh/ssh-key-kara}"
SERVER_USER="mbabaev"
SERVER_IP="158.160.9.28"

MODE="debug"
if [ "$1" = "--release" ]; then
    MODE="release"
fi

if [ "$MODE" = "release" ]; then
    REMOTE_DIR="/home/mbabaev/MetaTheGathering/meta_the_gathering"
    ENV_DEST="$REMOTE_DIR/bot/.env"
    SERVICE_NAME="meta-the-gathering-web"
    info "Mode: \033[1mPRODUCTION\033[0m"
else
    REMOTE_DIR="/home/mbabaev/MetaTheGathering/meta_the_gatheringDebug"
    ENV_DEST="$REMOTE_DIR/bot/.env.debug"
    SERVICE_NAME="meta-the-gathering-debug-web"
    info "Mode: \033[1mDEBUG\033[0m"
fi

[ ! -f "${SSH_KEY/#\~/$HOME}" ] && error "SSH-ключ $SSH_KEY не найден"

ARCHIVE="/tmp/meta-web-deploy-$(date +%Y%m%d%H%M%S).tar.gz"
info "Создаём архив: $ARCHIVE"

COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env*' \
    --exclude='.pytest_cache' \
    --exclude='tests/' \
    --exclude='venv/' \
    --exclude='.git/' \
    --exclude='output/' \
    --exclude='._*' \
    -C "$REPO_ROOT" .

info "Архив создан: $(du -sh $ARCHIVE | cut -f1)"

ARCHIVE_NAME="$(basename "$ARCHIVE")"
SYSTEMD_SERVICE_FILE="$REMOTE_DIR/bot/systemd/$SERVICE_NAME.service"

info "Копируем на сервер..."
scp -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no \
    "$ARCHIVE" "${SERVER_USER}@${SERVER_IP}:/tmp/"

ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
    ARCHIVE_NAME="$ARCHIVE_NAME" REMOTE_DIR="$REMOTE_DIR" SERVICE_NAME="$SERVICE_NAME" \
    ENV_DEST="$ENV_DEST" SYSTEMD_SERVICE_FILE="$SYSTEMD_SERVICE_FILE" \
    'bash -s' <<'REMOTE'
set -e

echo "→ Разворачиваем в $REMOTE_DIR"
mkdir -p "$REMOTE_DIR"

# Protect env file from being overwritten by tar extraction
[ -f "$ENV_DEST" ] && cp "$ENV_DEST" /tmp/.env.protected

tar -xzf "/tmp/$ARCHIVE_NAME" -C "$REMOTE_DIR"

# Restore env file if it was protected
if [ -f /tmp/.env.protected ]; then
    mv /tmp/.env.protected "$ENV_DEST"
else
    echo "ERROR: $ENV_DEST не найден на сервере. Загрузите его вручную."
    exit 1
fi

echo "→ Создаём venv..."
cd "$REMOTE_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

echo "→ Проверяем миграции..."
cp "$ENV_DEST" .env
HEAD_COUNT=$(./venv/bin/alembic heads 2>/dev/null | grep -c "(head)" || true)
if [ "$HEAD_COUNT" -ne 1 ]; then
    echo "ERROR: Multiple alembic heads ($HEAD_COUNT). Merge conflict in migrations — deploy aborted."
    ./venv/bin/alembic heads
    rm -f .env
    exit 1
fi
echo "→ Запускаем миграции..."
./venv/bin/alembic upgrade head
rm -f .env

sudo cp "$SYSTEMD_SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

rm -f "/tmp/$ARCHIVE_NAME"
echo "→ Сервис $SERVICE_NAME запущен"
REMOTE

info "Статус сервиса:"
ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
    "sudo systemctl status $SERVICE_NAME --no-pager -l | head -20"

rm -f "$ARCHIVE"
info "Web deploy завершён!"
