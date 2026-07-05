#!/bin/bash
set -e
cd "$(dirname "$0")"

# Activate venv if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# Load .env if it exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

PORT="${PORT:-8080}"

if [ -z "$ADMIN_TOKEN" ] || [ -z "$LIMITED_TOKEN" ]; then
    echo "  ERROR: Set ADMIN_TOKEN and LIMITED_TOKEN"
    echo ""
    echo "  Either create a .env file or run:"
    echo "    ADMIN_TOKEN=xxx LIMITED_TOKEN=yyy ./start.sh"
    echo ""
    exit 1
fi

cat << 'BANNER'

   ╭─────────────────────────────────╮
   │        Claude Portal            │
   ╰─────────────────────────────────╯

BANNER

echo "  Local:         http://localhost:$PORT"
[ -n "$TUNNEL_URL" ] && echo "  Tunnel:        $TUNNEL_URL"
echo ""

# Stop any previous instances
pkill -f "uvicorn server:app" 2>/dev/null || true
pkill -f "cloudflared tunnel run" 2>/dev/null || true
sleep 1

# Start server
uvicorn server:app --host 0.0.0.0 --port "$PORT" &
SERVER_PID=$!

# Start tunnel if configured
TUNNEL_PID=""
TUNNEL_NAME="${TUNNEL_NAME:-claude-portal}"
if cloudflared tunnel info "$TUNNEL_NAME" &>/dev/null; then
    cloudflared tunnel run "$TUNNEL_NAME" &
    TUNNEL_PID=$!
fi

echo "  Press Ctrl+C to stop"
echo ""

cleanup() {
    echo "Shutting down..."
    kill $SERVER_PID 2>/dev/null
    [ -n "$TUNNEL_PID" ] && kill $TUNNEL_PID 2>/dev/null
    wait 2>/dev/null
}
trap cleanup INT TERM

wait
