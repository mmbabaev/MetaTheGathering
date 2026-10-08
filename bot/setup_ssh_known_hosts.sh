#!/usr/bin/env bash
# Resolve the deployment host before any deploy script starts.
#
# GitHub Actions runners occasionally lose the route to the VM. A bounded,
# retried keyscan makes that failure explicit instead of leaving a deploy job
# hanging or failing with an opaque later SSH error.

set -Eeuo pipefail

SERVER_HOST="${SERVER_HOST:-}"
if [[ -z "$SERVER_HOST" ]]; then
    echo "[ssh-preflight] SERVER_HOST is empty" >&2
    exit 1
fi

if [[ "$SERVER_HOST" == *"://"* || "$SERVER_HOST" == */* || "$SERVER_HOST" == *[[:space:]]* ]]; then
    echo "[ssh-preflight] SERVER_HOST must be a bare hostname or IP address" >&2
    exit 1
fi

known_hosts_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
mkdir -p "$known_hosts_dir"
known_hosts_file="$known_hosts_dir/metagatherer-known-hosts"

for attempt in 1 2 3; do
    if ssh-keyscan -T 5 -H "$SERVER_HOST" >"$known_hosts_file" 2>/dev/null && [[ -s "$known_hosts_file" ]]; then
        cat "$known_hosts_file" >>"$HOME/.ssh/known_hosts"
        rm -f -- "$known_hosts_file"
        echo "[ssh-preflight] SSH host is reachable"
        exit 0
    fi

    if [[ "$attempt" -lt 3 ]]; then
        echo "[ssh-preflight] SSH host check failed; retrying ($attempt/3)" >&2
        sleep 5
    fi
done

rm -f -- "$known_hosts_file"
echo "[ssh-preflight] SSH host is unreachable or SERVER_HOST is invalid" >&2
echo "[ssh-preflight] Check the VM, TCP port 22, firewall rules and the SERVER_HOST secret" >&2
exit 1
