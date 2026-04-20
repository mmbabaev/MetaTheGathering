#!/bin/bash
# server.sh — start/stop/restart the MetaGatherer bot

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.server.pid"
LOG_FILE="$SCRIPT_DIR/server.log"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python3"

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            rm "$PID_FILE"
            echo "Stopped server (PID $PID)"
        else
            echo "Stale PID file ($PID not running), cleaning up"
            rm "$PID_FILE"
        fi
    else
        echo "Server is not running"
    fi
}

start() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Server already running (PID $PID)"
            return 1
        fi
        rm "$PID_FILE"
    fi

    local env_file="$SCRIPT_DIR/.env.debug"
    if [ ! -f "$env_file" ]; then
        echo "ERROR: .env.debug not found. Create it with a debug bot token to avoid conflicting with prod."
        echo "  Example: cp .env .env.debug  # then replace TELEGRAM_BOT_TOKEN with a test token"
        return 1
    fi

    cd "$SCRIPT_DIR"
    set -a; source "$env_file"; set +a
    BOT_ENV=debug nohup "$VENV_PYTHON" main.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Server started in DEBUG mode (PID $!), logging to $LOG_FILE"
}

status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Server is RUNNING (PID $PID)"
        else
            echo "Server is NOT RUNNING (stale PID $PID)"
        fi
    else
        echo "Server is NOT RUNNING"
    fi
    echo ""
    echo "--- Last 20 log lines ---"
    tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log file yet)"
}

# ── Remote (server via SSH) ───────────────────────────────────────────────────
SSH_KEY="${SSH_KEY:-~/.ssh/ssh-key-kara}"
SERVER_USER="${SERVER_USER:-mbabaev}"
SERVER_IP="${SERVER_IP:-158.160.9.28}"

remote_cmd() {
    local env="${2:-prod}"
    local service="meta-the-gathering"
    [ "$env" = "debug" ] && service="meta-the-gathering-debug"
    ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" "$1 $service"
}

case "${1:-restart}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    logs)    tail -f "$LOG_FILE" ;;

    remote-restart) remote_cmd "sudo systemctl restart" "${2:-prod}" ;;
    remote-stop)    remote_cmd "sudo systemctl stop"    "${2:-prod}" ;;
    remote-status)  remote_cmd "sudo systemctl status --no-pager -l" "${2:-prod}" ;;
    remote-logs)
        env="${2:-prod}"
        service="meta-the-gathering"; [ "$env" = "debug" ] && service="meta-the-gathering-debug"
        ssh -i "${SSH_KEY/#\~/$HOME}" -o StrictHostKeyChecking=no "${SERVER_USER}@${SERVER_IP}" \
            "sudo journalctl -u $service -f"
        ;;

    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        echo "       $0 {remote-restart|remote-stop|remote-status|remote-logs} [prod|debug]"
        exit 1
        ;;
esac
