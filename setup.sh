#!/bin/bash
set -e
cd "$(dirname "$0")"

# ─── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}[ok]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[!]${NC}  $1"; }
fail() { echo -e "  ${RED}[x]${NC}  $1"; }
info() { echo -e "  ${DIM}$1${NC}"; }

cat << 'BANNER'

   ╭─────────────────────────────────╮
   │      Claude Portal Setup        │
   ╰─────────────────────────────────╯

BANNER

# ─── Check prerequisites ────────────────────────────────────────────────────

echo -e "${BOLD}Checking prerequisites...${NC}\n"

MISSING=0

# Python 3.11+
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
        ok "Python $PY_VERSION"
    else
        fail "Python $PY_VERSION found, but 3.11+ is required"
        info "Install from https://www.python.org/downloads/"
        MISSING=1
    fi
else
    fail "Python 3 not found"
    info "Install from https://www.python.org/downloads/"
    MISSING=1
fi

# Claude Code CLI
if command -v claude &>/dev/null; then
    ok "Claude Code CLI"
else
    fail "Claude Code CLI not found"
    info "Install: npm install -g @anthropic-ai/claude-code"
    info "Then run: claude"
    info "Docs: https://docs.anthropic.com/en/docs/claude-code"
    MISSING=1
fi

# cloudflared (optional)
if command -v cloudflared &>/dev/null; then
    ok "cloudflared (optional, for remote access)"
else
    info "cloudflared not found (optional, only needed for remote access)"
fi

echo ""

if [ "$MISSING" -eq 1 ]; then
    fail "Missing required dependencies. Install them and re-run this script."
    echo ""
    exit 1
fi

# ─── Create virtual environment ─────────────────────────────────────────────

echo -e "${BOLD}Setting up Python environment...${NC}\n"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    ok "Created virtual environment (.venv)"
else
    ok "Virtual environment already exists"
fi

source .venv/bin/activate
pip install -q -r requirements.txt
ok "Installed dependencies"
echo ""

# ─── Generate .env ───────────────────────────────────────────────────────────

if [ -f .env ]; then
    echo -e "${BOLD}Configuration${NC}\n"
    ok ".env already exists — skipping token generation"
    info "To regenerate, delete .env and re-run setup.sh"
    echo ""
else
    echo -e "${BOLD}Generating configuration...${NC}\n"

    ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    LIMITED_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

    cat > .env << EOF
ADMIN_TOKEN=$ADMIN_TOKEN
LIMITED_TOKEN=$LIMITED_TOKEN
PORT=8080

# Optional: Cloudflare Tunnel for remote access
# TUNNEL_NAME=claude-portal
# TUNNEL_URL=https://your-domain.com
EOF

    ok "Created .env with secure tokens"
    echo ""

    echo -e "${BOLD}Your access tokens${NC} ${DIM}(save these somewhere safe!)${NC}\n"
    echo -e "  ${GREEN}Admin token:${NC}   $ADMIN_TOKEN"
    echo -e "  ${BLUE}Limited token:${NC} $LIMITED_TOKEN"
    echo ""
    info "Admin  = full access to Claude Code"
    info "Limited = sandboxed, no host filesystem access"
    echo ""
fi

# ─── Make start.sh executable ────────────────────────────────────────────────

chmod +x start.sh

# ─── Done ────────────────────────────────────────────────────────────────────

echo ""
echo -e "   ${GREEN}${BOLD}Setup complete!${NC}"
echo ""
echo -e "   Start the portal:"
echo ""
echo -e "     ${BOLD}./start.sh${NC}"
echo ""
echo -e "   Then open ${BLUE}http://localhost:8080${NC} and enter your token."
echo ""
