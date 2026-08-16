#!/usr/bin/env bash
# Container entrypoint for the Render single-port deployment.
#
# Runs the Reflex backend (websocket + API, port 8000, loopback only) and
# Caddy (static frontend + reverse proxy, $PORT, the only port Render exposes)
# as sibling processes. If either one dies, the container exits non-zero so
# Render's health check / restart logic notices instead of silently serving a
# static shell with a dead backend.
set -euo pipefail

PORT="${PORT:-10000}"
export PORT

uv run --no-sync reflex run --backend-only --env prod --backend-host 127.0.0.1 --backend-port 8000 &
backend_pid=$!

caddy run --config /app/Caddyfile --adapter caddyfile &
caddy_pid=$!

# Exit as soon as either process exits, taking the other one down with it.
trap 'kill "$backend_pid" "$caddy_pid" 2>/dev/null' EXIT
wait -n "$backend_pid" "$caddy_pid"
exit_code=$?
exit "$exit_code"
