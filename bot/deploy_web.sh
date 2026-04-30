#!/bin/bash
exec "$(dirname "$0")/deploy_web_debug.sh" --release "$@"
