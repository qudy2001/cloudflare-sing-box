"""Small LAN-only manager for a sing-box VMess WebSocket server."""

import html
import ipaddress
import json
import os
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DATA = Path(os.environ.get("MANAGER_DATA", "/data"))
IMPORT = Path(os.environ.get("MANAGER_IMPORT", "/import/server.json"))
SING_BOX = os.environ.get("SING_BOX_BIN", "/usr/local/bin/sing-box")
STATE_FILE = DATA / "state.json"
CONFIG_FILE = DATA / "server.json"
PORT = 10000
MANAGER_PORT = int(os.environ.get("MANAGER_PORT", "8080"))
ALLOWED_HOSTS = {item.strip().lower() for item in os.environ.get("MANAGER_ALLOWED_HOSTS", "").split(",") if item.strip()}
LOG_LEVELS = {"trace", "debug", "info", "warn", "error", "fatal", "panic"}
LOCK = threading.RLock()
CSRF_TOKEN = secrets.token_urlsafe(32)
PROCESS = None
STATE = None


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix=".new-", dir=DATA)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate(state):
    if not isinstance(state, dict):
        raise ValueError("设置格式无效")
    path = state.get("ws_path")
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 128 or any(c.isspace() for c in path) or "?" in path or "#" in path:
        raise ValueError("WebSocket 路径须以 / 开头，且不能包含空格、? 或 #")
    if state.get("log_level") not in LOG_LEVELS:
        raise ValueError("日志级别无效")
    users = state.get("users")
    if not isinstance(users, list) or not users or len(users) > 100:
        raise ValueError("至少需要一位用户，最多支持 100 位")
    seen_names, seen_ids = set(), set()
    for user in users:
        name = user.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 40 or name != name.strip() or any(ord(c) < 32 for c in name):
            raise ValueError("用户名须为 1–40 个可见字符")
        try:
            user_id = str(uuid.UUID(user.get("uuid", "")))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("用户 UUID 无效") from None
        if name in seen_names or user_id in seen_ids:
            raise ValueError("用户名或 UUID 重复")
        seen_names.add(name)
        seen_ids.add(user_id)


def server_config(state):
    validate(state)
    return {
        "log": {"level": state["log_level"]},
        "inbounds": [{
            "type": "vmess", "tag": "vmess-ws-in", "listen": "0.0.0.0",
            "listen_port": PORT,
            "users": [{"name": u["name"], "uuid": u["uuid"], "alterId": 0} for u in state["users"]],
            "transport": {"type": "ws", "path": state["ws_path"]},
        }],
        "outbounds": [{"type": "direct", "tag": "direct"}],
    }


def import_state():
    if not IMPORT.is_file():
        raise ValueError("找不到 /import/server.json；请先准备 server.json")
    source = json.loads(IMPORT.read_text(encoding="utf-8"))
    if set(source) - {"log", "inbounds", "outbounds"} or source.get("outbounds") != [{"type": "direct", "tag": "direct"}]:
        raise ValueError("现有配置包含管理页面不支持的其他设置；请先备份并使用仓库的 server.example.json")
    inbounds = source.get("inbounds", [])
    if len(inbounds) != 1 or inbounds[0].get("type") != "vmess" or inbounds[0].get("transport", {}).get("type") != "ws":
        raise ValueError("只能导入单个 VMess WebSocket 入站配置")
    inbound = inbounds[0]
    if set(inbound) - {"type", "tag", "listen", "listen_port", "users", "transport"}:
        raise ValueError("现有入站包含管理页面不支持的设置")
    if inbound.get("listen_port") != PORT:
        raise ValueError("现有代理端口须为 10000")
    state = {
        "ws_path": inbound["transport"].get("path", "/proxy"),
        "log_level": source.get("log", {}).get("level", "info"),
        "users": [{"name": u["name"], "uuid": u["uuid"]} for u in inbound.get("users", [])],
    }
    validate(state)
    return state


def check_config(path):
    result = subprocess.run([SING_BOX, "check", "-c", str(path)], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or "sing-box 配置检查失败").strip()[:500])


def launch():
    global PROCESS
    PROCESS = subprocess.Popen([SING_BOX, "run", "-c", str(CONFIG_FILE)])
    time.sleep(0.25)
    if PROCESS.poll() is not None:
        raise RuntimeError("sing-box 启动失败；请查看容器日志")


def stop():
    global PROCESS
    if PROCESS is not None and PROCESS.poll() is None:
        PROCESS.terminate()
        try:
            PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            PROCESS.kill()
            PROCESS.wait(timeout=5)


def apply_state(candidate):
    global STATE
    config = server_config(candidate)
    fd, temp_name = tempfile.mkstemp(prefix=".check-", suffix=".json", dir=DATA)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        check_config(temp)
        with LOCK:
            old_config = CONFIG_FILE.read_bytes() if CONFIG_FILE.exists() else None
            stop()
            os.replace(temp, CONFIG_FILE)
            try:
                launch()
                atomic_json(STATE_FILE, candidate)
                STATE = candidate
            except Exception:
                stop()
                if old_config is not None:
                    CONFIG_FILE.write_bytes(old_config)
                    launch()
                raise
    finally:
        temp.unlink(missing_ok=True)


def startup():
    global STATE
    DATA.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        STATE = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        validate(STATE)
        config = server_config(STATE)
        atomic_json(CONFIG_FILE, config)
        check_config(CONFIG_FILE)
        launch()
    else:
        apply_state(import_state())


def supervise():
    while True:
        time.sleep(2)
        with LOCK:
            if PROCESS is not None and PROCESS.poll() is not None:
                print("sing-box exited; restarting", flush=True)
                try:
                    launch()
                except Exception as exc:
                    print(f"restart failed: {exc}", flush=True)


def esc(value):
    return html.escape(str(value), quote=True)


def layout(title, content, notice=""):
    alert = f'<div class="notice">{esc(notice)}</div>' if notice else ""
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · sing-box 管理</title>
<style>
:root{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#182230;background:#f4f7fa}}
*{{box-sizing:border-box}}body{{margin:0}}header{{background:#102338;color:white;padding:22px 24px}}
header h1{{margin:0;font-size:22px}}header p{{margin:5px 0 0;color:#b9d0e4;font-size:14px}}
main{{max-width:980px;margin:28px auto;padding:0 18px}}section{{background:white;border:1px solid #dce4ed;border-radius:12px;padding:22px;margin:0 0 20px;box-shadow:0 3px 12px #12263a0a}}
h2{{font-size:19px;margin:0 0 16px}}p{{line-height:1.5}}label{{display:block;font-weight:600;margin:12px 0 5px}}
input,select{{font:inherit;border:1px solid #aebdcb;border-radius:7px;padding:9px;width:100%;max-width:460px;background:white}}
button{{font:inherit;border:0;border-radius:7px;background:#1769aa;color:white;padding:9px 14px;cursor:pointer}}
button.danger{{background:#a53535}}button.secondary{{background:#5b6a79}}form.inline{{display:inline-block;margin:3px 4px 3px 0}}
table{{border-collapse:collapse;width:100%}}th,td{{border-bottom:1px solid #e4e9ef;text-align:left;padding:10px 8px;vertical-align:middle}}th{{color:#526274;font-size:13px}}
code{{font-size:13px;overflow-wrap:anywhere}}small,.muted{{color:#5d6d7d}}.notice{{padding:12px 15px;background:#e8f5ee;border:1px solid #a9dcc2;border-radius:8px;margin-bottom:18px}}
.error{{background:#fff0ec;border-color:#edb1a4}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.actions{{white-space:nowrap}}
@media(max-width:650px){{.grid{{grid-template-columns:1fr}}table,thead,tbody,tr,td{{display:block}}thead{{display:none}}td{{padding:5px 0;border:0}}tr{{border-bottom:1px solid #e4e9ef;padding:12px 0}}.actions{{white-space:normal}}}}
</style></head><body><header><h1>sing-box 管理</h1><p>内网管理页面 · 代理端口 10000 · 管理端口 8080</p></header>
<main>{alert}{content}</main></body></html>'''


def field(name, value=""):
    return f'<input type="hidden" name="csrf" value="{CSRF_TOKEN}"><input type="hidden" name="{esc(name)}" value="{esc(value)}">'


def page(notice=""):
    with LOCK:
        state = json.loads(json.dumps(STATE))
        running = PROCESS is not None and PROCESS.poll() is None
    rows = []
    for user in state["users"]:
        user_id = esc(user["uuid"])
        rows.append(f'''<tr><td>{esc(user["name"])}</td><td><code>{user_id}</code></td><td class="actions">
<form class="inline" method="post" action="/users/rotate">{field("uuid", user["uuid"])}<button class="secondary" type="submit">重置 UUID</button></form>
<form class="inline" method="post" action="/users/delete">{field("uuid", user["uuid"])}<button class="danger" type="submit">删除</button></form></td></tr>''')
    options = "".join(f'<option value="{level}"{" selected" if level == state["log_level"] else ""}>{level}</option>' for level in ("info", "warn", "error", "debug", "trace", "fatal", "panic"))
    status = "运行中" if running else "已停止（正在尝试重启）"
    body = f'''<section><h2>服务器</h2><p>状态：<strong>{status}</strong>　VMess 端口：<strong>10000</strong></p>
<form method="post" action="/settings">{field("action", "save")}
<div class="grid"><div><label for="path">WebSocket 路径</label><input id="path" name="ws_path" required maxlength="128" value="{esc(state['ws_path'])}"></div>
<div><label for="level">日志级别</label><select id="level" name="log_level">{options}</select></div></div>
<p class="muted">更改路径后，也要更新客户端配置。保存时会检查配置并重启 sing-box，现有连接可能断开。</p><button type="submit">保存设置</button></form></section>
<section><h2>用户 <small>（{len(state['users'])}）</small></h2><div style="overflow-x:auto"><table><thead><tr><th>名称</th><th>UUID</th><th>操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<form method="post" action="/users/add">{field("action", "add")}<label for="name">新用户名称</label><input id="name" name="name" maxlength="40" required placeholder="例如：iPhone"><p><button type="submit">添加用户并生成 UUID</button></p></form>
<p class="muted">删除或重置 UUID 后，原 UUID 将失效；对应客户端也需要更新。</p></section>
<section><h2>访问范围</h2><p>此页面没有登录密码。只把容器的 8080 端口映射到可信内网，且不要为它创建 Cloudflare 公网路由。</p></section>'''
    return layout("概览", body, notice)


class Handler(BaseHTTPRequestHandler):
    def valid_host(self):
        try:
            host = urllib.parse.urlsplit("//" + self.headers.get("Host", "")).hostname
            if not host:
                return False
            if host.lower() == "localhost" or host.lower() in ALLOWED_HOSTS:
                return True
            ipaddress.ip_address(host)
            return True
        except ValueError:
            return False

    def respond(self, status, body, content_type="text/html; charset=utf-8"):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def redirect(self, message=""):
        self.send_response(303)
        self.send_header("Location", "/?notice=" + urllib.parse.quote(message))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.valid_host():
            self.respond(421, "Invalid host", "text/plain; charset=utf-8")
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/healthz":
            with LOCK:
                healthy = PROCESS is not None and PROCESS.poll() is None
            self.respond(200 if healthy else 503, "ok" if healthy else "unavailable", "text/plain; charset=utf-8")
        elif parsed.path == "/":
            notice = urllib.parse.parse_qs(parsed.query).get("notice", [""])[0][:200]
            self.respond(200, page(notice))
        else:
            self.respond(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        if not self.valid_host():
            self.respond(421, "Invalid host", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > 8192:
            self.respond(413, "Invalid request", "text/plain; charset=utf-8")
            return
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        value = lambda key: form.get(key, [""])[0]
        if not secrets.compare_digest(value("csrf"), CSRF_TOKEN):
            self.respond(403, "Forbidden", "text/plain; charset=utf-8")
            return
        try:
            with LOCK:
                candidate = json.loads(json.dumps(STATE))
                if self.path == "/users/add":
                    candidate["users"].append({"name": value("name").strip(), "uuid": str(uuid.uuid4())})
                elif self.path == "/users/delete":
                    candidate["users"] = [u for u in candidate["users"] if u["uuid"] != value("uuid")]
                    if len(candidate["users"]) == len(STATE["users"]):
                        raise ValueError("找不到该用户")
                elif self.path == "/users/rotate":
                    matches = [u for u in candidate["users"] if u["uuid"] == value("uuid")]
                    if len(matches) != 1:
                        raise ValueError("找不到该用户")
                    matches[0]["uuid"] = str(uuid.uuid4())
                elif self.path == "/settings":
                    candidate["ws_path"] = value("ws_path").strip()
                    candidate["log_level"] = value("log_level")
                else:
                    self.respond(404, "Not found", "text/plain; charset=utf-8")
                    return
                apply_state(candidate)
            self.redirect("已保存并应用")
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.respond(400, layout("保存失败", f'<section><h2>保存失败</h2><p>{esc(exc)}</p><p><a href="/">返回管理页面</a></p></section>'))


if __name__ == "__main__":
    startup()
    threading.Thread(target=supervise, daemon=True).start()
    print(f"manager listening on 0.0.0.0:{MANAGER_PORT}; proxy port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", MANAGER_PORT), Handler).serve_forever()
