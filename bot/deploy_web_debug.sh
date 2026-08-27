#!/bin/bash
# deploy_web_debug.sh — Deploy MetaGatherer Web UI to server (prod or debug)
# Usage:
#   bash deploy_web_debug.sh           → DEBUG deploy (port 8081)
#   bash deploy_web_debug.sh --release → PROD deploy  (port 8080)

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
info()  { echo -e "${GREEN}[web-deploy]${NC} $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

SSH_KEY="${SSH_KEY:-~/.ssh/ssh-key-kara}"
SERVER_USER="mbabaev"
SERVER_IP="158.160.9.28"

MODE="debug"
if [ "${1:-}" = "--release" ]; then
    MODE="release"
fi

if [ "$MODE" = "release" ]; then
    REMOTE_DIR="/home/mbabaev/MetaTheGathering/meta_the_gathering"
    SERVICE_NAME="meta-the-gathering-web"
    info "Mode: \033[1mPRODUCTION\033[0m"
else
    REMOTE_DIR="/home/mbabaev/MetaTheGathering/meta_the_gatheringDebug"
    SERVICE_NAME="meta-the-gathering-debug-web"
    info "Mode: \033[1mDEBUG\033[0m"
fi

[ ! -f "${SSH_KEY/#\~/$HOME}" ] && error "SSH-ключ $SSH_KEY не найден"

DEPLOY_ID="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
ARCHIVE_NAME="meta-web-deploy-${DEPLOY_ID}.tar.gz"
ARCHIVE="/tmp/$ARCHIVE_NAME"
REMOTE_ARCHIVE="/tmp/$ARCHIVE_NAME"
REMOTE_LOCK="/tmp/meta-the-gathering-${MODE}-deploy.lock"
SSH_TARGET="${SERVER_USER}@${SERVER_IP}"

cleanup() {
    rm -f -- "$ARCHIVE"
    ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "$SSH_TARGET" \
        "rm -f -- '$REMOTE_ARCHIVE'" >/dev/null 2>&1 || true
}
trap cleanup EXIT

info "Создаём архив: $ARCHIVE"

COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env*' \
    --exclude='.pytest_cache' \
    --exclude='tests/' \
    --exclude='venv/' \
    --exclude='.venv/' \
    --exclude='.git/' \
    --exclude='.claude/' \
    --exclude='.ruff_cache/' \
    --exclude='.playwright_session' \
    --exclude='output/' \
    --exclude='playgrounds/' \
    --exclude='server.log' \
    --exclude='events.jsonl' \
    --exclude='._*' \
    -C "$REPO_ROOT" .

info "Архив создан: $(du -sh $ARCHIVE | cut -f1)"

ARCHIVE_BYTES=$(wc -c < "$ARCHIVE" | tr -d ' ')
MIN_FREE_BYTES=$((200 * 1024 * 1024))
REQUIRED_BYTES=$((ARCHIVE_BYTES + MIN_FREE_BYTES))
REMOTE_FREE_BYTES=$(ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "$SSH_TARGET" \
    "df -Pk /tmp | awk 'NR == 2 {print \$4 * 1024}'")
if ! [[ "$REMOTE_FREE_BYTES" =~ ^[0-9]+$ ]]; then
    error "Не удалось определить свободное место в /tmp на сервере"
fi
if [ "$REMOTE_FREE_BYTES" -lt "$REQUIRED_BYTES" ]; then
    error "Недостаточно места в /tmp: доступно $((REMOTE_FREE_BYTES / 1024 / 1024)) MiB, нужно не менее $((REQUIRED_BYTES / 1024 / 1024)) MiB"
fi

SYSTEMD_SERVICE_FILE="$REMOTE_DIR/bot/systemd/$SERVICE_NAME.service"

info "Копируем на сервер..."
scp -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no \
    "$ARCHIVE" "$SSH_TARGET:$REMOTE_ARCHIVE"

ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "$SSH_TARGET" \
    ARCHIVE_NAME="$ARCHIVE_NAME" REMOTE_DIR="$REMOTE_DIR" SERVICE_NAME="$SERVICE_NAME" \
    SYSTEMD_SERVICE_FILE="$SYSTEMD_SERVICE_FILE" \
    "flock -w 900 '$REMOTE_LOCK' bash -s" <<'REMOTE'
set -Eeuo pipefail

cleanup_remote() {
    rm -f -- "/tmp/$ARCHIVE_NAME"
}
trap cleanup_remote EXIT

echo "→ Разворачиваем в $REMOTE_DIR"
mkdir -p "$REMOTE_DIR"
tar -xzf "/tmp/$ARCHIVE_NAME" -C "$REMOTE_DIR" --warning=no-unknown-keyword --exclude='.env' --exclude='bot/.env' --exclude='bot/.env.*'

echo "→ Устанавливаем зависимости..."
cd "$REMOTE_DIR"
sudo apt-get install -y python3-venv -qq 2>/dev/null || true
# Пересоздаём venv, только если он отсутствует или повреждён — не сносим
# рабочий venv (его делит bot-деплой в той же папке).
if ! ./venv/bin/python -m pip --version >/dev/null 2>&1; then
    echo "  venv отсутствует или повреждён — пересоздаём"
    rm -rf venv 2>/dev/null || true
    python3 -m venv venv
fi
./venv/bin/python -m pip install --upgrade pip -q
./venv/bin/python -m pip install -r requirements.txt -q

sudo cp "$SYSTEMD_SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "→ Сервис $SERVICE_NAME запущен"
REMOTE

info "Статус сервиса:"
ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
    "sudo systemctl status $SERVICE_NAME --no-pager -l | head -20"

info "Web deploy завершён!"
