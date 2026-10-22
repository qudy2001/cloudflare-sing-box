"""WebSocket ingress and approximate per-user traffic accounting."""

import collections
import ipaddress
import re
import select
import socket
import socketserver
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone


MAX_HEADER = 32768
CONNECTION_ID = re.compile(r"\[(\d+)\s+[^]]+\]\s+inbound/vmess\[[^]]+\]: (.*)")
SOURCE_PORT = re.compile(r"^inbound connection from .*:(\d+)$")
AUTH_USER = re.compile(r"^\[(.+)\] inbound (?:packet )?connection to ")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def utc_day():
    return datetime.now(timezone.utc).date().isoformat()


def read_header(sock):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed during WebSocket handshake")
        data.extend(chunk)
        if len(data) > MAX_HEADER:
            raise ValueError("WebSocket headers too large")
    end = data.index(b"\r\n\r\n") + 4
    return bytes(data[:end]), bytes(data[end:])


def request_meta(header):
    lines = header.decode("iso-8859-1", errors="replace").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or parts[0] != "GET":
        raise ValueError("not a WebSocket GET request")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    if headers.get("upgrade", "").lower() != "websocket":
        raise ValueError("not a WebSocket upgrade")
    return parts[1].split("?", 1)[0], headers


def visitor_meta(headers):
    ip = headers.get("cf-connecting-ip", "")
    try:
        ip = str(ipaddress.ip_address(ip))
    except ValueError:
        ip = None
    country = headers.get("cf-ipcountry", "").upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        country = None
    def location(key):
        value = headers.get(key, "")[:80]
        return value.encode("iso-8859-1", errors="replace").decode("utf-8", errors="replace") or None
    return ip, country, location("cf-region"), location("cf-ipcity")


class TrafficMonitor:
    def __init__(self, data_dir, public_port=10000, backend_port=10001):
        self.data_dir = data_dir
        self.public_port = public_port
        self.backend_port = backend_port
        self.lock = threading.RLock()
        self.ws_path = "/proxy"
        self.sessions = {}
        self.by_port = {}
        self.log_ids = {}
        self.pending = collections.defaultdict(lambda: [0, 0])
        self.next_id = 1
        self.db = None
        self.server = None

    def start(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "traffic.db", check_same_thread=False)
        with self.lock:
            self.db.execute("CREATE TABLE IF NOT EXISTS traffic_daily ("
                            "day TEXT NOT NULL, username TEXT NOT NULL, upload INTEGER NOT NULL DEFAULT 0, "
                            "download INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, username))")
            self.db.commit()
        monitor = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                monitor.handle_websocket(self.request)

        class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("0.0.0.0", self.public_port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self.flush_loop, daemon=True).start()

    def set_ws_path(self, path):
        with self.lock:
            self.ws_path = path

    def handle_websocket(self, client):
        backend = None
        session_id = None
        try:
            client.settimeout(10)
            request, extra_up = read_header(client)
            path, headers = request_meta(request)
            with self.lock:
                expected_path = self.ws_path
            if path != expected_path:
                client.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                return
            backend = socket.create_connection(("127.0.0.1", self.backend_port), timeout=10)
            client_ip, country, region, city = visitor_meta(headers)
            with self.lock:
                session_id = self.next_id
                self.next_id += 1
                port = backend.getsockname()[1]
                self.sessions[session_id] = {
                    "id": session_id, "port": port, "user": None, "ip": client_ip,
                    "country": country, "region": region, "city": city,
                    "started": time.time(), "upload": 0, "download": 0,
                    "rates": collections.deque(),
                }
                self.by_port[port] = session_id
            backend.sendall(request + extra_up)
            response, extra_down = read_header(backend)
            client.sendall(response + extra_down)
            if not response.startswith(b"HTTP/1.1 101 "):
                return
            if extra_up:
                self.record(session_id, len(extra_up), 0)
            if extra_down:
                self.record(session_id, 0, len(extra_down))
            client.settimeout(None)
            backend.settimeout(None)
            while True:
                readable, _, _ = select.select((client, backend), (), (), 60)
                if not readable:
                    continue
                for source in readable:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    if source is client:
                        backend.sendall(chunk)
                        self.record(session_id, len(chunk), 0)
                    else:
                        client.sendall(chunk)
                        self.record(session_id, 0, len(chunk))
        except (OSError, ValueError, ConnectionError):
            pass
        finally:
            if backend is not None:
                backend.close()
            if session_id is not None:
                with self.lock:
                    session = self.sessions.pop(session_id, None)
                    if session:
                        self.by_port.pop(session["port"], None)
            client.close()

    def consume_log(self, line):
        match = CONNECTION_ID.search(ANSI_ESCAPE.sub("", line))
        if not match:
            return
        connection_id, message = match.groups()
        source = SOURCE_PORT.match(message)
        user = AUTH_USER.match(message)
        now = time.time()
        with self.lock:
            if source:
                self.log_ids[connection_id] = (int(source.group(1)), now)
            elif user:
                item = self.log_ids.pop(connection_id, None)
                if item:
                    session_id = self.by_port.get(item[0])
                    session = self.sessions.get(session_id)
                    if session and session["user"] is None:
                        session["user"] = user.group(1)
                        totals = self.pending[(utc_day(), session["user"])]
                        totals[0] += session["upload"]
                        totals[1] += session["download"]
            if len(self.log_ids) > 1000:
                self.log_ids = {key: value for key, value in self.log_ids.items() if now - value[1] < 60}

    def record(self, session_id, upload, download):
        now = int(time.time())
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return
            session["upload"] += upload
            session["download"] += download
            rates = session["rates"]
            if rates and rates[-1][0] == now:
                rates[-1][1] += upload
                rates[-1][2] += download
            else:
                rates.append([now, upload, download])
            while rates and rates[0][0] < now - 4:
                rates.popleft()
            if session["user"]:
                totals = self.pending[(utc_day(), session["user"])]
                totals[0] += upload
                totals[1] += download

    def flush(self):
        with self.lock:
            if not self.db or not self.pending:
                return
            rows = [(day, user, amounts[0], amounts[1]) for (day, user), amounts in self.pending.items()]
            with self.db:
                self.db.executemany(
                    "INSERT INTO traffic_daily(day, username, upload, download) VALUES(?, ?, ?, ?) "
                    "ON CONFLICT(day, username) DO UPDATE SET "
                    "upload=upload+excluded.upload, download=download+excluded.download", rows)
            self.pending.clear()

    def flush_loop(self):
        while True:
            time.sleep(1)
            try:
                self.flush()
            except sqlite3.Error as exc:
                print(f"traffic database write failed: {exc}", flush=True)

    def snapshot(self, users):
        now = time.time()
        today = datetime.now(timezone.utc).date()
        first_day = (today - timedelta(days=29)).isoformat()
        with self.lock:
            rows = self.db.execute(
                "SELECT day, username, upload, download FROM traffic_daily WHERE day >= ?", (first_day,)
            ).fetchall() if self.db else []
            rows += [(day, user, value[0], value[1]) for (day, user), value in self.pending.items()]
            totals = collections.defaultdict(lambda: [[0, 0], [0, 0], [0, 0]])
            for day, user, upload, download in rows:
                age = (today - datetime.fromisoformat(day).date()).days
                for index, limit in enumerate((1, 7, 30)):
                    if 0 <= age < limit:
                        totals[user][index][0] += upload
                        totals[user][index][1] += download
            user_rows = {user["name"]: {
                "name": user["name"], "connections": 0, "ips": [], "locations": [],
                "upload_rate": 0, "download_rate": 0,
                "today": totals[user["name"]][0], "days7": totals[user["name"]][1],
                "days30": totals[user["name"]][2],
            } for user in users}
            connections = []
            for session in self.sessions.values():
                user = session["user"]
                if not user:
                    continue
                recent = [bucket for bucket in session["rates"] if bucket[0] >= int(now) - 2]
                up_rate = sum(bucket[1] for bucket in recent) / 3
                down_rate = sum(bucket[2] for bucket in recent) / 3
                location = " · ".join(value for value in (session["country"], session["region"], session["city"]) if value)
                connections.append({
                    "user": user, "ip": session["ip"], "location": location or None,
                    "seconds": int(now - session["started"]),
                    "upload_rate": up_rate, "download_rate": down_rate,
                    "upload": session["upload"], "download": session["download"],
                })
                if user in user_rows:
                    row = user_rows[user]
                    row["connections"] += 1
                    row["upload_rate"] += up_rate
                    row["download_rate"] += down_rate
                    if session["ip"] and session["ip"] not in row["ips"]:
                        row["ips"].append(session["ip"])
                    if location and location not in row["locations"]:
                        row["locations"].append(location)
            return {
                "active_users": sum(row["connections"] > 0 for row in user_rows.values()),
                "active_connections": len(connections),
                "upload_rate": sum(row["upload_rate"] for row in user_rows.values()),
                "download_rate": sum(row["download_rate"] for row in user_rows.values()),
                "users": list(user_rows.values()), "connections": connections,
            }
