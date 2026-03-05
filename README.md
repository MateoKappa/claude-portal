# Claude Portal

Access Claude Code from any device — your phone, tablet, another laptop — through a web-based chat interface.

Claude Portal is a lightweight server that bridges a web UI to the Claude Code CLI. It runs on your machine (or a VPS), connects through a Cloudflare Tunnel, and gives you a polished chat experience with markdown rendering, syntax highlighting, file downloads, and role-based access control.

![Dark themed chat interface](https://img.shields.io/badge/theme-dark-000?style=flat-square) ![Python](https://img.shields.io/badge/python-3.11+-blue?style=flat-square) ![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

## Features

- **Chat with Claude Code** from any browser — mobile, desktop, anywhere
- **Streaming responses** — see Claude's output token by token in real-time
- **Markdown rendering** with syntax-highlighted code blocks and copy buttons
- **Tool use visibility** — see when Claude runs commands, edits files, etc. (collapsible)
- **File sharing** — Claude creates files you can download directly from the portal
- **Session continuity** — conversations persist across messages using `--resume`
- **Role-based access**:
  - **Admin** — full access to Claude Code with all capabilities
  - **Limited** — sandboxed to a shared files directory, no access to host filesystem
- **Security** — token auth, brute force protection, Cloudflare Tunnel (no open ports)
- **Responsive UI** — works great on phones, tablets, and desktops

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and logged in
- Python 3.11+
- (Optional) [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) for remote access

## Quick Start

```bash
# Clone
git clone https://github.com/mateokappa/claude-portal.git
cd claude-portal

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your tokens (use long random strings!)

# Run
./start.sh
```

Open `http://localhost:8080` and enter your token.

### Generate secure tokens

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Remote Access (Cloudflare Tunnel)

To access the portal from any device over the internet:

```bash
# Install cloudflared
brew install cloudflared  # macOS
# or: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create claude-portal
cloudflared tunnel route dns claude-portal portal.yourdomain.com

# Add to ~/.cloudflared/config.yml:
# tunnel: <your-tunnel-id>
# credentials-file: ~/.cloudflared/<your-tunnel-id>.json
# ingress:
#   - hostname: portal.yourdomain.com
#     service: http://localhost:8080
#   - service: http_status:404

# Add to your .env:
# TUNNEL_NAME=claude-portal
# TUNNEL_URL=https://portal.yourdomain.com
```

The start script will automatically launch the tunnel alongside the server.

## Configuration

All config lives in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `ADMIN_TOKEN` | Yes | Token for full access |
| `LIMITED_TOKEN` | Yes | Token for sandboxed access |
| `PORT` | No | Server port (default: 8080) |
| `TUNNEL_NAME` | No | Cloudflare tunnel name |
| `TUNNEL_URL` | No | Your tunnel URL (for display only) |

## Access Roles

| | Admin | Limited |
|---|---|---|
| Chat with Claude | ✓ | ✓ |
| Create & download files | ✓ | ✓ |
| Read host filesystem | ✓ | ✗ |
| Run any shell command | ✓ | Sandboxed |
| Install packages | ✓ | ✓ (in sandbox) |
| Serve files (ngrok, etc.) | ✓ | ✓ |

## Security

- **Token authentication** with constant-time comparison
- **Brute force protection** — 5 failed attempts = 5 min lockout
- **Secure cookies** — httponly, samesite=strict, secure flag
- **Cloudflare Tunnel** — no open ports, encrypted traffic, IP hidden
- **Path traversal protection** on file serving endpoint
- **No default tokens** — app refuses to start without them

## Project Structure

```
claude-portal/
├── .env.example        # Template for configuration
├── .gitignore
├── requirements.txt    # Python dependencies
├── server.py           # FastAPI backend
├── start.sh            # One-command startup script
├── shared-files/       # Files Claude creates for download
└── static/
    └── index.html      # Chat UI
```

## License

MIT
