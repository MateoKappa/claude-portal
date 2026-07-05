"""
Claude Portal — Access Claude Code from any device.
A web-based chat interface that connects to Claude Code CLI via WebSocket.
"""

import asyncio
import base64
import fcntl
import json
import os
import pty
import secrets
import signal
import struct
import termios
import time
import uuid
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────────────────

load_dotenv(Path(__file__).parent / ".env")

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
LIMITED_TOKEN = os.environ.get("LIMITED_TOKEN")

if not ADMIN_TOKEN or not LIMITED_TOKEN:
    print("ERROR: ADMIN_TOKEN and LIMITED_TOKEN environment variables are required.")
    print("  Usage: ADMIN_TOKEN=xxx LIMITED_TOKEN=yyy ./start.sh")
    exit(1)

SHARED_FILES_DIR = Path(__file__).parent / "shared-files"
SHARED_FILES_DIR.mkdir(exist_ok=True)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300

# ─── App Setup ───────────────────────────────────────────────────────────────

app = FastAPI(title="Claude Portal", docs_url=None, redoc_url=None)

# Clean env for child processes: drop CLAUDECODE (so claude doesn't think it's
# nested) and strip portal secrets (auth tokens, tunnel credentials) so neither
# the chat subprocess nor PTY shells can read them (privilege-escalation guard).
_SECRET_ENV_KEYS = ("CLAUDECODE", "ADMIN_TOKEN", "LIMITED_TOKEN")
CLEAN_ENV = {
    k: v
    for k, v in os.environ.items()
    if k not in _SECRET_ENV_KEYS and not k.startswith("TUNNEL_")
}

# ─── State ───────────────────────────────────────────────────────────────────

sessions: dict[str, asyncio.subprocess.Process] = {}
conversation_ids: dict[str, str] = {}
valid_cookies: dict[str, str] = {}  # cookie_value -> role
login_attempts: dict[str, tuple[int, float]] = {}  # ip -> (fails, last_time)

# ─── Security Helpers ────────────────────────────────────────────────────────

for _name, _tok in [("ADMIN_TOKEN", ADMIN_TOKEN), ("LIMITED_TOKEN", LIMITED_TOKEN)]:
    if len(_tok) < 20:
        print(f"⚠ {_name} is only {len(_tok)} chars — use 20+ for security")


def get_client_ip(request: Request) -> str:
    return (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for", "").split(",")[0].strip())
        or (request.client.host if request.client else "unknown")
    )


def is_locked_out(ip: str) -> bool:
    if ip not in login_attempts:
        return False
    fails, last_time = login_attempts[ip]
    if fails >= MAX_LOGIN_ATTEMPTS:
        if time.time() - last_time < LOCKOUT_SECONDS:
            return True
        del login_attempts[ip]
    return False


def record_fail(ip: str):
    fails = login_attempts.get(ip, (0, 0))[0]
    login_attempts[ip] = (fails + 1, time.time())


def check_auth(cookie: str | None) -> str | None:
    if cookie is None:
        return None
    return valid_cookies.get(cookie)


# ─── Login Page ──────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Portal</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'DM Sans', -apple-system, sans-serif;
            background: #08080a; color: #e8e6f0;
            height: 100vh; display: flex; align-items: center; justify-content: center;
            -webkit-font-smoothing: antialiased;
        }
        body::before {
            content: ''; position: fixed; top: -40%; left: -20%;
            width: 80%; height: 80%;
            background: radial-gradient(ellipse, rgba(167,139,250,0.04) 0%, transparent 70%);
            pointer-events: none;
        }
        .login-box {
            background: #0c0c0f; border: 1px solid rgba(255,255,255,0.06);
            border-radius: 20px; padding: 44px 36px; width: 360px;
            position: relative; z-index: 1;
        }
        .logo {
            width: 40px; height: 40px; border-radius: 12px;
            background: linear-gradient(135deg, #a78bfa 0%, #818cf8 100%);
            display: flex; align-items: center; justify-content: center;
            font-weight: 600; font-size: 16px; color: #fff;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(167,139,250,0.25);
        }
        h1 { font-size: 22px; margin-bottom: 6px; font-weight: 600; letter-spacing: -0.02em; }
        .subtitle { font-size: 13px; color: #55526a; margin-bottom: 28px; }
        input {
            width: 100%; padding: 12px 16px; background: #1a1a22; border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px; color: #e8e6f0; font-size: 14px; margin-bottom: 14px;
            font-family: 'DM Sans', sans-serif; transition: border-color 0.2s, box-shadow 0.2s;
        }
        input:focus { outline: none; border-color: rgba(167,139,250,0.4); box-shadow: 0 0 0 3px rgba(167,139,250,0.12); }
        input::placeholder { color: #55526a; }
        button {
            width: 100%; padding: 12px; background: #a78bfa; color: #fff; border: none;
            border-radius: 12px; font-size: 14px; font-weight: 600; cursor: pointer;
            font-family: 'DM Sans', sans-serif; transition: all 0.2s;
        }
        button:hover { background: #8b5cf6; transform: translateY(-1px); }
        button:active { transform: scale(0.98); }
        .error { color: #f87171; font-size: 13px; margin-bottom: 12px; }
        @media (max-width: 400px) { .login-box { margin: 0 16px; padding: 32px 24px; } }
    </style>
</head>
<body>
    <div class="login-box">
        <div class="logo">C</div>
        <h1>Claude Portal</h1>
        <div class="subtitle">Enter your access token to continue</div>
        <div class="error" id="error"></div>
        <form method="POST" action="/login">
            <input type="password" name="token" placeholder="Access token" autofocus>
            <button type="submit">Continue</button>
        </form>
    </div>
</body>
</html>"""


# ─── Auth Routes ─────────────────────────────────────────────────────────────

@app.get("/login")
async def login_page():
    return HTMLResponse(LOGIN_HTML)


@app.post("/login")
async def login(request: Request):
    ip = get_client_ip(request)

    if is_locked_out(ip):
        remaining = int(LOCKOUT_SECONDS - (time.time() - login_attempts[ip][1]))
        return HTMLResponse(LOGIN_HTML.replace(
            '<div class="error" id="error"></div>',
            f'<div class="error" id="error">Too many attempts. Try again in {remaining}s</div>'
        ), status_code=429)

    form = await request.form()
    token = str(form.get("token", ""))

    role = None
    if secrets.compare_digest(token, ADMIN_TOKEN):
        role = "admin"
    elif secrets.compare_digest(token, LIMITED_TOKEN):
        role = "limited"

    if role is None:
        record_fail(ip)
        fails = login_attempts[ip][0]
        remaining = MAX_LOGIN_ATTEMPTS - fails
        msg = "Invalid token"
        if 0 < remaining <= 2:
            msg += f" ({remaining} attempts left)"
        return HTMLResponse(LOGIN_HTML.replace(
            '<div class="error" id="error"></div>',
            f'<div class="error" id="error">{msg}</div>'
        ), status_code=401)

    login_attempts.pop(ip, None)
    cookie_value = secrets.token_urlsafe(32)
    valid_cookies[cookie_value] = role
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "portal_auth", cookie_value,
        httponly=True, samesite="strict", secure=True, max_age=86400 * 7
    )
    return response


@app.get("/")
async def index(portal_auth: str | None = Cookie(default=None)):
    if not check_auth(portal_auth):
        return RedirectResponse("/login")
    return FileResponse(Path(__file__).parent / "static" / "index.html")


# ─── Claude CLI Integration ──────────────────────────────────────────────────

def build_claude_cmd(role: str) -> list[str]:
    shared_path = str(SHARED_FILES_DIR.resolve())

    home_path = str(Path.home())

    file_prompt = (
        f"When the user asks you to create a file (PDF, image, text, etc.) that they need to download, "
        f"save it to {shared_path}/ — files there are served at /files/<filename> and the user can "
        f"download them from the portal. After creating a file, tell the user the download link like: "
        f"[Download filename](/files/filename)"
    )

    smart_home_prompt = (
        f"\n\nSMART HOME — WiZ Light Control:\n"
        f"The user has a WiZ smart bulb. You can control it with {home_path}/wiz-light.sh\n"
        f"Commands:\n"
        f"  {home_path}/wiz-light.sh on              — turn light on\n"
        f"  {home_path}/wiz-light.sh off             — turn light off\n"
        f"  {home_path}/wiz-light.sh brightness N    — set brightness (0-255)\n"
        f"  {home_path}/wiz-light.sh color red       — named colors (red, green, blue, purple, orange, pink)\n"
        f"  {home_path}/wiz-light.sh color R G B     — custom RGB values\n"
        f"  {home_path}/wiz-light.sh warm            — warm white (2700K)\n"
        f"  {home_path}/wiz-light.sh cool            — cool white (6500K)\n"
        f"  {home_path}/wiz-light.sh status          — check current state\n"
        f"When the user says things like 'close the lights', 'turn off the light', 'lights off', etc. — run the off command.\n"
        f"When they say 'open the lights', 'turn on the light', 'lights on', etc. — run the on command.\n"
        f"Just run the command and confirm briefly. No need for long explanations."
    )

    if role == "admin":
        return [
            "claude", "-p",
            "--dangerously-skip-permissions",
            "--verbose", "--output-format", "stream-json",
            "--append-system-prompt", file_prompt + smart_home_prompt,
        ]

    # Limited role
    limited_prompt = (
        f"{file_prompt}\n\n"
        f"IMPORTANT RESTRICTIONS:\n"
        f"- Your working directory is {shared_path}/ — create ALL files there\n"
        f"- You can ONLY read/write/access files inside {shared_path}/\n"
        f"- You must NEVER read, list, or access any files outside {shared_path}/\n"
        f"- You must NEVER run destructive commands (rm -rf /, kill, shutdown, reboot, etc.)\n"
        f"- You must NEVER access environment variables, credentials, SSH keys, or private data\n"
        f"- You CAN run Bash commands for building/serving projects (npm, python, npx, pip, etc.)\n"
        f"- You CAN use npx, ngrok, cloudflared, python -m http.server to serve/share files\n"
        f"- You CAN install npm/pip packages needed for the user's project\n"
        f"- If the user asks to read files from the host system, politely refuse"
    )
    return [
        "claude", "-p",
        "--dangerously-skip-permissions",
        "--verbose", "--output-format", "stream-json",
        "--allowedTools",
            f"Write({shared_path}/*)",
            f"Edit({shared_path}/*)",
            f"Read({shared_path}/*)",
            f"Glob({shared_path}/*)",
            "Bash",
        "--append-system-prompt", limited_prompt + smart_home_prompt,
    ]


async def stream_claude(websocket: WebSocket, message: str, session_id: str, role: str):
    cmd = build_claude_cmd(role)

    if session_id in conversation_ids:
        cmd.extend(["--resume", conversation_ids[session_id]])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=CLEAN_ENV,
    )
    sessions[session_id] = proc

    proc.stdin.write(message.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    buffer = ""
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buffer += chunk.decode()
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                await handle_event(websocket, json.loads(line), session_id)
            except json.JSONDecodeError:
                pass

    if buffer.strip():
        try:
            await handle_event(websocket, json.loads(buffer.strip()), session_id)
        except json.JSONDecodeError:
            pass

    await proc.wait()

    stderr = await proc.stderr.read()
    if stderr:
        await websocket.send_json({"type": "error", "content": stderr.decode()})

    await websocket.send_json({"type": "done"})
    sessions.pop(session_id, None)


async def handle_event(websocket: WebSocket, event: dict, session_id: str):
    event_type = event.get("type")

    if event_type == "system":
        sid = event.get("session_id") or event.get("conversation_id")
        if sid:
            conversation_ids[session_id] = sid

    elif event_type == "assistant":
        message = event.get("message", {})
        if isinstance(message, dict):
            for block in message.get("content", []):
                if block.get("type") == "text":
                    await websocket.send_json({"type": "assistant", "content": block["text"]})
                elif block.get("type") == "tool_use":
                    await websocket.send_json({
                        "type": "tool_use",
                        "tool": block.get("name", "unknown"),
                        "input": json.dumps(block.get("input", {}), indent=2),
                    })

    elif event_type == "content_block_delta":
        delta = event.get("delta", {})
        if delta.get("type") == "text_delta":
            await websocket.send_json({"type": "text_delta", "content": delta["text"]})

    elif event_type == "result":
        sid = event.get("session_id")
        if sid:
            conversation_ids[session_id] = sid
        await websocket.send_json({
            "type": "result",
            "session_id": sid or "",
            "cost": event.get("cost_usd"),
            "duration": event.get("duration_ms"),
        })


# ─── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    role = check_auth(websocket.cookies.get("portal_auth"))
    if not role:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                await stream_claude(websocket, data["content"], session_id, role)
            elif data.get("type") == "stop":
                proc = sessions.get(session_id)
                if proc:
                    proc.terminate()
    except WebSocketDisconnect:
        proc = sessions.pop(session_id, None)
        if proc:
            proc.terminate()


# ─── File Serving ────────────────────────────────────────────────────────────

@app.get("/files/{filename:path}")
async def download_file(filename: str, portal_auth: str | None = Cookie(default=None)):
    if not check_auth(portal_auth):
        return RedirectResponse("/login")
    file_path = SHARED_FILES_DIR / filename
    if not file_path.resolve().is_relative_to(SHARED_FILES_DIR.resolve()):
        return HTMLResponse("Forbidden", status_code=403)
    if not file_path.is_file():
        return HTMLResponse("File not found", status_code=404)
    return FileResponse(file_path, filename=filename)


@app.get("/api/files")
async def list_files(portal_auth: str | None = Cookie(default=None)):
    if not check_auth(portal_auth):
        return {"error": "unauthorized"}
    files = []
    for f in sorted(SHARED_FILES_DIR.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "url": f"/files/{f.name}",
            })
    return {"files": files}


# ─── Interactive Terminal (PTY, admin only) ──────────────────────────────────

SCROLLBACK_CAP = 200_000
WRITE_BUF_CAP = 1_000_000  # max pending bytes queued toward a stalled PTY


class TerminalSession:
    def __init__(self, tid: str, name: str, pid: int, fd: int):
        self.id = tid
        self.name = name
        self.pid = pid
        self.fd = fd
        self.scrollback = bytearray()
        self.attached: WebSocket | None = None
        self.alive = True
        self.write_buf = bytearray()
        self.writer_registered = False

    def append_scrollback(self, data: bytes):
        self.scrollback.extend(data)
        if len(self.scrollback) > SCROLLBACK_CAP:
            del self.scrollback[: len(self.scrollback) - SCROLLBACK_CAP]


terminals: dict[str, TerminalSession] = {}
_terminal_counter = 0


async def _term_safe_send(ws: WebSocket, payload: dict):
    try:
        await ws.send_json(payload)
    except Exception:
        pass


def _term_schedule_send(sess: TerminalSession, payload: dict):
    ws = sess.attached
    if ws is not None:
        asyncio.ensure_future(_term_safe_send(ws, payload))


def _on_pty_readable(sess: TerminalSession):
    loop = asyncio.get_event_loop()
    try:
        data = os.read(sess.fd, 65536)
    except OSError:
        data = b""
    if not data:
        # EOF — shell exited
        try:
            loop.remove_reader(sess.fd)
        except Exception:
            pass
        sess.alive = False
        _term_remove_writer(sess)
        sess.write_buf.clear()
        try:
            os.waitpid(sess.pid, os.WNOHANG)
        except ChildProcessError:
            pass
        _term_schedule_send(sess, {"t": "exit"})
        return
    sess.append_scrollback(data)
    _term_schedule_send(sess, {"t": "o", "d": base64.b64encode(data).decode("ascii")})


def _term_remove_writer(sess: TerminalSession):
    if sess.writer_registered:
        try:
            asyncio.get_event_loop().remove_writer(sess.fd)
        except Exception:
            pass
        sess.writer_registered = False


def _term_flush_writes(sess: TerminalSession):
    """Drain sess.write_buf into the (non-blocking) PTY master without ever
    blocking the event loop. Handles partial writes; retries via add_writer."""
    while sess.write_buf and sess.alive:
        try:
            n = os.write(sess.fd, sess.write_buf)
        except BlockingIOError:
            break
        except OSError:
            sess.write_buf.clear()
            break
        if n <= 0:
            break
        del sess.write_buf[:n]
    if sess.write_buf and sess.alive:
        if not sess.writer_registered:
            try:
                asyncio.get_event_loop().add_writer(sess.fd, _term_flush_writes, sess)
                sess.writer_registered = True
            except Exception:
                sess.write_buf.clear()
    else:
        if not sess.alive:
            sess.write_buf.clear()
        _term_remove_writer(sess)


def _term_write(sess: TerminalSession, data: bytes):
    if not sess.alive or not data:
        return
    if len(sess.write_buf) + len(data) > WRITE_BUF_CAP:
        print(
            f"[terminal {sess.id}] write buffer full ({len(sess.write_buf)} bytes), "
            f"dropping {len(data)} bytes of input",
            flush=True,
        )
        return
    sess.write_buf.extend(data)
    _term_flush_writes(sess)


def _spawn_terminal() -> TerminalSession:
    global _terminal_counter
    _terminal_counter += 1
    name = f"Terminal {_terminal_counter}"
    tid = uuid.uuid4().hex

    shell = os.environ.get("SHELL", "/bin/zsh")
    pid, fd = pty.fork()
    if pid == 0:
        # Child — never let an exception leak back into the server event loop
        try:
            os.chdir(str(Path.home()))
            env = dict(CLEAN_ENV)
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            env.setdefault("LANG", "en_US.UTF-8")
            os.execvpe(shell, [shell, "-l"], env)
        except BaseException:
            pass
        os._exit(1)

    os.set_blocking(fd, False)
    sess = TerminalSession(tid, name, pid, fd)
    terminals[tid] = sess
    loop = asyncio.get_event_loop()
    loop.add_reader(fd, _on_pty_readable, sess)
    return sess


def _kill_terminal(sess: TerminalSession):
    loop = asyncio.get_event_loop()
    sess.alive = False
    _term_remove_writer(sess)
    sess.write_buf.clear()
    try:
        loop.remove_reader(sess.fd)
    except Exception:
        pass
    for sig in (signal.SIGHUP, signal.SIGKILL):
        try:
            os.kill(sess.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.close(sess.fd)
    except OSError:
        pass
    try:
        os.waitpid(sess.pid, os.WNOHANG)
    except ChildProcessError:
        pass
    sess.alive = False
    terminals.pop(sess.id, None)


@app.post("/api/terminals")
async def create_terminal(portal_auth: str | None = Cookie(default=None)):
    if check_auth(portal_auth) != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    sess = _spawn_terminal()
    return {"id": sess.id, "name": sess.name}


@app.get("/api/terminals")
async def list_terminals(portal_auth: str | None = Cookie(default=None)):
    if check_auth(portal_auth) != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return {
        "terminals": [
            {
                "id": s.id,
                "name": s.name,
                "attached": s.attached is not None,
                "alive": s.alive,
            }
            for s in terminals.values()
        ]
    }


@app.delete("/api/terminals/{tid}")
async def delete_terminal(tid: str, portal_auth: str | None = Cookie(default=None)):
    if check_auth(portal_auth) != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    sess = terminals.get(tid)
    if sess is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    old_ws = sess.attached
    sess.attached = None
    _kill_terminal(sess)
    if old_ws is not None:
        await _term_safe_send(old_ws, {"t": "exit"})
        try:
            await old_ws.close()
        except Exception:
            pass
    return {"ok": True}


@app.websocket("/ws/terminal/{tid}")
async def terminal_websocket(websocket: WebSocket, tid: str):
    role = check_auth(websocket.cookies.get("portal_auth"))
    if role != "admin":
        await websocket.close(code=4001, reason="Unauthorized")
        return

    sess = terminals.get(tid)
    if sess is None:
        await websocket.close(code=4004, reason="Unknown terminal")
        return

    await websocket.accept()

    # Only one attachment: kick out any previous socket
    old_ws = sess.attached
    if old_ws is not None and old_ws is not websocket:
        sess.attached = None
        await _term_safe_send(old_ws, {"t": "detached"})
        try:
            await old_ws.close()
        except Exception:
            pass

    sess.attached = websocket

    # Replay full scrollback as one message
    await _term_safe_send(
        websocket,
        {"t": "o", "d": base64.b64encode(bytes(sess.scrollback)).decode("ascii")},
    )
    if not sess.alive:
        await _term_safe_send(websocket, {"t": "exit"})

    try:
        while True:
            try:
                msg = await websocket.receive_json()
            except (json.JSONDecodeError, ValueError):
                continue
            mtype = msg.get("t")
            if mtype == "i":
                data = msg.get("d")
                if isinstance(data, str) and sess.alive:
                    _term_write(sess, data.encode("utf-8"))
            elif mtype == "r":
                try:
                    rows = int(msg.get("rows", 24))
                    cols = int(msg.get("cols", 80))
                    fcntl.ioctl(
                        sess.fd,
                        termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0),
                    )
                except (OSError, ValueError, TypeError):
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        # Detach only — the shell keeps running (tmux-lite)
        if sess.attached is websocket:
            sess.attached = None
