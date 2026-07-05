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

## Quick Start

You need two things installed before starting:
- **Python 3.11+** — [download here](https://www.python.org/downloads/)
- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code` ([docs](https://docs.anthropic.com/en/docs/claude-code)), then run `claude` once to log in

Then:

```bash
git clone https://github.com/mateokappa/claude-portal.git
cd claude-portal
./setup.sh
```

The setup script will:
1. Verify Python and Claude Code are installed
2. Create a virtual environment and install dependencies
3. Generate secure access tokens and save them to `.env`
4. Print your tokens — save them somewhere safe

When setup finishes, start the portal:

```bash
./start.sh
```

Open **http://localhost:8080** and enter your token.

> **Forgot your tokens?** They're stored in the `.env` file. Delete it and re-run `./setup.sh` to generate new ones.

## Remote Access (Cloudflare Tunnel)

To access the portal from anywhere over the internet, you can use a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/). This requires a free Cloudflare account and a domain managed by Cloudflare.

```bash
# 1. Install cloudflared
brew install cloudflared          # macOS
# See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ for Linux/Windows

# 2. Authenticate with Cloudflare
cloudflared tunnel login

# 3. Create a tunnel
cloudflared tunnel create claude-portal
cloudflared tunnel route dns claude-portal portal.yourdomain.com

# 4. Configure the tunnel — add to ~/.cloudflared/config.yml:
# tunnel: <your-tunnel-id>
# credentials-file: ~/.cloudflared/<your-tunnel-id>.json
# ingress:
#   - hostname: portal.yourdomain.com
#     service: http://localhost:8080
#   - service: http_status:404

# 5. Add to your .env:
# TUNNEL_NAME=claude-portal
# TUNNEL_URL=https://portal.yourdomain.com
```

Once configured, `./start.sh` will automatically launch the tunnel alongside the server.

## Configuration

All config lives in `.env` (created by `setup.sh`):

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
| Chat with Claude | Yes | Yes |
| Create & download files | Yes | Yes |
| Read host filesystem | Yes | No |
| Run any shell command | Yes | Sandboxed |
| Install packages | Yes | Yes (in sandbox) |
| Serve files (ngrok, etc.) | Yes | Yes |

## Troubleshooting

**`./setup.sh: Permission denied`**
Run `chmod +x setup.sh start.sh` and try again.

**`claude: command not found`**
Install Claude Code CLI with `npm install -g @anthropic-ai/claude-code`, then run `claude` once to complete login.

**Port already in use**
Either stop whatever is using port 8080, or change the `PORT` in your `.env` file.

**Login works but chat doesn't connect**
Make sure Claude Code CLI is logged in — run `claude` in your terminal to verify. The portal communicates with Claude via the CLI, so it must be authenticated.

**Cookies not working (localhost)**
The auth cookie has `secure=true`, which some browsers enforce even on localhost. Try using Chrome or Firefox, or access via `127.0.0.1:8080` instead.

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
├── setup.sh            # One-time setup (venv, deps, tokens)
├── start.sh            # Start the portal
├── server.py           # FastAPI backend
├── .env.example        # Template for configuration
├── requirements.txt    # Python dependencies
├── shared-files/       # Files Claude creates for download
└── static/
    └── index.html      # Chat UI
```

## License

MIT
