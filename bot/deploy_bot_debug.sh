#!/bin/bash
# deploy_bot_debug.sh — Deploy Meta The Gathering to server (prod or debug)
# Usage:
#   bash deploy_bot_debug.sh           → DEBUG deploy
#   bash deploy_bot_debug.sh --release → PROD deploy

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${GREEN}[deploy]${NC} $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── Config ────────────────────────────────────────────────────────────────────
SSH_KEY="${SSH_KEY:-~/.ssh/ssh-key-kara}"
SERVER_USER="mbabaev"
SERVER_IP="158.160.9.28"

MODE="debug"
if [ "$1" = "--release" ]; then
    MODE="release"
fi

if [ "$MODE" = "release" ]; then
    ENV_FILE="${SCRIPT_DIR}/.env"
    REMOTE_DIR="/home/mbabaev/MetaTheGathering/meta_the_gathering"
    SERVICE_NAME="meta-the-gathering"
    BOT_ENV="prod"
    info "Mode: \033[1mPRODUCTION\033[0m"
else
    ENV_FILE="${SCRIPT_DIR}/.env.debug"
    REMOTE_DIR="/home/mbabaev/MetaTheGathering/meta_the_gatheringDebug"
    SERVICE_NAME="meta-the-gathering-debug"
    BOT_ENV="debug"
    info "Mode: \033[1mDEBUG\033[0m"
fi

# ── Validate ──────────────────────────────────────────────────────────────────
[ ! -f "$ENV_FILE" ] && error "Файл $ENV_FILE не найден"
[ ! -f "${SSH_KEY/#\~/$HOME}" ] && error "SSH-ключ $SSH_KEY не найден"

# ── Archive ───────────────────────────────────────────────────────────────────
ARCHIVE="/tmp/meta-the-gathering-deploy-$(date +%Y%m%d%H%M%S).tar.gz"
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

# ── Copy to server ────────────────────────────────────────────────────────────
info "Копируем на сервер..."
scp -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no \
    "$ARCHIVE" "${SERVER_USER}@${SERVER_IP}:/tmp/"
scp -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no \
    "$ENV_FILE" "${SERVER_USER}@${SERVER_IP}:/tmp/.env.deploy"

# ── Remote install ────────────────────────────────────────────────────────────
info "Устанавливаем на сервере..."
ARCHIVE_NAME="$(basename "$ARCHIVE")"

if [ "$MODE" = "release" ]; then
    ENV_DEST="$REMOTE_DIR/bot/.env"
    SYSTEMD_SERVICE_FILE="$REMOTE_DIR/bot/systemd/meta-the-gathering.service"
    OTEL_SERVICE_FILE="$REMOTE_DIR/bot/systemd/otel-collector.service"
    OTEL_SERVICE_NAME="otel-collector"
else
    ENV_DEST="$REMOTE_DIR/bot/.env.debug"
    SYSTEMD_SERVICE_FILE="$REMOTE_DIR/bot/systemd/meta-the-gathering-debug.service"
    SYSTEMD_WEB_SERVICE_FILE="$REMOTE_DIR/bot/systemd/meta-the-gathering-debug-web.service"
    OTEL_SERVICE_FILE="$REMOTE_DIR/bot/systemd/otel-collector-debug.service"
    OTEL_SERVICE_NAME="otel-collector-debug"
fi

ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
    ARCHIVE_NAME="$ARCHIVE_NAME" REMOTE_DIR="$REMOTE_DIR" SERVICE_NAME="$SERVICE_NAME" \
    ENV_DEST="$ENV_DEST" BOT_ENV="$BOT_ENV" SYSTEMD_SERVICE_FILE="$SYSTEMD_SERVICE_FILE" \
    SYSTEMD_WEB_SERVICE_FILE="${SYSTEMD_WEB_SERVICE_FILE:-}" \
    OTEL_SERVICE_FILE="$OTEL_SERVICE_FILE" OTEL_SERVICE_NAME="$OTEL_SERVICE_NAME" \
    'bash -s' <<'REMOTE'
set -e

echo "→ Разворачиваем в $REMOTE_DIR"
mkdir -p "$REMOTE_DIR"
tar -xzf "/tmp/$ARCHIVE_NAME" -C "$REMOTE_DIR" --warning=no-unknown-keyword
mv /tmp/.env.deploy "$ENV_DEST"

echo "→ Создаём venv..."
cd "$REMOTE_DIR"
sudo apt-get install -y python3-venv python3-pip -qq 2>/dev/null || true
if [ ! -f venv/bin/python ]; then
    rm -rf venv 2>/dev/null || true
    python3 -m venv --without-pip venv
    ./venv/bin/python -m ensurepip
fi
./venv/bin/python -m pip install -r requirements.txt -q

echo "→ Проверяем миграции..."
export BOT_ENV
HEAD_COUNT=$(./venv/bin/alembic heads 2>/dev/null | grep -c "(head)" || true)
if [ "$HEAD_COUNT" -ne 1 ]; then
    echo "ERROR: Multiple alembic heads ($HEAD_COUNT). Merge conflict in migrations — deploy aborted."
    ./venv/bin/alembic heads
    exit 1
fi
echo "→ Запускаем миграции..."
./venv/bin/alembic upgrade head

# Install OpenTelemetry Collector if missing
if [ ! -f /usr/local/bin/otelcol ]; then
    echo "Installing OpenTelemetry Collector..."
    OTEL_VERSION="0.114.0"
    OTEL_URL="https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTEL_VERSION}/otelcol_${OTEL_VERSION}_linux_amd64.tar.gz"
    curl -fsSL "$OTEL_URL" -o /tmp/otelcol.tar.gz
    tar -xzf /tmp/otelcol.tar.gz -C /tmp
    sudo mv /tmp/otelcol /usr/local/bin/otelcol
    sudo chmod +x /usr/local/bin/otelcol
    rm /tmp/otelcol.tar.gz
fi

sudo cp "$OTEL_SERVICE_FILE" /etc/systemd/system/
sudo cp "$SYSTEMD_SERVICE_FILE" /etc/systemd/system/
if [ -n "$SYSTEMD_WEB_SERVICE_FILE" ]; then
    sudo cp "$SYSTEMD_WEB_SERVICE_FILE" /etc/systemd/system/
fi
sudo systemctl daemon-reload
sudo systemctl enable "$OTEL_SERVICE_NAME"
sudo systemctl restart "$OTEL_SERVICE_NAME"
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
if [ -n "$SYSTEMD_WEB_SERVICE_FILE" ]; then
    WEB_SERVICE_NAME="$(basename "$SYSTEMD_WEB_SERVICE_FILE" .service)"
    sudo systemctl enable "$WEB_SERVICE_NAME"
    sudo systemctl restart "$WEB_SERVICE_NAME"
fi

rm -f "/tmp/$ARCHIVE_NAME"
echo "→ Сервис $SERVICE_NAME запущен"
REMOTE

# ── Status ────────────────────────────────────────────────────────────────────
info "Статус сервиса:"
ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
    "sudo systemctl status $SERVICE_NAME --no-pager -l | head -30"

info "Последние логи:"
ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
    "sudo journalctl -u $SERVICE_NAME -n 20 --no-pager"

rm -f "$ARCHIVE"
info "Deploy завершён!"

echo ""
echo "Полезные команды:"
echo "  ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'sudo journalctl -u $SERVICE_NAME -f'"
echo "  ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'sudo systemctl restart $SERVICE_NAME'"
echo "  ssh -i ${SSH_KEY} ${SERVER_USER}@${SERVER_IP} 'sudo systemctl stop $SERVICE_NAME'"
