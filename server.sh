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

    cd "$SCRIPT_DIR"
    nohup "$VENV_PYTHON" main.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Server started (PID $!), logging to $LOG_FILE"
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

case "${1:-restart}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        sleep 1
        start
        ;;
    status)
        status
        ;;
    logs)
        tail -f "$LOG_FILE"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
